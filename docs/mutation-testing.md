# 变异测试（夜跑质检层）

变异测试是 CI 四门禁（format / lint / type / test）之外的**补充质检层**：把源码
机械地改坏一小处（运算符翻转、常量加减一、条件取反……），逐个确认现有用例
能否发现。「改坏了测试仍然全绿」的位置就是测试缺口。

- **不进 pre-commit，不进 PR 门禁**：首轮试点单次实跑约 4.5 分钟，按夜跑节奏用。
- **工具**：mutmut 2.5.1（`mutmut<3`；3.x 不再写 `.mutmut-cache`，配方链路读不到）。
- **来源**：[lazypack-discipline](https://github.com/jaredshuai/lazypack-discipline) 的
  `mutation-testing` 配方（recipe v1.0.0）。`scripts/` 下 5 个工具脚本由配方**逐字分发**
  （其中 4 个核心脚本文件头带 `@version 1.0.0`），升级方式见文末。格式契约与运营手册：
  [运营手册](https://github.com/jaredshuai/lazypack-discipline/blob/main/docs/quality-gates/mutation-testing.md)、
  [夜跑闭环](https://github.com/jaredshuai/lazypack-discipline/blob/main/docs/quality-gates/nightly-mutation-loop.md)。

## 首轮试点范围

| 文件 | 职责 | 变异体 | Killed | Survived | 分数 |
| --- | --- | ---: | ---: | ---: | ---: |
| `backend/app/services/audit.py` | 审计载荷脱敏、审计写入 | 127 | 101 | 26 | 79.53% |
| `backend/app/services/notifications.py` | Webhook URL 脱敏、渠道分派、投递原因码 | 122 | 77 | 45 | 63.11% |
| 合计 | | 249 | 178 | 71 | **71.49%** |

选这两个文件的原因：都是安全相关的纯逻辑（凭据脱敏、渠道分派），守护用例是
不依赖数据库的快速单元用例；而且把慢用例 `test_access_wiring` /
`test_trusted_proxy` 也放进来（除 helm 渲染与 deploy 脚本用例外的全部非数据库
用例，29 个文件）重跑一轮，这两个文件的逐个变异体结果与快速守护集完全一致
（实测），不存在「因为少跑了用例才存活」的误报。

暂不纳入的文件与原因（`deps.py` 一行是实测结论，其余是只数了变异体、没有实跑的静态盘点）：

| 文件 | 原因 |
| --- | --- |
| `backend/app/api/deps.py` | 73 个变异体，完整分数 83.56%。4 个变异体只有慢用例 `test_access_wiring` / `test_trusted_proxy` 才能杀死，而把这两个文件放进 runner 会让每个存活变异体多花约 6 秒（整轮 14 分钟）。要么连慢用例一起纳入并接受预算，要么等 coverage 用例选择。 |
| `backend/app/api/access.py` | 54 个变异体（未实跑）：守护用例 `test_access_wiring` 单文件约 5 秒。 |
| `backend/app/core/config.py` | 139 个变异体（未实跑）：主体是 `Settings` 的 pydantic 字段默认值，按配置层处理属于结构性豁免；`parse_trusted_proxy_networks` / `validate_auth_settings` 两个纯函数值得纳入，但 mutmut 只能按文件圈范围，没法把它们单独拎出来。 |
| `backend/app/services/certificates.py` | 143 个变异体（未实跑）：证书状态的核心用例需要 `DATABASE_URL`，纯单元环境下会 skip，直接跑会把「没连库」误报成存活。 |
| `frontend/` | 用的是 `node:test`，Stryker 没有对应 runner（配方里提到可兜底的 `@stryker-mutator/command-runner` 已从 npm 下架）。 |

## 文件清单

| 路径 | 作用 |
| --- | --- |
| `setup.cfg` | `[mutmut]` 段：变异范围、测试目录、runner。mutmut 2.x 只读当前目录的配置，所以必须在仓库根。 |
| `pytest-mutation.ini` | 守护用例集（有序）与 pytest 开关，被 `setup.cfg` 的 runner 以 `-c` 引用；日常 pytest 不读它。 |
| `backend/pyproject.toml` 的 `mutation` extra | 声明 `mutmut<3`。`uv sync --extra dev` 不安装，不影响 CI 与镜像构建。 |
| `scripts/mutation-baseline.mjs` | 基线 init / check / update（棘轮只涨不跌）。配方分发。 |
| `scripts/parse-stryker-report.mjs` | Stryker 报告解析器。配方分发，本仓暂未用到（前端无 Stryker runner）。 |
| `scripts/parse_mutmut_report.py` | `.mutmut-cache` + `mutmut show all` → 统一变异体报告。配方分发。 |
| `scripts/create-mutation-issues.mjs` | 统一报告 → 按文件分组的补测 issue + `.mutation-queue/` 队列文件。配方分发。 |
| `scripts/nightly-mutation-runner.sh` | 本地一条龙包装脚本（cron / systemd 触发面）。配方分发。 |
| `.github/workflows/nightly-mutation-py.yml` | GitHub Actions 夜跑闭环，手动触发 + 每日 03:00（北京时间）定时；定时默认 `--dry-run`。 |
| `docs/setup/mutation-testing.{service,timer}`、`docs/setup/crontab.example` | 本地定时模板，默认不启用。 |
| `.mutation-baseline.json` | 变异分数基线，**提交进版本库**（棘轮依赖它）。 |
| `.equivalent-mutants.json` | 可选，等价变异体豁免清单，评审后提交。 |

每轮运行的产物（`.mutmut-cache`、`.mutmut-show-all.txt`、`.mutmut-run-output.txt`、
`mutmut-results-export.json`、`unified-mutation-report.json`、`.mutation-queue/`）已加进
`.gitignore`，不提交。

## 本地运行

```bash
# 1. 安装（mutmut 只在叠加 mutation extra 时进入 backend 虚拟环境）
uv sync --project backend --extra dev --extra mutation --locked

# 2. 只跑变异测试（必须在仓库根目录）。想让结果全量重算就先删 .mutmut-cache
PATH="$PWD/backend/.venv/bin:$PATH" mutmut run

# 3. 或者一条龙：实跑 -> 解析 -> 基线（默认跳过，见「夜跑闭环」）-> 补测 issue
#    （--dry-run = 零 gh 调用）。
#    必须先删缓存：结果全部命中缓存时 mutmut 不会重写 .mutmut-cache，runner
#    脚本会把它误判成「陈旧缓存」并以退出码 2 失败（实测）
rm -f .mutmut-cache && PATH="$PWD/backend/.venv/bin:$PATH" scripts/nightly-mutation-runner.sh --lang py --dry-run
```

`mutmut run` 在有存活变异体时以非零码退出（退出码是结果类别的按位或：2 有存活、
4 有超时、8 有可疑、1 致命错误），这是预期结果，不是故障。

注意：

- **mutmut 会就地改写被变异的源文件再还原**，必须在干净的工作区里串行运行；
  中途崩溃时源码可能停在变异状态，`git status` 能看出来（同目录会留 `.bak`）。
- **改了 runner 或范围之后先删 `.mutmut-cache`**：mutmut 2.x 的结果缓存与基线
  耗时只按测试文件内容取 hash，只改 runner 不会让旧结果失效。
- runner 的用例集里带 `--continue-on-collection-errors`，不能去掉：被变异模块在
  import 期崩溃时 pytest 默认退出码是 2，而 mutmut 2.x 只把退出码 1 当作
  「测试失败」，其余一律记成存活。

## 夜跑闭环

```
mutmut run
  -> mutmut result-ids <status> x6      -> mutmut-results-export.json   （六类状态的 id 清单）
  -> mutmut show all + parse_mutmut_report.py
                                        -> unified-mutation-report.json（存活/可疑变异体，带替换片段）
  -> mutation-baseline.mjs init|check   （首轮冻结，之后只涨不跌；回归退出码 2）
  -> create-mutation-issues.mjs         （按文件分组：GitHub issue + .mutation-queue/*.json）
```

- **分数口径**：`score = (killed + timeout) / total × 100`（百分制）。Timeout 计入检出，
  Suspicious（测试明显变慢但没超时）不计入。
- **基线**：`.mutation-baseline.json` 记录 score / killed / survived / total。
  补测合入让分数上涨后执行 `mutation-baseline.mjs update` 再提交基线；
  分数下降时 workflow 失败并中止 issue 创建，由人先处理。
  变异范围或工具变化后基线不可比，手动删掉重新 `init`。
- **等价变异体**：确认某条存活变异体在任何输入下行为都不变时，不要硬写测试，
  按[豁免格式](https://github.com/jaredshuai/lazypack-discipline/blob/main/docs/formats/equivalent-mutants.md)
  记入 `.equivalent-mutants.json`（reason 必填且可检验），下一轮起不再出现在 issue 里。
- **实建 issue**：与 open 状态的同名 issue 按文件去重，重复夜跑只跳过不重复建。

本地 `nightly-mutation-runner.sh --lang py` 有两个已知缺口：

- 它不生成 `mutmut-results-export.json`：文件不存在时跳过基线检查并记一条 WARN；
  文件存在时（比如上一轮手动生成的）会直接拿它比较，不校验是否对应当前这一轮
  （GitHub Actions 版 workflow 每轮自己导出，没有这个问题）。需要在本地做基线
  检查时，跑完后手动执行：

```bash
export PATH="$PWD/backend/.venv/bin:$PATH"
python - <<'PY'
import json, subprocess
export = {s: subprocess.run(["mutmut", "result-ids", s], capture_output=True, text=True, check=True).stdout.split()
          for s in ("killed", "timeout", "survived", "suspicious", "skipped", "untested")}
json.dump(export, open("mutmut-results-export.json", "w"), indent=2)
PY
node scripts/mutation-baseline.mjs check --input mutmut-results-export.json --lang py
```

- 它靠「缓存文件是否比本轮新」判断缓存新鲜度，而结果全部命中缓存时 mutmut 不会
  重写 `.mutmut-cache`，所以代码没变化的夜里重跑会被误判成失败（退出码 2）。
  调用前先删 `.mutmut-cache`。

## 启用夜跑

### GitHub Actions

`.github/workflows/nightly-mutation-py.yml` 在 Actions 页面可手动触发
（`workflow_dispatch`），并已开启每日定时：`cron: "0 19 * * *"`（UTC，
即北京时间次日 03:00）。

- 定时与手动默认都是 `--dry-run`：零 gh 调用，只上传 `.mutation-queue/` 预览与报告产物。
- 手动触发勾选 `create_issues` 才真正建 issue（凭据用仓库自带的 `GITHUB_TOKEN`，无需额外 secret）。
- 定时事件没有 inputs，当前由步骤内的 `SCHEDULE_CREATES_ISSUES` 决定模式，值为
  `false`（保持 `--dry-run`）；要让定时实建 issue，把该值改为 `true`。

### 本机 cron / systemd

模板在 `docs/setup/`，二选一，启用步骤见文件头。两处适配：

- 这台机器的时区是 `America/New_York`，timer 的时间带了 `UTC` 后缀（北京时间
  03:00），cron 示例按本地时间换算过，改时间时注意换算。
- 模板每轮都先删 `.mutmut-cache` 再跑：runner 脚本靠「缓存文件是否比本轮新」
  判断新鲜度，而结果全部命中缓存时 mutmut 不重写缓存，代码没变化的夜里会被
  误判成失败。

## 首轮实测数据（2026-11-27，jxccs）

环境：Python 3.12.12、pytest 9.0.3、mutmut 2.5.1、Node 26.4.0；配方脚本来自
lazypack-discipline `9746a99`（@version 1.0.0）。mutmut 2.x 是**串行**的（单进程
逐个变异体，不随核数扩展），每个变异体都重新起一次 pytest。

| 轮次 | 变异范围 | 守护用例 | 基线耗时 | 总耗时 | Total | Killed | Survived | Timeout | Suspicious | 分数 |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A（探索） | 3 文件（含 `deps.py`） | 除 helm / deploy 脚本用例外的全部非数据库用例（29 个文件） | 7.3s | 14m24s | 322 | 239 | 83 | 0 | 0 | 74.22% |
| B（探索） | 3 文件（含 `deps.py`） | 快速守护集（27 个文件） | 1.3s | 5m54s | 322 | 235 | 87 | 0 | 0 | 72.98% |
| C（**首轮定稿**） | 2 文件 | 快速守护集 | 1.3s | **4m35s** | 249 | 178 | 71 | 0 | 0 | **71.49%** |

- A → B 只差 4 个 `deps.py` 变异体（只有慢用例能杀死）；`audit.py` 与
  `notifications.py` 的结果在两轮之间逐条一致。
- Timeout / Suspicious 均为 0。mutmut 2.x 没有 Stryker 的 NoCoverage 类别；
  本轮没有启用 coverage 用例选择，untested / skipped 也是 0。
- 耗时几乎全在「每个变异体起一次 pytest」上：被杀死的变异体约 0.9 秒
  （首个失败即停），存活的要跑完守护集。

### 存活变异体的信噪比（71 条）

| 类别 | 条数 | 占比 | 说明 |
| --- | ---: | ---: | --- |
| 真缺口，高价值 | 17 | 24% | 安全 / 业务行为没被任何用例约束 |
| 真缺口，中价值 | 45 | 63% | 边界值、结果契约、未覆盖分支 |
| 噪声 | 9 | 13% | 等价变异体、日志文案、超时时间常量 |

71 条存活背后大约只有 20 处独立缺口：同一处缺口会裂成多条记录（敏感键名 9 条、
飞书 / 钉钉分派 8 条、邮件成功路径 14 条），一条参数化用例就能全部杀死。

抽样复核（在分析副本上 `mutmut apply` 后对比行为）：

| 变异体 | 原代码 | 变异后 | 判定 |
| --- | --- | --- | --- |
| `audit.py` L26 敏感键 `"password"` → `"XXpasswordXX"` | `{"password": "***"}` | `{"password": "hunter2"}` | **真缺口**：键名屏蔽表里 9 个词条没有被用例逐个钉住 |
| `notifications.py` L76 `"feishu"` → `"XXfeishuXX"` | 飞书渠道 `status: "sent"` | `status: "skipped"` | **真缺口**：`send_to_hr` 只被用 wecom / email 跑过，飞书、钉钉分派没有任何用例 |
| `audit.py` L116 截断计数 `-` → `+` | `__truncated_keys__: 1` | `__truncated_keys__: 101` | **真缺口**：字典超过 50 个键的截断分支从未被用例走到 |
| `notifications.py` L96 日志文案加 `XX` | 返回值相同 | 返回值相同 | **噪声**：只影响日志文本 |
| `deps.py`（探索轮）L29 注解 `str | None` → `str & None` | 行为相同 | 行为相同 | **等价变异体**：`from __future__ import annotations` 下注解不求值 |

`deps.py` 探索轮的 12 条存活里值得补的两处（都只在非数据库用例范围内成立）：
无操作人时的 `401` 状态码改成 `402` 没有被断言；`audit_actor_name` /
`audit_request_id` / `audit_ip_address` 三个辅助函数的非空返回路径没有用例。

## 实测踩坑

mutmut 2.5.1：

- 没有并发：单进程串行，耗时 ≈ 变异体数 × 单次 pytest 时间。
- `tests_pass` 只把 pytest 退出码 1 当失败；收集错误（退出码 2，例如 import 期
  崩溃）会被记成存活，runner 必须带 `--continue-on-collection-errors`。
- 配置文件只在选项取值为假时才生效：`test_time_multiplier`（默认 2.0）写在任何
  配置文件里都被忽略；`test_time_base`（默认 0.0）在 `setup.cfg` 里会拿到字符串，
  出现被杀死的变异体时直接 `TypeError`。
- `paths_to_mutate` 与 `runner` 必须写成单行（ConfigParser 会把续行原样保留成换行符）。
- `paths_to_mutate` 里不存在的路径被静默丢弃。
- 改 runner 不会让缓存失效（见上）。
- 类型注解里的 `|` 会被变异成 `&`，在 `from __future__ import annotations` 下必然等价。
- 会被就地改写源文件，恢复后文件 mtime 变化（内容不变）。

配方资产（可反哺 lazypack-discipline）：

- `mutmut --version` 不是合法选项（退出码 2），配方 §5.2 的安装核验命令会把安装
  成功判成 `install-failed`；正确命令是 `mutmut version`。
- `nightly-mutation-runner.sh` 的 py 链路不会生成 `mutmut-results-export.json`，
  基线步骤被跳过；workflow 模板已经补了导出步骤，runner 脚本与 systemd / cron
  模板还停在旧口径。
- `nightly-mutation-runner.sh` 用「`.mutmut-cache` 是否比本轮新」判断缓存新鲜度；
  结果全部命中缓存时 mutmut 不重写缓存文件，代码没变化的夜里重跑会被误判成
  失败（实测退出码 2）。
- `test_time_multiplier` 写在配置文件里会被 mutmut 忽略（它只在选项取值为假时才读
  配置），而配方 runner 脚本调用的是不带参数的 `mutmut run`，所以 Suspicious 阈值
  固定为基线耗时的 2 倍；基线分数又把 Suspicious 计为未检出，CI 机器偶尔抖动就
  可能让棘轮检查误报回归（风险，尚未复现）。
- 同一处缺口会裂成多条存活记录（邮件成功路径 14 条、飞书 / 钉钉分派 8 条），
  issue 按变异体逐条列出会高估工作量；建单前按行 / 分支聚类会更准。
- `parse_mutmut_report.py` 有多类 mutmut 2.x 变异形态归不了类：字符串字面量变异
  （`'XX' + 值 + 'XX'`）、实参 / 赋值被换成 `None`、类型注解 `|` → `&` 等。本轮
  71 条存活里 41 条落到 `Unknown`（其中 33 条是字符串字面量）。
- 统一报告的 id 是重新排的序号，不带 mutmut 原生 id，补测 agent 要用
  `mutmut show <id>` / `mutmut apply <id>` 得先靠 diff 反查。
- `create-mutation-issues.mjs` 的标签（`mutation` + `nightly`）是写死的，没有参数
  或环境变量可以覆盖。
- 运营手册的快速上手与配置示例用的是 mutmut 3.x 语法（`source_paths`、
  `[tool.mutmut]`、`# pragma: no mutate block`），与配方固定的 2.x 不一致。
- 配方 §6.3.1 提到受限分支可手动配置 Stryker command runner，但
  `@stryker-mutator/command-runner` 已从 npm 下架（404）。

## 扩面

1. 把新模块加进 `setup.cfg` 的 `paths_to_mutate`，把它的守护用例加进
   `pytest-mutation.ini` 的 `testpaths`（越直接的越靠前）。
2. 删除 `.mutmut-cache` 重跑一轮，看耗时；单轮预算按夜跑可接受的上限定。
3. 核对 `mutmut results` 里的文件清单与预期一致（不存在的路径会被静默丢弃）。
4. 范围变了基线不可比：删除 `.mutation-baseline.json` 后重新 `init` 并提交。

## 升级配方脚本

`scripts/` 下的工具脚本不是托管配置，升级靠手动：从 lazypack-discipline 的
`skills/lazypack-setup/assets/mutation/scripts/` 重新复制，核对 4 个核心脚本的
`@version` 一致，再删 `.mutmut-cache` 重跑一轮。
