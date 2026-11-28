/**
 * scripts/mutation-baseline.mjs
 * @version 1.0.0
 *
 * 变异分数基线管理工具：从原始变异测试报告提取统计值（score/killed/survived/total），
 * 管理目标项目根目录下的 .mutation-baseline.json（格式契约见
 * docs/formats/mutation-baseline.md v1.0）：
 *   init   首次冻结基线；目标位置已有基线或变异范围为空（total=0）时拒绝（退出码 1）。
 *   check  比较本次分数与基线：不低于基线退出码 0；回归退出码 2；基线缺失/非法退出码 1。
 *   update 棘轮只涨不跌：分数提高才重写（四个统计值与 updated 全部换新）；
 *          持平 no-op 不触碰文件；下调拒绝（退出码 2）；基线不存在时等价于 init。
 * 零依赖（Node.js 标准库），解析为纯函数，CLI 入口在文件底部。
 *
 * 用法:
 *   node scripts/mutation-baseline.mjs <init|check|update> --input <report> \
 *     [--lang <ts|py>] [--output <path>] [--help]
 *
 * 报告形态（--lang 决定接受哪些形态，未提供时自动检测）:
 *   ts: Stryker JSON（变异体结果数组，或 { schemaVersion, files } schema 报告）
 *   py: mutmut 结果导出（{ killed: [...], survived: [...], timeout: [...], ... }，值为 id 数组）
 *   通用: 最小统计对象 { score, killed, survived, total }（各语言均可）
 *
 * 分数口径：报告里显式给出的分数原样记录（禁止取整、禁止截断）；报告只有变异体
 * 状态清单时按检出口径计算 score = round2((killed + timeout) / total * 100)
 * （Stryker 口径，Timeout 计入检出；与格式契约 §7 示例一致）。
 * check/update 的分数比较带 1e-9 浮点容差（契约 §4）。
 *
 * 退出码: 0 成功；1 用户错误（缺参、文件缺失、JSON 非法、版本未知、init 已有基线、空范围）；
 *         2 门槛失败（check 回归、update 拒绝下调）。
 */

import fs from 'node:fs';

/** 基线文件契约版本（docs/formats/mutation-baseline.md）。 */
const BASELINE_VERSION = '1.0';

/** 未指定 --output 时基线文件的默认落盘文件名（当前工作目录下）。 */
const DEFAULT_OUTPUT_NAME = '.mutation-baseline.json';

/** 分数比较的浮点容差（契约 §4 建议 1e-9）。 */
const SCORE_EPSILON = 1e-9;

/** 语言别名到解析器族的映射。 */
const LANG_ALIASES = {
  ts: 'ts',
  typescript: 'ts',
  javascript: 'ts',
  js: 'ts',
  py: 'py',
  python: 'py'
};

/** 需要取值的命令行旗标。 */
const VALUE_FLAGS = new Set(['--input', '--output', '--lang']);

/** 支持的子命令。 */
const SUBCOMMANDS = ['init', 'check', 'update'];

/** mutmut 结果导出里参与 total 计数的类别（契约 §3：其余状态也计入 total）。 */
const MUTMUT_CATEGORIES = ['killed', 'survived', 'timeout', 'suspicious', 'untested', 'skipped'];

/**
 * CLI 用法/输入错误：向 stderr 输出 message 并以退出码 1 结束。
 */
class CliError extends Error {}

/**
 * 把数值四舍五入到两位小数，规避浮点尾差（仅用于计算出的分数，显式分数不动）。
 * @param {number} value - 原始数值
 * @returns {number} 两位小数数值
 */
function round2(value) {
  return Math.round(value * 100) / 100;
}

/**
 * 从候选值里挑出第一个有限数值。
 * @param {...(number|undefined)} candidates - 按优先级排列的候选值
 * @returns {number|undefined} 首个有限数值，均无效时为 undefined
 */
function pickNumber(...candidates) {
  for (const value of candidates) {
    if (typeof value === 'number' && Number.isFinite(value)) {
      return value;
    }
  }
  return undefined;
}

/**
 * 把分数格式化成稳定字符串（最多 6 位小数，去掉尾随零），用于消息输出。
 * @param {number} value - 分数或差值
 * @returns {string} 形如 42.55 / -0.54 / 0 的字符串
 */
function formatScore(value) {
  return String(Number(value.toFixed(6)));
}

/**
 * 归一化语言参数；未提供时返回 undefined 表示自动检测。
 * @param {string|undefined} raw - --lang 的原始字符串
 * @returns {'ts'|'py'|undefined} 解析器族
 */
function normalizeLang(raw) {
  if (raw === undefined) {
    return undefined;
  }
  const lang = LANG_ALIASES[String(raw).toLowerCase()];
  if (!lang) {
    throw new CliError(
      `unsupported language: ${raw} (supported: ts, py; aliases: typescript, javascript, js, python)`
    );
  }
  return lang;
}

/**
 * 解析命令行参数；首个非旗标 token 视为子命令。
 * @param {string[]} argv - process.argv.slice(2)
 * @returns {{command: string|undefined, help: boolean, input: string|undefined,
 *   output: string|undefined, lang: string|undefined}}
 */
function parseCommandArgs(argv) {
  const args = { command: undefined, help: false, input: undefined, output: undefined, lang: undefined };
  let index = 0;
  if (argv.length > 0 && !argv[0].startsWith('-')) {
    args.command = argv[0];
    index = 1;
  }
  for (let i = index; i < argv.length; i++) {
    const token = argv[i];
    if (token === '--help' || token === '-h') {
      args.help = true;
      continue;
    }
    if (!VALUE_FLAGS.has(token)) {
      throw new CliError(`unknown option: ${token} (see --help)`);
    }
    if (i + 1 >= argv.length) {
      throw new CliError(`missing value for ${token}`);
    }
    const key = token.slice(2);
    if (args[key] !== undefined) {
      throw new CliError(`duplicate option: ${token}`);
    }
    args[key] = argv[++i];
  }
  return args;
}

/**
 * 读取并解析 JSON 文件，缺失与语法错误分别给出清晰提示。
 * @param {string} filePath - 报告或基线路径
 * @param {string} label - 报错用的文件名（mutation report/baseline）
 * @returns {unknown} 解析后的 JSON 值
 */
function readJsonFile(filePath, label) {
  let raw;
  try {
    raw = fs.readFileSync(filePath, 'utf8');
  } catch (err) {
    if (err && err.code === 'ENOENT') {
      throw new CliError(`${label} not found: ${filePath}`);
    }
    throw new CliError(`failed to read ${label} ${filePath}: ${err.message}`);
  }
  try {
    return JSON.parse(raw);
  } catch (err) {
    throw new CliError(`failed to parse ${label} as JSON: ${err.message} (${filePath})`);
  }
}

/**
 * 校验计数为不小于下限的整数。
 * @param {number} value - 待校验值
 * @param {string} name - 字段名（报错用）
 * @param {string} sourcePath - 报错用的来源路径
 * @param {number} minimum - 允许的最小值
 */
function validateCount(value, name, sourcePath, minimum = 0) {
  if (typeof value !== 'number' || !Number.isInteger(value) || value < minimum) {
    throw new CliError(`mutation report field "${name}" must be an integer >= ${minimum}, got ${JSON.stringify(value)} (${sourcePath})`);
  }
}

/**
 * 校验分数为 [0, 100] 内的有限数值。
 * @param {number} value - 待校验分数
 * @param {string} sourcePath - 报错用的来源路径
 */
function validateScore(value, sourcePath) {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0 || value > 100) {
    throw new CliError(`mutation report score must be a number in [0, 100], got ${JSON.stringify(value)} (${sourcePath})`);
  }
}

/**
 * 从报告对象里挑出工具显式给出的分数（metrics.mutationScore → mutationScore → score）。
 * @param {unknown} data - 已解析的报告对象
 * @returns {number|undefined} 显式分数，缺失时为 undefined
 */
function pickExplicitScore(data) {
  if (!data || typeof data !== 'object' || Array.isArray(data)) {
    return undefined;
  }
  const metrics = data.metrics && typeof data.metrics === 'object' ? data.metrics : {};
  return pickNumber(metrics.mutationScore, data.mutationScore, data.score);
}

/**
 * 汇总并校验统计值，决定最终分数：显式分数原样保留（禁止取整/截断），
 * 否则按检出口径计算 round2((killed + timeout) / total * 100)。
 * @param {{killed: number, survived: number, timeout: number, total: number}} raw - 原始计数
 * @param {unknown} data - 已解析的报告（用于挑显式分数）
 * @param {string} sourcePath - 报错用的报告路径
 * @returns {{score: number, killed: number, survived: number, total: number, scoreSource: string}}
 */
function finishStats(raw, data, sourcePath) {
  validateCount(raw.killed, 'killed', sourcePath);
  validateCount(raw.survived, 'survived', sourcePath);
  validateCount(raw.total, 'total', sourcePath);
  if (raw.killed + raw.survived > raw.total) {
    throw new CliError(`mutation report inconsistent: killed + survived (${raw.killed + raw.survived}) > total (${raw.total}) (${sourcePath})`);
  }
  if (raw.total < 1) {
    throw new CliError(`empty mutant range: report contains 0 mutants, refusing to freeze a baseline (${sourcePath})`);
  }
  const explicit = pickExplicitScore(data);
  if (explicit !== undefined) {
    validateScore(explicit, sourcePath);
    return { score: explicit, killed: raw.killed, survived: raw.survived, total: raw.total, scoreSource: 'reported' };
  }
  return {
    score: round2(((raw.killed + raw.timeout) / raw.total) * 100),
    killed: raw.killed,
    survived: raw.survived,
    total: raw.total,
    scoreSource: 'computed'
  };
}

/**
 * 识别 Stryker 变异体结果数组（每个条目是带 status 字符串的对象）。
 * @param {unknown} data - 已解析的报告
 * @returns {boolean}
 */
function looksLikeStrykerMutantList(data) {
  return Array.isArray(data) && data.every((m) => m !== null && typeof m === 'object' && typeof m.status === 'string');
}

/**
 * 识别 Stryker schema 报告（{ files: { "<path>": { mutants: [...] } } }，files 也可为数组）。
 * @param {unknown} data - 已解析的报告
 * @returns {boolean}
 */
function looksLikeStrykerFileReport(data) {
  if (!data || typeof data !== 'object' || Array.isArray(data)) {
    return false;
  }
  const files = data.files;
  if (!files || typeof files !== 'object') {
    return false;
  }
  const entries = Array.isArray(files) ? files : Object.values(files);
  return entries.every((f) => f !== null && typeof f === 'object' && Array.isArray(f.mutants));
}

/**
 * 识别 mutmut 结果导出（至少一个类别是数组，其余类别若出现也必须是数组）。
 * @param {unknown} data - 已解析的报告
 * @returns {boolean}
 */
function looksLikeMutmutExport(data) {
  if (!data || typeof data !== 'object' || Array.isArray(data)) {
    return false;
  }
  let sawArray = false;
  for (const key of MUTMUT_CATEGORIES) {
    if (data[key] === undefined) {
      continue;
    }
    if (!Array.isArray(data[key])) {
      return false;
    }
    sawArray = true;
  }
  return sawArray;
}

/**
 * 识别最小统计对象（score/killed/survived/total 四个键全部出现，类型由校验兜底）。
 * @param {unknown} data - 已解析的报告
 * @returns {boolean}
 */
function looksLikeStatsObject(data) {
  if (!data || typeof data !== 'object' || Array.isArray(data)) {
    return false;
  }
  return data.score !== undefined && data.killed !== undefined && data.survived !== undefined && data.total !== undefined;
}

/**
 * 按 Stryker 口径统计变异体状态：Timeout 计入检出，其余非 Killed/Survived/Timeout
 * 状态（NoCoverage、RuntimeError 等）计入 total 但不计入检出。
 * @param {object[]} mutants - 变异体条目
 * @returns {{killed: number, survived: number, timeout: number, total: number}}
 */
function countStatuses(mutants) {
  let killed = 0;
  let survived = 0;
  let timeout = 0;
  for (const mutant of mutants) {
    if (mutant.status === 'Killed') {
      killed++;
    } else if (mutant.status === 'Survived') {
      survived++;
    } else if (mutant.status === 'Timeout') {
      timeout++;
    }
  }
  return { killed, survived, timeout, total: mutants.length };
}

/**
 * 解析 Stryker 形态（结果数组或 schema 报告）；形态不符返回 undefined。
 * @param {unknown} data - 已解析的报告
 * @param {string} sourcePath - 报错用的报告路径
 * @returns {object|undefined} 统计值
 */
function extractStrykerStats(data, sourcePath) {
  if (looksLikeStrykerMutantList(data)) {
    return finishStats(countStatuses(data), data, sourcePath);
  }
  if (looksLikeStrykerFileReport(data)) {
    const files = data.files;
    const mutants = (Array.isArray(files) ? files : Object.values(files)).flatMap((f) => f.mutants);
    return finishStats(countStatuses(mutants), data, sourcePath);
  }
  return undefined;
}

/**
 * 解析 mutmut 结果导出（各类别数组求长度）；形态不符返回 undefined。
 * @param {unknown} data - 已解析的报告
 * @param {string} sourcePath - 报错用的报告路径
 * @returns {object|undefined} 统计值
 */
function extractMutmutStats(data, sourcePath) {
  if (!looksLikeMutmutExport(data)) {
    return undefined;
  }
  const raw = { killed: 0, survived: 0, timeout: 0, total: 0 };
  for (const key of MUTMUT_CATEGORIES) {
    if (Array.isArray(data[key])) {
      raw.total += data[key].length;
      if (key in raw) {
        raw[key] = data[key].length;
      }
    }
  }
  return finishStats(raw, data, sourcePath);
}

/**
 * 解析最小统计对象；形态不符返回 undefined。
 * @param {unknown} data - 已解析的报告
 * @param {string} sourcePath - 报错用的报告路径
 * @returns {object|undefined} 统计值
 */
function extractStatsObject(data, sourcePath) {
  if (!looksLikeStatsObject(data)) {
    return undefined;
  }
  return finishStats(
    { killed: data.killed, survived: data.survived, timeout: 0, total: data.total },
    data,
    sourcePath
  );
}

/**
 * 按语言解析报告统计值：--lang 决定接受哪些形态，未提供时按 ts → py → 通用顺序尝试。
 * @param {unknown} data - 已解析的报告
 * @param {'ts'|'py'|undefined} lang - 解析器族
 * @param {string} sourcePath - 报错用的报告路径
 * @returns {{score: number, killed: number, survived: number, total: number, scoreSource: string}}
 */
function parseMutationReport(data, lang, sourcePath) {
  const extractors = lang === 'ts'
    ? [extractStrykerStats, extractStatsObject]
    : lang === 'py'
      ? [extractMutmutStats, extractStatsObject]
      : [extractStrykerStats, extractMutmutStats, extractStatsObject];
  for (const extract of extractors) {
    const stats = extract(data, sourcePath);
    if (stats) {
      return stats;
    }
  }
  const scope = lang ? ` for lang ${lang}` : '';
  throw new CliError(
    `mutation report format not recognized${scope}: expected a Stryker JSON report (ts), a mutmut results export (py), or a stats object {score, killed, survived, total} (${sourcePath})`
  );
}

/**
 * 生成基线文件的 UTC 时间戳（YYYY-MM-DDTHH:MM:SSZ，契约 §2）。
 * @returns {string}
 */
function utcNowStamp() {
  return new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');
}

/**
 * 由统计值构造基线文件对象（契约 §6 schema 的字段与顺序）。
 * @param {{score: number, killed: number, survived: number, total: number}} stats - 统计值
 * @returns {{version: string, updated: string, baseline: object}}
 */
function buildBaseline(stats) {
  return {
    version: BASELINE_VERSION,
    updated: utcNowStamp(),
    baseline: { score: stats.score, killed: stats.killed, survived: stats.survived, total: stats.total }
  };
}

/**
 * 读取并校验基线文件；非法 JSON、版本未知、字段缺失/越界均按用户错误抛出（契约 §2/§5.2）。
 * @param {string} filePath - 基线文件路径
 * @returns {{version: string, updated: string, baseline: {score: number, killed: number, survived: number, total: number}}}
 */
function readBaselineFile(filePath) {
  const data = readJsonFile(filePath, 'baseline file');
  if (!data || typeof data !== 'object' || Array.isArray(data)) {
    throw new CliError(`baseline file must be a JSON object (${filePath})`);
  }
  if (data.version !== BASELINE_VERSION) {
    const shown = data.version === undefined ? 'missing' : JSON.stringify(data.version);
    throw new CliError(`unsupported baseline version: ${shown} (expected "${BASELINE_VERSION}"); delete the file and re-init (${filePath})`);
  }
  if (typeof data.updated !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(data.updated)) {
    throw new CliError(`baseline field "updated" must be an ISO-8601 UTC timestamp (YYYY-MM-DDTHH:MM:SSZ), got ${JSON.stringify(data.updated)} (${filePath})`);
  }
  const baseline = data.baseline;
  if (!baseline || typeof baseline !== 'object' || Array.isArray(baseline)) {
    throw new CliError(`baseline file must contain a "baseline" object with score/killed/survived/total (${filePath})`);
  }
  validateScore(baseline.score, filePath);
  validateCount(baseline.killed, 'killed', filePath);
  validateCount(baseline.survived, 'survived', filePath);
  validateCount(baseline.total, 'total', filePath, 1);
  if (baseline.killed + baseline.survived > baseline.total) {
    throw new CliError(`baseline inconsistent: killed + survived (${baseline.killed + baseline.survived}) > total (${baseline.total}) (${filePath})`);
  }
  return { version: data.version, updated: data.updated, baseline };
}

/**
 * 判断分数相对基线是否视为持平（|delta| ≤ 1e-9，契约 §4）。
 */
function isScoreUnchanged(current, baselineScore) {
  return Math.abs(current - baselineScore) <= SCORE_EPSILON;
}

/**
 * 写出基线文件：UTF-8、2 空格缩进、结尾一个换行符（契约 §1）。
 * @param {string} outputPath - 目标路径
 * @param {{version: string, updated: string, baseline: object}} baselineObj - 基线对象
 */
function writeBaselineFile(outputPath, baselineObj) {
  try {
    fs.writeFileSync(outputPath, `${JSON.stringify(baselineObj, null, 2)}\n`, 'utf8');
  } catch (err) {
    throw new CliError(`failed to write baseline file ${outputPath}: ${err.message}`);
  }
}

/**
 * init：首次冻结。已有基线拒绝（不静默覆盖），空范围在统计解析时已被拒绝。
 * @param {object} stats - 统计值
 * @param {string} outputPath - 基线写出路径
 * @returns {number} 退出码
 */
function runInit(stats, outputPath) {
  if (fs.existsSync(outputPath)) {
    throw new CliError(`baseline file already exists: ${outputPath} (init never overwrites; use check or update instead)`);
  }
  writeBaselineFile(outputPath, buildBaseline(stats));
  process.stdout.write(
    `mutation-baseline: init baseline=${formatScore(stats.score)} killed=${stats.killed} survived=${stats.survived} total=${stats.total} (${stats.scoreSource} score) file=${outputPath}\n`
  );
  return 0;
}

/**
 * check：门槛检查。回归时 stdout 给出比较结果、stderr 写明两分数与差值，退出码 2。
 * @param {object} stats - 统计值
 * @param {string} outputPath - 基线文件路径
 * @returns {number} 退出码
 */
function runCheck(stats, outputPath) {
  if (!fs.existsSync(outputPath)) {
    throw new CliError(`baseline file not found: ${outputPath} (run init first, e.g. node scripts/mutation-baseline.mjs init --input <report>)`);
  }
  const base = readBaselineFile(outputPath).baseline;
  if (isScoreUnchanged(stats.score, base.score)) {
    process.stdout.write(`mutation-baseline: check PASS current=${formatScore(stats.score)} baseline=${formatScore(base.score)} delta=0 (unchanged)\n`);
    return 0;
  }
  const delta = stats.score - base.score;
  if (delta > 0) {
    process.stdout.write(`mutation-baseline: check PASS current=${formatScore(stats.score)} baseline=${formatScore(base.score)} delta=+${formatScore(delta)} (improved)\n`);
    return 0;
  }
  process.stdout.write(`mutation-baseline: check REGRESSION current=${formatScore(stats.score)} baseline=${formatScore(base.score)} delta=${formatScore(delta)}\n`);
  process.stderr.write(`Error: mutation score regressed: current ${formatScore(stats.score)} < baseline ${formatScore(base.score)} (delta ${formatScore(delta)}, file ${outputPath})\n`);
  return 2;
}

/**
 * update：棘轮只涨不跌。提高才重写（统计值与 updated 全部换新）；持平 no-op 不触碰文件；
 * 下调拒绝（退出码 2）；基线不存在时等价于 init（VAL-BASELINE-009）。
 * @param {object} stats - 统计值
 * @param {string} outputPath - 基线文件路径
 * @returns {number} 退出码
 */
function runUpdate(stats, outputPath) {
  if (!fs.existsSync(outputPath)) {
    writeBaselineFile(outputPath, buildBaseline(stats));
    process.stdout.write(
      `mutation-baseline: update (no baseline existed, created) baseline=${formatScore(stats.score)} killed=${stats.killed} survived=${stats.survived} total=${stats.total} file=${outputPath}\n`
    );
    return 0;
  }
  const file = readBaselineFile(outputPath);
  const base = file.baseline;
  if (isScoreUnchanged(stats.score, base.score)) {
    process.stdout.write(`mutation-baseline: update NO-OP current=${formatScore(stats.score)} baseline=${formatScore(base.score)} (unchanged, file untouched)\n`);
    return 0;
  }
  const delta = stats.score - base.score;
  if (delta > 0) {
    writeBaselineFile(outputPath, buildBaseline(stats));
    process.stdout.write(`mutation-baseline: update RAISED baseline ${formatScore(base.score)} -> ${formatScore(stats.score)} (delta +${formatScore(delta)}) file=${outputPath}\n`);
    return 0;
  }
  process.stdout.write(`mutation-baseline: update REFUSED current=${formatScore(stats.score)} baseline=${formatScore(base.score)} delta=${formatScore(delta)}\n`);
  process.stderr.write(`Error: refusing to lower baseline: current ${formatScore(stats.score)} < baseline ${formatScore(base.score)} (delta ${formatScore(delta)}); the ratchet never goes down - re-init manually if the tool or mutate scope changed (file ${outputPath})\n`);
  return 2;
}

/**
 * 打印单行用法（缺子命令或缺 --input 时输出到 stderr）。
 * @param {NodeJS.WriteStream} stream - 输出流
 */
function printUsage(stream) {
  stream.write('Usage: node scripts/mutation-baseline.mjs <init|check|update> --input <report> [--lang <ts|py>] [--output <path>]\n');
  stream.write('Run with --help for details.\n');
}

/**
 * 打印用法说明（--help，VAL-BASELINE-010）。
 */
function printHelp() {
  const lines = [
    'Usage: node scripts/mutation-baseline.mjs <init|check|update> --input <report> [options]',
    '',
    'Freeze the mutation score into .mutation-baseline.json and enforce a ratchet:',
    'the score may only rise. Format contract: docs/formats/mutation-baseline.md (v1.0).',
    '',
    'Subcommands:',
    '  init     Read the report and create .mutation-baseline.json;',
    '           refuses if the file already exists or the mutant range is empty',
    '  check    Compare the current score against the baseline;',
    '           exits non-zero (2) when the score regressed',
    '  update   Raise the baseline when the score improved; equal score is a no-op;',
    '           refuses to lower the score; creates the baseline if missing',
    '',
    'Options:',
    '  --input <path>    Path to the raw tool report (required)',
    '  --lang <lang>     Parser family: ts or py (aliases: typescript, javascript, js, python);',
    '                    default: auto-detect from the report shape',
    '  --output <path>   Baseline file path (default: .mutation-baseline.json in the current directory)',
    '  -h, --help        Show this help and exit',
    '',
    'Report formats:',
    '  ts: Stryker JSON (mutant result array, or { schemaVersion, files } schema report)',
    '  py: mutmut results export ({ killed: [...], survived: [...], timeout: [...], ... })',
    '  both: stats object { score, killed, survived, total }',
    '',
    'Score semantics:',
    '  An explicit score in the report is recorded verbatim (never rounded or truncated).',
    '  Without one, score = round2((killed + timeout) / total * 100) - Timeout counts as',
    '  detected (Stryker semantics). Score comparison uses a 1e-9 float tolerance.',
    '',
    'Exit codes:',
    '  0  success: init written, check passed (equal passes), update raised or no-op',
    '  1  user error: bad arguments, missing files, invalid JSON, unknown version,',
    '     init on an existing baseline, empty mutant range',
    '  2  gate failure: check regression, update refusing a lower score',
    '',
    'Examples:',
    '  node scripts/mutation-baseline.mjs init --input reports/mutation/mutation.json --lang ts',
    '  node scripts/mutation-baseline.mjs check --input reports/mutation/mutation.json',
    '  node scripts/mutation-baseline.mjs update --input mutmut-results.json --lang py'
  ];
  process.stdout.write(`${lines.join('\n')}\n`);
}

/**
 * CLI 入口：解析参数、读取报告、执行子命令，返回进程退出码。
 * @param {string[]} argv - process.argv.slice(2)
 * @returns {number} 退出码：0 成功；2 门槛失败（用户错误以 CliError 抛出，统一按 1 处理）
 */
function main(argv) {
  const args = parseCommandArgs(argv);
  if (args.help) {
    printHelp();
    return 0;
  }
  if (args.command === undefined) {
    process.stderr.write('Error: missing subcommand (expected init|check|update)\n');
    printUsage(process.stderr);
    return 1;
  }
  if (!SUBCOMMANDS.includes(args.command)) {
    throw new CliError(`unknown subcommand: ${args.command} (expected init|check|update; see --help)`);
  }
  if (!args.input) {
    process.stderr.write(`Error: --input <report> is required for ${args.command}\n`);
    printUsage(process.stderr);
    return 1;
  }
  const lang = normalizeLang(args.lang);
  const reportData = readJsonFile(args.input, 'mutation report');
  const stats = parseMutationReport(reportData, lang, args.input);
  const outputPath = args.output || DEFAULT_OUTPUT_NAME;
  if (args.command === 'init') {
    return runInit(stats, outputPath);
  }
  if (args.command === 'check') {
    return runCheck(stats, outputPath);
  }
  return runUpdate(stats, outputPath);
}

try {
  process.exit(main(process.argv.slice(2)));
} catch (err) {
  const message = err instanceof CliError ? err.message : (err && err.stack) || String(err);
  process.stderr.write(`Error: ${message}\n`);
  process.exit(1);
}
