#!/usr/bin/env bash
# =============================================================================
# 夜跑变异测试闭环本地包装脚本（cron / systemd timer 触发面）
# =============================================================================
# 作用：把夜跑闭环四步串成一条命令——运行变异测试、解析存活变异体为统一
#       报告、baseline 只涨不跌检查、按文件分组创建补测 issue（人读
#       GitHub issue + agent 队列 JSON）。全程写带时间戳的日志文件并自动
#       清理过期日志；任何一步失败立即退出，退出码沿用失败工具的退出码
#       （baseline 回归为门槛失败，退出码 2）。
#
# 使用方式（复制到目标项目后使用；本仓自身不运行该闭环）：
#   1. 把本文件复制为目标项目的 scripts/nightly-mutation-runner.sh 并
#      chmod +x；
#   2. 把lazypack-setup 包 assets/mutation/scripts/ 的工具脚本一并复制到目标项目 scripts/：
#      - TypeScript：parse-stryker-report.mjs、mutation-baseline.mjs、
#        create-mutation-issues.mjs；
#      - Python：parse_mutmut_report.py、mutation-baseline.mjs、
#        create-mutation-issues.mjs；
#   3. gh CLI 认证（gh auth login 的持久凭据，或导出 GH_TOKEN）；未认证时
#      先用 --dry-run 验证链路（零 gh 调用）；
#   4. 手动跑通后再挂定时：crontab 示例与 systemd service/timer 模板见
#      lazypack-setup 包 assets/mutation/config/。
#
# 用法：
#   scripts/nightly-mutation-runner.sh [选项]
#
# 选项：
#   --lang ts|py        变异测试工具链：ts=Stryker，py=mutmut（默认 ts）
#   --project-dir DIR   目标项目根（默认：本脚本所在目录的上一级，即脚本
#                       位于 <项目>/scripts/ 时的项目根）
#   --log-dir DIR       日志目录（默认环境变量 MUTATION_LOG_DIR，再默认
#                       /tmp/nightly-mutation）
#   --log-keep DAYS     日志保留天数，到期自动清理（默认 14）
#   --dry-run           issue 创建走 --dry-run：零 gh 调用，只写
#                       .mutation-queue/ 队列文件与 body 预览
#   -h, --help          显示本帮助并退出
#
# 流程与前置条件（与 assets/mutation/workflows/ 同一口径）：
#   步骤 1  运行变异测试   ts: npx stryker run（要求 reporters 含 "json"，
#                          建议不配 thresholds.break，门槛由 baseline 承担）
#                          py: mutmut run（固定 2.x；存活/超时/可疑变异体
#                          的按位或退出码属预期输入；致命错误位退出、越界
#                          退出码、traceback 信号与 .mutmut-cache 新鲜度校
#                          验失败在本步裁决为真实失败，陈旧缓存不进入后续
#                          解析；退出码含义见 run_py_pipeline 步骤 1 注释）
#   步骤 2  解析存活变异体 ts: parse-stryker-report.mjs 读取
#                          reports/mutation/mutation.json
#                          py: 先 mutmut show all 捕获 diff，再由
#                          parse_mutmut_report.py 读 .mutmut-cache；
#                          两者的统一报告落项目根 unified-mutation-report.json
#   步骤 3  baseline 检查  ts: 读原生 Stryker 报告，首次 init、之后 check
#                          py: 需项目自备 mutmut results-export JSON
#                          （mutmut-results-export.json；baseline 工具不读
#                          .mutmut-cache，缺口见
#                          docs/research/vscode-scheduled-tasks.md §7.1），
#                          缺文件时跳过并记 WARN，其余环节照常
#   步骤 4  创建补测 issue gh CLI；存在 .equivalent-mutants.json 自动豁免
#                          过滤；与 open 同名 issue 去重
#   首次运行自动 init 基线；.mutation-baseline.json 按契约提交进版本库
#   （否则每轮重 init，棘轮失效）。
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ----------------------------- 默认值 ---------------------------------------
lang="ts"
project_dir=""
log_dir="${MUTATION_LOG_DIR:-/tmp/nightly-mutation}"
log_keep_days="14"
dry_run="false"
LOG_FILE=""

# ----------------------------- 通用函数 -------------------------------------

usage() {
  cat <<'EOF'
夜跑变异测试闭环本地包装脚本（cron / systemd timer 触发面）

用法：
  scripts/nightly-mutation-runner.sh [选项]

选项：
  --lang ts|py        变异测试工具链：ts=Stryker，py=mutmut（默认 ts）
  --project-dir DIR   目标项目根（默认：脚本所在目录的上一级）
  --log-dir DIR       日志目录（默认 $MUTATION_LOG_DIR 或 /tmp/nightly-mutation）
  --log-keep DAYS     日志保留天数，到期自动清理（默认 14）
  --dry-run           issue 创建走 --dry-run（零 gh 调用，只写队列与预览）
  -h, --help          显示本帮助并退出

流程：运行变异测试 -> 解析存活变异体 -> baseline 检查 -> 创建补测 issue。
任一步失败立即退出，退出码沿用失败工具（baseline 回归=2，用法错误=1）。
EOF
}

# 统一日志行：ISO-8601 本地时间 + 级别 + 正文（stdout/stderr 已整体经 tee
# 重定向，控制台与日志文件双写）
log() {
  printf '%s [%s] %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$1" "$2"
}

die() {
  log "ERROR" "$1"
  exit "${2:-1}"
}

# 包装每个流水线步骤：失败即记日志并沿用工具退出码退出
run_step() {
  local step_name="$1"
  shift
  log "INFO" "==> ${step_name}"
  if "$@"; then
    log "INFO" "完成：${step_name}"
  else
    local rc=$?
    log "ERROR" "步骤失败（退出码 ${rc}）：${step_name}"
    log "ERROR" "完整输出见日志：${LOG_FILE}"
    exit "$rc"
  fi
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    die "缺少依赖命令：$1（${2:-请先安装并确保在 PATH 中}）"
  fi
}

# ----------------------------- 参数解析 -------------------------------------

while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    --lang)
      [ $# -ge 2 ] || die "参数 $1 缺少值"
      lang="$2"
      shift 2
      ;;
    --project-dir)
      [ $# -ge 2 ] || die "参数 $1 缺少值"
      project_dir="$2"
      shift 2
      ;;
    --log-dir)
      [ $# -ge 2 ] || die "参数 $1 缺少值"
      log_dir="$2"
      shift 2
      ;;
    --log-keep)
      [ $# -ge 2 ] || die "参数 $1 缺少值"
      log_keep_days="$2"
      shift 2
      ;;
    --dry-run)
      dry_run="true"
      shift
      ;;
    --*)
      die "未知参数：$1（--help 查看用法）"
      ;;
    *)
      die "意外参数：$1（本脚本不接受位置参数，--help 查看用法）"
      ;;
  esac
done

case "$lang" in
  ts|py) ;;
  *) die "--lang 只接受 ts 或 py（收到：${lang}）" ;;
esac

case "$log_keep_days" in
  ''|*[!0-9]*) die "--log-keep 需要非负整数（收到：${log_keep_days}）" ;;
esac

[ -n "$project_dir" ] || project_dir="$(dirname "$SCRIPT_DIR")"
if [ ! -d "$project_dir" ]; then
  die "项目目录不存在：${project_dir}"
fi
if [ ! -d "${project_dir}/scripts" ]; then
  die "项目目录缺少 scripts/ 子目录（工具脚本应随迁到该处）：${project_dir}/scripts"
fi

# ----------------------------- 日志管理 -------------------------------------

mkdir -p "$log_dir"
LOG_FILE="${log_dir}/nightly-mutation-$(date '+%Y%m%d-%H%M%S').log"
# 控制台与日志文件双写（stdout/stderr 整体经 tee 重定向），cron 下也不丢输出
exec > >(tee -a "$LOG_FILE") 2>&1

# 日志清理：删除超过保留期的旧日志，避免日志目录无限增长
# （-mtime +N 匹配修改时间早于约 N 天的文件，本轮新建日志不受影响）
find "$log_dir" -maxdepth 1 -type f -name 'nightly-mutation-*.log' -mtime +"$log_keep_days" -delete

# 未包裹步骤的命令（cd、mkdir、find 等）失败时兜底报错
trap 'rc=$?; log "ERROR" "命令在第 ${LINENO} 行失败（退出码 ${rc}）；日志：${LOG_FILE}"; exit "$rc"' ERR

log "INFO" "夜跑变异测试闭环开始：lang=${lang} project_dir=${project_dir}"
log "INFO" "日志文件：${LOG_FILE}（保留 ${log_keep_days} 天）"

cd "$project_dir"

# ----------------------------- 依赖检查 -------------------------------------

require_cmd node "Node.js（解析器、baseline、issue 创建工具都是 Node 程序）"
if [ "$dry_run" = "false" ]; then
  require_cmd gh "GitHub CLI（issue 创建用；gh auth login 或设置 GH_TOKEN）"
  if [ -z "${GH_TOKEN:-}" ] && ! gh auth status >/dev/null 2>&1; then
    die "gh CLI 未认证：先 gh auth login，或在 cron/systemd 环境导出 GH_TOKEN"
  fi
fi

# ----------------------------- 流水线步骤 -----------------------------------

run_ts_pipeline() {
  require_cmd npx "npm 随 Node.js 安装"
  # 先确认 Stryker 已随项目本地安装，避免 npx 在无人值守环境里挂起等网络
  # 安装（cron/定时器里没有交互输入）
  if [ ! -x node_modules/.bin/stryker ]; then
    die "未找到本地 Stryker（node_modules/.bin/stryker）：请在项目里安装（npm install --save-dev @stryker-mutator/core）"
  fi

  # 步骤 1：全量变异测试（原生 JSON 报告默认落 reports/mutation/mutation.json）
  run_step "运行变异测试（npx stryker run）" npx stryker run

  # 步骤 2：解析存活变异体为统一报告（落项目根；--output 不创建父目录）
  run_step "解析存活变异体（parse-stryker-report.mjs）" \
    node scripts/parse-stryker-report.mjs \
    --input reports/mutation/mutation.json \
    --output unified-mutation-report.json

  # 步骤 3：baseline 只涨不跌检查（读原生 Stryker 报告；回归=退出码 2）
  if [ -f .mutation-baseline.json ]; then
    run_step "检查 baseline（check；回归=失败）" \
      node scripts/mutation-baseline.mjs check \
      --input reports/mutation/mutation.json \
      --lang ts
  else
    run_step "初始化 baseline（首次运行）" \
      node scripts/mutation-baseline.mjs init \
      --input reports/mutation/mutation.json \
      --lang ts
    log "WARN" "已生成 .mutation-baseline.json，请提交进版本库（否则每轮重 init，棘轮失效）"
  fi
}

# 把 mutmut 2.x run 的按位或退出码翻译成人读类别文本（供日志与报错引用；
# 退出码含义见 run_py_pipeline 步骤 1 注释，调用方无须自行拦截越界码）
mutmut_exit_meaning() {
  local rc="$1"
  if [ "$rc" -eq 0 ]; then
    printf '全部变异体被杀死'
    return
  fi
  if [ "$rc" -ge 16 ]; then
    printf '越界退出码（超出 mutmut 位标志空间 0-15，多为信号终止 128+n）'
    return
  fi
  local -a parts=()
  if [ "$((rc & 1))" -ne 0 ]; then parts+=("致命错误"); fi
  if [ "$((rc & 2))" -ne 0 ]; then parts+=("存活变异体"); fi
  if [ "$((rc & 4))" -ne 0 ]; then parts+=("超时变异体"); fi
  if [ "$((rc & 8))" -ne 0 ]; then parts+=("可疑变异体"); fi
  local IFS='|'
  printf '%s' "${parts[*]}"
}

run_py_pipeline() {
  local python_bin
  require_cmd mutmut "mutmut 2.x（pip install \"mutmut<3\"；3.x 不再写 .mutmut-cache）"
  if command -v python3 >/dev/null 2>&1; then
    python_bin="python3"
  elif command -v python >/dev/null 2>&1; then
    python_bin="python"
  else
    die "缺少依赖命令：python3（解析器 parse_mutmut_report.py 要求 Python 3.8+）"
  fi

  # 步骤 1：全量变异测试。mutmut 2.x 的 run 退出码不是成败两态，而是结果
  # 类别的按位或（bit-OR）组合（依据 mutmut 2.5.1 源码 run --help 帮助文本
  # 与 mutmut/__init__.py compute_exit_code 实现；pip install "mutmut<3" 现今
  # 解析到的即该版）：
  #   0         全部变异体被杀死
  #   位 0（1） mutmut 致命错误（中途异常、基线测试没跑干净等）→ 真实失败
  #   位 1（2） 存在存活变异体（夜跑闭环要处理的输入，属预期结果）
  #   位 2（4） 存在超时变异体（同样属预期结果类别）
  #   位 3（8） 存在可疑变异体（测试显著变慢但未超时，同样属预期结果）
  #   1..15     上述位的任意组合：偶数（位 0 未置）= 本轮正常跑完、结果已
  #             写入缓存；奇数（位 0 置位）= mutmut 自报致命错误
  #   >=16      超出 mutmut 退出码空间（信号终止 128+n 等异常终止）
  # 注意：mutmut 的 click 用法错误（如 paths_to_mutate 缺失）同样退出 2，
  # 与「存在存活变异体」同码，但该场景本轮不写缓存，由下方新鲜度校验拦截。
  # 本步就地裁决（比 GitHub Actions 模板的 continue-on-error 更严格：那边的
  # 兜底是后续导出/解析步骤硬失败）：
  #   a) 起跑前落标记文件；输出整体捕获到 .mutmut-run-output.txt 备查；
  #   b) 非零退出且输出含 Python traceback → mutmut 中途崩溃、缓存可能
  #      残缺，按真实失败退出（沿用 mutmut 退出码）——额外保险，正常情形
  #      已被致命错误位覆盖，保留以防退出码口径之外的崩溃形态；
  #   c) 奇数退出码（致命错误位置位）或 >=16 → 真实执行失败，中止（缓存
  #      即便在场也可能是残缺的部分产物，不进入解析）；
  #   d) .mutmut-cache 缺失或修改时间不晚于标记 → mutmut 本轮没有写缓存，
  #      在场的是陈旧数据，拒绝带着陈旧缓存进入解析，按真实执行/配置失败
  #      退出（沿用 mutmut 退出码）；
  #   e) 其余情形（退出码 0 或偶数组合）且缓存在场新鲜 → 按预期结果放行，
  #      非零退出记 WARN 写明退出码类别。
  # 新鲜度按 mtime 严格晚于标记判定（find -newer），秒级粒度下存在同秒
  # 边角，真实施行耗时远超 1 秒，不影响真实运行。
  local mutmut_rc="0"
  local run_marker="${log_dir}/.mutmut-run-start-$$"
  : > "$run_marker"
  log "INFO" "==> 运行变异测试（mutmut run；存活/超时/可疑变异体的非零退出属预期，致命错误位或无新缓存中止）"
  set +e
  mutmut run 2>&1 | tee .mutmut-run-output.txt
  mutmut_rc=$?
  set -e
  if [ "$mutmut_rc" -ne 0 ] && grep -q "Traceback (most recent call last)" .mutmut-run-output.txt; then
    rm -f "$run_marker"
    die "mutmut run 中途崩溃（退出码 ${mutmut_rc}，输出含 Python traceback，缓存可能残缺）；完整输出：.mutmut-run-output.txt，日志：${LOG_FILE}" "$mutmut_rc"
  fi
  if [ "$((mutmut_rc & 1))" -ne 0 ] || [ "$mutmut_rc" -ge 16 ]; then
    rm -f "$run_marker"
    die "mutmut run 真实执行失败（退出码 ${mutmut_rc}：$(mutmut_exit_meaning "$mutmut_rc")）——致命错误位（1）置位或超出 mutmut 退出码空间 0-15，不是存活/超时/可疑变异体的预期退出；先修复配置/测试再重跑；输出：.mutmut-run-output.txt，日志：${LOG_FILE}" "$mutmut_rc"
  fi
  if [ ! -f .mutmut-cache ] || [ -z "$(find .mutmut-cache -maxdepth 0 -newer "$run_marker")" ]; then
    rm -f "$run_marker"
    if [ "$mutmut_rc" -eq 0 ]; then
      die "mutmut run 退出码 0 但本轮没有写出新的 .mutmut-cache（多为配置问题：paths_to_mutate 未命中源码、runner 起不来等）；输出：.mutmut-run-output.txt，日志：${LOG_FILE}"
    fi
    die "mutmut run 失败（退出码 ${mutmut_rc}：$(mutmut_exit_meaning "$mutmut_rc")）且 .mutmut-cache 缺失或陈旧——mutmut 本轮没有写缓存，这不是存活变异体的预期退出（mutmut 的 click 用法错误也以 2 退出，同在此拦截）；先修复配置/测试再重跑；输出：.mutmut-run-output.txt，日志：${LOG_FILE}" "$mutmut_rc"
  fi
  rm -f "$run_marker"
  if [ "$mutmut_rc" -ne 0 ]; then
    log "WARN" "mutmut run 退出码 ${mutmut_rc}（$(mutmut_exit_meaning "$mutmut_rc")）：.mutmut-cache 已确认为本轮新鲜产物，按存活/超时/可疑变异体的预期输入继续"
  fi

  # 步骤 2：先捕获 mutmut show 全量 diff（缓存不含替换片段，存活条目必须
  # 配 diff），再把 .mutmut-cache 解析为统一报告（落项目根）
  log "INFO" "==> 捕获 mutmut show 全量输出（.mutmut-show-all.txt）"
  if ! mutmut show all > .mutmut-show-all.txt; then
    log "ERROR" "mutmut show all 失败（无法为存活变异体配 diff）；日志：${LOG_FILE}"
    exit 1
  fi
  run_step "解析存活变异体（parse_mutmut_report.py）" \
    "$python_bin" scripts/parse_mutmut_report.py \
    --input .mutmut-cache \
    --show .mutmut-show-all.txt \
    --output unified-mutation-report.json

  # 步骤 3：baseline 只涨不跌检查（可选）。baseline 工具不读 .mutmut-cache，
  # 需项目自备 mutmut results-export JSON；缺文件时跳过并如实记日志。
  if [ -f mutmut-results-export.json ]; then
    if [ -f .mutation-baseline.json ]; then
      run_step "检查 baseline（check；回归=失败）" \
        node scripts/mutation-baseline.mjs check \
        --input mutmut-results-export.json \
        --lang py
    else
      run_step "初始化 baseline（首次运行）" \
        node scripts/mutation-baseline.mjs init \
        --input mutmut-results-export.json \
        --lang py
      log "WARN" "已生成 .mutation-baseline.json，请提交进版本库（否则每轮重 init，棘轮失效）"
    fi
  else
    log "WARN" "跳过 baseline 步骤：未找到 mutmut-results-export.json（baseline 工具不读 .mutmut-cache，见 docs/research/vscode-scheduled-tasks.md §7.1）"
  fi
}

run_issue_creation() {
  # 步骤 4：按文件分组创建补测 issue + agent 队列 JSON（与 open 同名 issue
  # 去重；存在 .equivalent-mutants.json 自动应用豁免过滤）
  local -a issue_cmd
  issue_cmd=(node scripts/create-mutation-issues.mjs --input unified-mutation-report.json)
  if [ -f .equivalent-mutants.json ]; then
    issue_cmd+=(--exemptions .equivalent-mutants.json)
  fi
  if [ "$dry_run" = "true" ]; then
    issue_cmd+=(--dry-run)
    log "INFO" "dry-run 模式：不调用 gh，只写 .mutation-queue/ 队列文件与 body 预览"
  fi
  run_step "创建补测 issue（create-mutation-issues.mjs）" "${issue_cmd[@]}"
}

# ----------------------------- 主流程 ---------------------------------------

if [ "$lang" = "ts" ]; then
  run_ts_pipeline
else
  run_py_pipeline
fi
run_issue_creation

log "INFO" "夜跑闭环完成：统一报告 unified-mutation-report.json；agent 队列 .mutation-queue/；日志 ${LOG_FILE}"
