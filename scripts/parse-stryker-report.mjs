/**
 * scripts/parse-stryker-report.mjs
 * @version 1.0.0
 *
 * Stryker JSON 报告解析器（夜跑闭环 M2）：读取 StrykerJS 的 JSON 报告
 * （默认产物 reports/mutation/mutation.json，接受 v6/v7 形态，见 --help），
 * 提取 status === 'Survived' 的变异体，转换为统一变异体报告格式
 * （docs/formats/unified-mutation-report.md，契约 v1.1）：
 *   { tool: 'stryker', timestamp, mutants: [...], score }
 * mutant 字段 id/file/line/column/mutationType/original/mutated/status 按契约
 * §2/§3 归一化：id 前缀 stryker-（原生 id 转字符串）；Stryker 报告坐标已为
 * 1-based（schema v1.0 落盘前已把工具内部 0-based 换算 +1），直接透传；
 * original 从报告内 source 按 1-based 坐标切片（Stryker 不单独给出原文，
 * end 为开区间端点）；mutatorName 不在 §4 枚举时归为 Unknown；路径仅
 * 归一分隔符与 ./ 前缀，大小写逐字保留；mutants 按 file/line/column 升序。
 * 分数：报告显式分数（metrics.mutationScore → mutationScore → score）原样
 * 记录；否则按检出口径 round2((killed+timeout)/total*100)（Timeout 计入
 * 检出，与 mutation-baseline.mjs 同口径）；变异范围为空时记 100。
 * 零依赖（Node.js 标准库），解析为纯函数，CLI 入口在文件底部。未接 hook/CI。
 *
 * 用法:
 *   node scripts/parse-stryker-report.mjs --input <path> [--output <path>] [--help]
 *
 * 退出码: 0 成功（含空存活清单）；1 用户错误（缺参、文件缺失、JSON 非法、
 *         schema 不识别、未知变异状态、坐标/替换文本不一致）。
 */

import fs from 'node:fs';

/** Stryker 报告里允许出现的状态（契约 §5.1 映射表，透传）。 */
const STRYKER_STATUSES = new Set([
  'Pending',
  'Killed',
  'Survived',
  'NoCoverage',
  'Timeout',
  'RuntimeError',
  'CompileError',
  'Ignored'
]);

/** StrykerJS 的 19 个 mutator 名称（契约 §4 枚举的 Stryker 侧子集）。 */
const STRYKER_MUTATOR_NAMES = new Set([
  'ArithmeticOperator',
  'ArrayDeclaration',
  'ArrowFunction',
  'Block',
  'BooleanLiteral',
  'ConditionalExpression',
  'EqualityOperator',
  'LogicalOperator',
  'MethodExpression',
  'MethodName',
  'NegateCondition',
  'NumberLiteral',
  'ObjectLiteral',
  'OptionalChaining',
  'Regex',
  'StringLiteral',
  'SwitchStatement',
  'UnaryOperator',
  'UpdateOperator'
]);

/** 需要取值的命令行旗标。 */
const VALUE_FLAGS = new Set(['--input', '--output']);

/**
 * CLI 用法/输入错误：只向 stderr 输出 message 并以退出码 1 结束。
 */
class CliError extends Error {}

/**
 * 把数值四舍五入到两位小数，规避浮点尾差（仅用于计算出的分数）。
 * @param {number} value - 原始数值
 * @returns {number} 两位小数数值
 */
function round2(value) {
  return Math.round(value * 100) / 100;
}

/**
 * 解析命令行参数。
 * @param {string[]} argv - process.argv.slice(2)
 * @returns {{help: boolean, input: string|undefined, output: string|undefined}}
 */
function parseArgs(argv) {
  const args = { help: false };
  for (let i = 0; i < argv.length; i++) {
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
 * @param {string} filePath - Stryker 报告路径
 * @param {string} label - 报错用的文件名
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
 * 当前时刻的 ISO-8601 UTC 时间戳（秒精度，契约 §1）。
 * @returns {string} YYYY-MM-DDTHH:MM:SSZ
 */
function isoTimestampUtc() {
  return new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');
}

/**
 * 校验值为正整数（Stryker 报告坐标 1-based，最小值为 1）。
 * @param {unknown} value - 待校验值
 * @returns {boolean} 是否正整数
 */
function isPositiveInt(value) {
  return typeof value === 'number' && Number.isInteger(value) && value >= 1;
}

/**
 * 归一化文件键为契约 §3.2 的 POSIX 相对路径：反斜杠转正斜杠、去掉 ./ 前缀，
 * 大小写与其余内容逐字保留。
 * @param {string} rawPath - Stryker files 对象的键
 * @param {string} sourcePath - 报错用的报告路径
 * @returns {string} 归一化后的路径
 */
function normalizeFileKey(rawPath, sourcePath) {
  if (typeof rawPath !== 'string' || rawPath.trim() === '') {
    throw new CliError(`stryker report file key must be a non-empty string, got ${JSON.stringify(rawPath ?? null)} (${sourcePath})`);
  }
  const posix = rawPath.replace(/\\/g, '/');
  const withoutDot = posix.startsWith('./') ? posix.slice(2) : posix;
  if (withoutDot === '') {
    throw new CliError(`stryker report file key normalizes to an empty path: ${JSON.stringify(rawPath)} (${sourcePath})`);
  }
  return withoutDot;
}

/**
 * 从报告内 source 按 Stryker 位置切片出 original。坐标为 1-based（schema
 * v1.0），切片前换算为 0-based 下标；end 为开区间端点，跨行片段以 \n 连接
 * （契约 §3.4）。
 * @param {string|undefined} source - 文件源码
 * @param {string} file - 报错用的文件路径
 * @param {string} mutantId - 报错用的变异体标识
 * @param {{start: {line: number, column: number}, end: {line: number, column: number}}|undefined} location - Stryker 原生位置（1-based）
 * @param {string} sourcePath - 报错用的报告路径
 * @returns {string} 原始源码片段（非空）
 */
function extractOriginal(source, file, mutantId, location, sourcePath) {
  if (typeof source !== 'string') {
    throw new CliError(`stryker report file "${file}" has surviving mutant ${mutantId} but no source text to extract the original fragment from (${sourcePath})`);
  }
  const start = location && location.start;
  const end = location && location.end;
  if (!start || !isPositiveInt(start.line) || !isPositiveInt(start.column)) {
    throw new CliError(`surviving mutant ${mutantId} in "${file}" has invalid location.start (expected 1-based line and column, got ${JSON.stringify(start ?? null)}) (${sourcePath})`);
  }
  if (!end || !isPositiveInt(end.line) || !isPositiveInt(end.column)) {
    throw new CliError(`surviving mutant ${mutantId} in "${file}" has invalid location.end (expected 1-based line and column, got ${JSON.stringify(end ?? null)}) (${sourcePath})`);
  }
  const lines = source.split('\n');
  if (end.line < start.line || start.line > lines.length || end.line > lines.length) {
    throw new CliError(`surviving mutant ${mutantId} in "${file}" has a location out of range: start ${start.line}:${start.column}, end ${end.line}:${end.column}, source has ${lines.length} lines (${sourcePath})`);
  }
  if (start.line === end.line && end.column < start.column) {
    throw new CliError(`surviving mutant ${mutantId} in "${file}" has location.end before location.start (${sourcePath})`);
  }
  let original;
  if (start.line === end.line) {
    original = lines[start.line - 1].slice(start.column - 1, end.column - 1);
  } else {
    const parts = [lines[start.line - 1].slice(start.column - 1)];
    for (let l = start.line; l < end.line - 1; l++) {
      parts.push(lines[l]);
    }
    parts.push(lines[end.line - 1].slice(0, end.column - 1));
    original = parts.join('\n');
  }
  if (original === '') {
    throw new CliError(`surviving mutant ${mutantId} in "${file}" has an empty original fragment at ${start.line}:${start.column} (${sourcePath})`);
  }
  return original;
}

/**
 * 把单个存活变异体归一化为契约 §2 的 mutant 对象。
 * @param {string} file - 归一化后的文件路径
 * @param {string} rawFile - 报错用的原始文件键
 * @param {object} mutant - Stryker 原生变异体
 * @param {string|undefined} source - 文件源码
 * @param {string} sourcePath - 报错用的报告路径
 * @returns {object} 统一格式 mutant（恰八字段）
 */
function toUnifiedMutant(file, rawFile, mutant, source, sourcePath) {
  const nativeId = mutant.id;
  if ((typeof nativeId !== 'number' || !Number.isFinite(nativeId)) && typeof nativeId !== 'string') {
    throw new CliError(`surviving mutant in "${rawFile}" has missing or non-scalar id (${JSON.stringify(nativeId ?? null)}) (${sourcePath})`);
  }
  const idText = String(nativeId);
  if (/\s/.test(idText)) {
    throw new CliError(`surviving mutant id in "${rawFile}" must not contain whitespace: ${JSON.stringify(idText)} (${sourcePath})`);
  }
  const mutatorName = typeof mutant.mutatorName === 'string' ? mutant.mutatorName : '';
  const start = mutant.location && mutant.location.start;
  const original = extractOriginal(source, rawFile, `stryker-${idText}`, mutant.location, sourcePath);
  if (typeof mutant.replacement !== 'string' || mutant.replacement === '') {
    throw new CliError(`surviving mutant stryker-${idText} in "${rawFile}" has missing or empty replacement (${sourcePath})`);
  }
  if (mutant.replacement === original) {
    throw new CliError(`surviving mutant stryker-${idText} in "${rawFile}" has a replacement identical to the original fragment ${JSON.stringify(original)} (${sourcePath})`);
  }
  return {
    id: `stryker-${idText}`,
    file,
    line: start.line,
    column: start.column,
    mutationType: STRYKER_MUTATOR_NAMES.has(mutatorName) ? mutatorName : 'Unknown',
    original,
    mutated: mutant.replacement,
    status: 'Survived'
  };
}

/**
 * 解析 Stryker schema 报告：先全量校验状态并计数，再提取存活变异体。
 * @param {unknown} data - 已解析的 Stryker 报告
 * @param {string} sourcePath - 报错用的报告路径
 * @returns {{mutants: object[], stats: {total: number, killed: number, timeout: number, survived: number}}}
 */
function parseStrykerReport(data, sourcePath) {
  if (!data || typeof data !== 'object' || Array.isArray(data)
    || !data.files || typeof data.files !== 'object' || Array.isArray(data.files)) {
    throw new CliError(`stryker report schema not recognized: expected { schemaVersion, files: { "<path>": { source, mutants } } } object (${sourcePath})`);
  }
  const stats = { total: 0, killed: 0, timeout: 0, survived: 0 };
  /** @type {object[]} */
  const survivors = [];
  for (const [rawFile, fileEntry] of Object.entries(data.files)) {
    if (!fileEntry || typeof fileEntry !== 'object') {
      throw new CliError(`stryker report file entry "${rawFile}" is not an object (${sourcePath})`);
    }
    const file = normalizeFileKey(rawFile, sourcePath);
    const mutants = Array.isArray(fileEntry.mutants) ? fileEntry.mutants : [];
    for (const mutant of mutants) {
      if (!mutant || typeof mutant !== 'object') {
        throw new CliError(`stryker report mutant in "${rawFile}" is not an object (${sourcePath})`);
      }
      const status = mutant.status;
      if (typeof status !== 'string' || !STRYKER_STATUSES.has(status)) {
        throw new CliError(`unknown mutant status ${JSON.stringify(status ?? null)} for "${rawFile}" (expected one of ${[...STRYKER_STATUSES].join(', ')}) (${sourcePath})`);
      }
      stats.total += 1;
      if (status === 'Killed') {
        stats.killed += 1;
      } else if (status === 'Timeout') {
        stats.timeout += 1;
      } else if (status === 'Survived') {
        stats.survived += 1;
        survivors.push(toUnifiedMutant(file, rawFile, mutant, fileEntry.source, sourcePath));
      }
    }
  }
  survivors.sort((a, b) => (
    a.file < b.file ? -1 : a.file > b.file ? 1 : a.line - b.line || a.column - b.column
  ));
  return { mutants: survivors, stats };
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
  const metrics = data.metrics && typeof data.metrics === 'object' && !Array.isArray(data.metrics)
    ? data.metrics
    : undefined;
  const candidates = [metrics && metrics.mutationScore, data.mutationScore, data.score];
  for (const value of candidates) {
    if (value !== undefined) {
      return value;
    }
  }
  return undefined;
}

/**
 * 决定输出分数：显式分数原样记录；否则按检出口径计算（Timeout 计入检出，
 * 与 mutation-baseline.mjs 同口径）；变异范围为空时记 100。
 * @param {unknown} data - 已解析的报告对象
 * @param {{total: number, killed: number, timeout: number}} stats - 状态计数
 * @param {string} sourcePath - 报错用的报告路径
 * @returns {number} 0–100 内的分数
 */
function resolveScore(data, stats, sourcePath) {
  const explicit = pickExplicitScore(data);
  if (explicit !== undefined) {
    if (typeof explicit !== 'number' || !Number.isFinite(explicit) || explicit < 0 || explicit > 100) {
      throw new CliError(`stryker report explicit score must be a number in [0, 100], got ${JSON.stringify(explicit)} (${sourcePath})`);
    }
    return explicit;
  }
  if (stats.total === 0) {
    return 100;
  }
  return round2(((stats.killed + stats.timeout) / stats.total) * 100);
}

/**
 * 组装统一报告（顶层恰好 tool/timestamp/mutants/score，契约 v1.1）。
 * @param {object[]} mutants - 已排序的存活变异体
 * @param {number} score - 变异分数
 * @returns {{tool: string, timestamp: string, mutants: object[], score: number}}
 */
function buildUnifiedReport(mutants, score) {
  return {
    tool: 'stryker',
    timestamp: isoTimestampUtc(),
    mutants,
    score
  };
}

/**
 * 渲染人类可读摘要行（仅 --output 落盘时打到 stdout）。
 * @param {object} report - 统一报告
 * @param {string} outputPath - 写出路径
 * @returns {string} 单行摘要
 */
function renderSummaryLine(report, outputPath) {
  return `parse-stryker-report: survived=${report.mutants.length} score=${report.score} wrote ${outputPath}`;
}

/**
 * 打印用法说明（--help）。
 */
function printHelp() {
  const lines = [
    'Usage: node scripts/parse-stryker-report.mjs --input <path> [options]',
    '',
    'Parse a Stryker JSON mutation report (reports/mutation/mutation.json), keep the',
    'mutants with status "Survived", and convert them to the unified mutation report',
    'format (docs/formats/unified-mutation-report.md, contract v1.1).',
    '',
    'Options:',
    '  --input <path>     Path to the Stryker JSON report (required)',
    '  --output <path>    Write the unified report JSON to this file (default: stdout)',
    '  -h, --help         Show this help and exit',
    '',
    'Accepted input shapes (StrykerJS v6 and v7 JSON reports):',
    '  { "schemaVersion": "...", "files": { "<path>": { "source": "...", "mutants": [...] } } }',
    '  v7 reports may add "testFiles" and per-mutant fields; extra sections are ignored.',
    '  Stryker report coordinates are already 1-based (the schema converts Stryker\'s',
    '  internal 0-based positions before writing the file) and are passed through',
    '  unchanged, pointing at the first character of "original", which is sliced from',
    '  the report source.',
    '',
    'Output:',
    '  Unified report JSON (UTF-8, LF, 2-space indent):',
    '  { tool: "stryker", timestamp: ISO-8601 UTC, mutants: [...], score: <0-100> }',
    '  mutant fields: id ("stryker-<native id>"), file, line, column, mutationType,',
    '  original, mutated, status ("Survived"). Sorted by file, then line, then column.',
    '  With --output the JSON goes to the file and stdout carries a summary line.',
    '',
    'Score semantics:',
    '  An explicit report score (metrics.mutationScore, or top-level mutationScore/score)',
    '  is preserved verbatim; otherwise score = round2((killed + timeout) / total * 100)',
    '  (Timeout counts as detected). With zero mutants, score = 100.',
    '',
    'Exit codes:',
    '  0  success (including an empty survivors list)',
    '  1  user error: bad arguments, missing file, invalid JSON, unrecognized schema,',
    '     unknown mutant status, inconsistent location/replacement'
  ];
  process.stdout.write(`${lines.join('\n')}\n`);
}

/**
 * 打印单行用法（缺 --input 时输出到 stderr）。
 * @param {NodeJS.WriteStream} stream - 输出流
 */
function printUsage(stream) {
  stream.write('Usage: node scripts/parse-stryker-report.mjs --input <path> [--output <path>]\n');
  stream.write('Run with --help for details.\n');
}

/**
 * CLI 入口：解析参数、读取报告、转换并输出，返回进程退出码。
 * @param {string[]} argv - process.argv.slice(2)
 * @returns {number} 退出码：0 成功；1 用户错误
 */
function main(argv) {
  const args = parseArgs(argv);
  if (args.help) {
    printHelp();
    return 0;
  }
  if (!args.input) {
    process.stderr.write('Error: --input <stryker-report.json> is required\n');
    printUsage(process.stderr);
    return 1;
  }
  const data = readJsonFile(args.input, 'stryker report');
  const { mutants, stats } = parseStrykerReport(data, args.input);
  const score = resolveScore(data, stats, args.input);
  const report = buildUnifiedReport(mutants, score);
  const text = `${JSON.stringify(report, null, 2)}\n`;
  if (args.output) {
    try {
      fs.writeFileSync(args.output, text);
    } catch (err) {
      throw new CliError(`failed to write output file ${args.output}: ${err.message}`);
    }
    process.stdout.write(`${renderSummaryLine(report, args.output)}\n`);
  } else {
    process.stdout.write(text);
  }
  return 0;
}

try {
  process.exit(main(process.argv.slice(2)));
} catch (err) {
  const message = err instanceof CliError ? err.message : (err && err.stack) || String(err);
  process.stderr.write(`Error: ${message}\n`);
  process.exit(1);
}
