/**
 * scripts/create-mutation-issues.mjs
 * @version 1.0.0
 *
 * 补测 issue 创建脚本（夜跑闭环 M2）：读取统一变异体报告
 * （docs/formats/unified-mutation-report.md，契约 v1.1），按消费者约定
 * 过滤 status === 'Survived'，应用 .equivalent-mutants.json 豁免
 * （docs/formats/equivalent-mutants.md，file+line+mutationType 三元组匹配），
 * 按 file 字段精确分组，为每组产出双轨输出（docs/formats/mutation-issue-template.md，
 * 契约 v1.0）：
 *   - GitHub issue（人读，经 gh CLI 创建，标题 [Mutation] {file} - N survivors，
 *     标签 mutation + nightly，body 三小节固定）；
 *   - 机读队列文件 .mutation-queue/{file}.json（agent 解析；实跑创建组带
 *     新编号、去重跳过组带既有 open issue 编号，dry-run 省略 issueNumber）。
 *
 * 模式：
 *   默认（无模式旗标）实跑模式：先经 gh label list/create 确保标签存在，
 *                     再用 gh issue list 做客户端前缀去重
 *                     （[Mutation] {file} -  + mutation 标签 + open 状态），
 *                     已有 open issue 的组跳过并计数，其余经
 *                     gh issue create --title --body-file --label 创建。
 *                     每组创建/跳过完成后队列文件立即原子写盘（临时文件 +
 *                     rename 覆盖），gh 中途失败时已完成组的条目保留；
 *                     创建 gh 调用前先删除该组既有队列文件，失败组不留
 *                     上一轮的陈旧条目（fix-stale-queue-cleanup）。
 *   --dry-run         预览模式：写队列文件与 body 预览
 *                     （.mutation-queue/{file}.body.md），不调用 gh。
 *   --create-issues   兼容 no-op：实跑已是默认行为，传入不改变模式
 *                     （与 --dry-run 同用时按预览处理）。
 *
 * 可选：--exemptions <path> 指定豁免文件（缺省不过滤；文件缺失/畸形/schema
 * 非法退出码 1）；--output <path> 写 manifest（issue 列表 + 元数据 + 四计数
 * 摘要）；--assignee <login> 把本轮创建的 issue 指派给同一用户（仅实跑）。
 * 失配（陈旧）豁免条目不报错，在摘要与 manifest 的 staleExemptionIds 留痕。
 *
 * 测试钩子：环境变量 MUTATION_ISSUES_GH 可用 "|"-分隔的 argv 前缀替换 gh
 * （如 "node|C:/tools/fake-gh.mjs"），供离线仿真 gh CLI。
 *
 * 零依赖（Node.js 标准库），解析/渲染为纯函数，CLI 入口在文件底部。
 * 未接 hook/CI。
 *
 * 用法:
 *   node scripts/create-mutation-issues.mjs --input <path> [options]
 *
 * 退出码: 0 成功（含空清单与全部跳过）；1 用户错误（缺参、文件缺失、
 *         JSON 非法、统一报告/豁免文件 schema 非法、旗标冲突）；
 *         2 工具失败（gh CLI 调用失败或输出不可解析）。
 */

import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

/** 统一报告允许的顶层字段（契约 §1，score 为 1.1 起可选）。 */
const REPORT_TOP_KEYS = new Set(['tool', 'timestamp', 'mutants', 'score']);

/** mutant 对象的八字段（契约 §2，全部必填）。 */
const MUTANT_KEYS = ['id', 'file', 'line', 'column', 'mutationType', 'original', 'mutated', 'status'];

/** mutationType 闭合枚举（契约 §4，25 值）。 */
const MUTATION_TYPES = new Set([
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
  'UpdateOperator',
  'BreakContinue',
  'ComparisonOperator',
  'DecoratorRemoval',
  'KeywordArgument',
  'KeywordLiteral',
  'Unknown'
]);

/** status 闭合枚举（契约 §5，10 值）。 */
const STATUSES = new Set([
  'Survived',
  'Killed',
  'Timeout',
  'Suspicious',
  'NoCoverage',
  'CompileError',
  'RuntimeError',
  'Ignored',
  'Skipped',
  'Pending'
]);

/** 允许的报告来源工具（契约 §1）。 */
const TOOLS = new Set(['stryker', 'mutmut']);

/** 豁免条目的八字段（equivalent-mutants.md §3，全部必填）。 */
const EXEMPTION_KEYS = ['id', 'file', 'line', 'mutationType', 'reason', 'exemptedBy', 'exemptedAt', 'reviewRequired'];

/** 需要取值的命令行旗标。 */
const VALUE_FLAGS = new Set(['--input', '--exemptions', '--output', '--assignee']);

/** ISO-8601 UTC 全时刻（契约 §1 / equivalent-mutants.md §3.7）。 */
const ISO_UTC_PATTERN = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/;

/** 队列文件契约版本（mutation-issue-template.md §4.3）。 */
const QUEUE_VERSION = '1.0';

/** manifest 契约版本（本施工票定义）。 */
const MANIFEST_VERSION = '1.0';

/** 队列目录（模板契约 §4.1，相对运行目录）。 */
const QUEUE_DIR = '.mutation-queue';

/** issue 标签（模板契约 §5，建议色与描述）。 */
const ISSUE_LABELS = [
  { name: 'mutation', color: 'B60205', description: '夜跑变异测试：存活变异体补测' },
  { name: 'nightly', color: '1D76DB', description: '由夜跑自动补强闭环创建' }
];

/**
 * 补测指引固定文案（模板契约 §3.4，逐字使用，不得改写）。
 */
const GUIDE_TEXT = [
  '每个变异体都是「源代码被机械改动后，全部测试仍然通过」的位置：现有测试没有约束这段行为。补测判定标准：**新增测试在原代码上通过、在变异后代码上失败**，该变异体即被杀死（Killed）。',
  '',
  '1. 逐个处理上方清单：按 line/column 打开源码位置，对比 original 与 mutated，找出能区分两者的输入（边界值、空值、组合条件等）。',
  '2. 为该输入新增测试用例，断言可观察行为；不要为让测试变红而断言实现细节。',
  '3. 测试通过后重跑变异测试，确认对应变异体状态变为 Killed。',
  '4. 若分析后确认该变异体是等价变异体（任何输入下行为不变），**不要**编写无意义测试：把条目记入项目根的 `.equivalent-mutants.json`（reason 必填且须可检验），下一轮夜跑起不再为它生成 issue 内容。',
  '5. 补测合入使变异分数上涨后，更新项目根的 `.mutation-baseline.json` 冻结门槛（棘轮式只涨不跌）。'
].join('\n');

/**
 * CLI 用法/输入错误：退出码 1。
 */
class CliError extends Error {}

/**
 * gh CLI 调用失败：退出码 2（工具失败）。
 */
class GhError extends Error {}

/**
 * 当前时刻的 ISO-8601 UTC 时间戳（秒精度）。
 * @returns {string} YYYY-MM-DDTHH:MM:SSZ
 */
function isoTimestampUtc() {
  return new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');
}

/**
 * 解析命令行参数。
 * @param {string[]} argv - process.argv.slice(2)
 * @returns {{help: boolean, dryRun: boolean, createIssues: boolean,
 *            input?: string, exemptions?: string, output?: string, assignee?: string}}
 */
function parseArgs(argv) {
  const args = { help: false, dryRun: false, createIssues: false };
  for (let i = 0; i < argv.length; i++) {
    const token = argv[i];
    if (token === '--help' || token === '-h') {
      args.help = true;
      continue;
    }
    if (token === '--dry-run') {
      args.dryRun = true;
      continue;
    }
    if (token === '--create-issues') {
      // 兼容旧接口：实跑已是默认行为，该旗标保留为 no-op
      args.createIssues = true;
      continue;
    }
    if (!VALUE_FLAGS.has(token)) {
      throw new CliError(`unknown option: ${token} (see --help)`);
    }
    if (i + 1 >= argv.length) {
      throw new CliError(`missing value for ${token}`);
    }
    const key = token.slice(2);
    const prop = key === 'input' || key === 'exemptions' || key === 'output' ? key : 'assignee';
    if (args[prop] !== undefined) {
      throw new CliError(`duplicate option: ${token}`);
    }
    args[prop] = argv[++i];
  }
  if (args.assignee !== undefined && args.dryRun) {
    throw new CliError('--assignee requires create mode (nothing is assigned with --dry-run)');
  }
  return args;
}

/**
 * 读取并解析 JSON 文件，缺失与语法错误分别给出清晰提示。
 * @param {string} filePath - JSON 路径
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
 * 是否普通对象（非数组、非 null）。
 * @param {unknown} value - 待测值
 * @returns {boolean} 是否普通对象
 */
function isPlainObject(value) {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/**
 * 是否正整数（1-based 坐标）。
 * @param {unknown} value - 待测值
 * @returns {boolean} 是否 ≥1 整数
 */
function isPositiveInt(value) {
  return typeof value === 'number' && Number.isInteger(value) && value >= 1;
}

/**
 * 是否非空字符串。
 * @param {unknown} value - 待测值
 * @returns {boolean} 是否非空字符串
 */
function isNonEmptyString(value) {
  return typeof value === 'string' && value.length > 0;
}

/**
 * 校验项目根相对 POSIX 路径（契约 §3.2）。
 * @param {unknown} value - 待测值
 * @returns {boolean} 是否合法路径
 */
function isValidPosixPath(value) {
  return isNonEmptyString(value) && !value.includes('\\') && !value.startsWith('./') && !value.startsWith('/');
}

/**
 * 校验字段集合：无未知字段、必填字段在场。
 * @param {object} obj - 待测对象
 * @param {string[]} allowed - 允许的字段
 * @param {string} label - 报错用的对象路径
 */
function checkFieldSet(obj, allowed, label) {
  const keys = Object.keys(obj);
  for (const key of keys) {
    if (!allowed.includes(key)) {
      throw new CliError(`${label}: unknown field "${key}" (allowed: ${allowed.join(', ')})`);
    }
  }
  for (const key of allowed) {
    if (!(key in obj)) {
      throw new CliError(`${label}: missing required field "${key}"`);
    }
  }
}

/**
 * 校验统一变异体报告（契约 §1/§2/§6；消费者侧严格校验）。
 * @param {unknown} data - 解析后的报告
 * @param {string} filePath - 报告路径（报错用）
 * @returns {{tool: string, timestamp: string, mutants: object[], score?: number}}
 */
function validateReport(data, filePath) {
  const fail = (detail) => {
    throw new CliError(`invalid unified mutation report ${filePath}: ${detail}`);
  };
  if (!isPlainObject(data)) {
    fail('top-level value must be a JSON object');
  }
  const topKeys = Object.keys(data);
  for (const key of topKeys) {
    if (!REPORT_TOP_KEYS.has(key)) {
      fail(`unknown top-level field "${key}" (allowed: ${[...REPORT_TOP_KEYS].join(', ')})`);
    }
  }
  for (const key of ['tool', 'timestamp', 'mutants']) {
    if (!(key in data)) {
      fail(`missing required top-level field "${key}"`);
    }
  }
  if (typeof data.tool !== 'string' || !TOOLS.has(data.tool)) {
    fail(`tool must be one of ${[...TOOLS].join(', ')}`);
  }
  if (typeof data.timestamp !== 'string' || !ISO_UTC_PATTERN.test(data.timestamp)) {
    fail('timestamp must be ISO-8601 UTC (YYYY-MM-DDTHH:MM:SSZ)');
  }
  if (!Array.isArray(data.mutants)) {
    fail('mutants must be an array');
  }
  if ('score' in data) {
    const score = data.score;
    if (typeof score !== 'number' || !Number.isFinite(score) || score < 0 || score > 100) {
      fail('score must be a number between 0 and 100');
    }
  }
  data.mutants.forEach((mutant, index) => {
    const label = `mutants[${index}]`;
    if (!isPlainObject(mutant)) {
      fail(`${label} is not an object`);
    }
    checkFieldSet(mutant, MUTANT_KEYS, label);
    if (typeof mutant.id !== 'string' || !/^(stryker|mutmut)-\S+$/.test(mutant.id)) {
      fail(`${label}.id must match ^(stryker|mutmut)-\\S+$`);
    }
    if (!mutant.id.startsWith(`${data.tool}-`)) {
      fail(`${label}.id "${mutant.id}" must use the "${data.tool}-" prefix to match tool "${data.tool}"`);
    }
    if (!isValidPosixPath(mutant.file)) {
      fail(`${label}.file must be a project-root relative POSIX path (forward slashes, no "./" prefix)`);
    }
    if (!isPositiveInt(mutant.line)) {
      fail(`${label}.line must be an integer >= 1`);
    }
    if (!isPositiveInt(mutant.column)) {
      fail(`${label}.column must be an integer >= 1`);
    }
    if (!MUTATION_TYPES.has(mutant.mutationType)) {
      fail(`${label}.mutationType "${mutant.mutationType}" is not in the closed enum (docs/formats/unified-mutation-report.md §4)`);
    }
    if (!isNonEmptyString(mutant.original)) {
      fail(`${label}.original must be a non-empty string`);
    }
    if (!isNonEmptyString(mutant.mutated)) {
      fail(`${label}.mutated must be a non-empty string`);
    }
    if (mutant.mutated === mutant.original) {
      fail(`${label}.mutated must differ from original`);
    }
    if (!STATUSES.has(mutant.status)) {
      fail(`${label}.status "${mutant.status}" is not in the closed enum (docs/formats/unified-mutation-report.md §5)`);
    }
  });
  return data;
}

/**
 * 校验豁免文件（equivalent-mutants.md §2/§3/§7；未知 version 报错退出）。
 * @param {unknown} data - 解析后的豁免文件
 * @param {string} filePath - 文件路径（报错用）
 * @returns {object[]} 豁免条目数组
 */
function validateExemptions(data, filePath) {
  const fail = (detail) => {
    throw new CliError(`invalid exemptions file ${filePath}: ${detail}`);
  };
  if (!isPlainObject(data)) {
    fail('top-level value must be a JSON object with version and exemptions');
  }
  const topKeys = Object.keys(data);
  for (const key of topKeys) {
    if (key !== 'version' && key !== 'exemptions') {
      fail(`unknown top-level field "${key}" (allowed: version, exemptions)`);
    }
  }
  if (!('version' in data)) {
    fail('missing required top-level field "version"');
  }
  if (data.version !== '1.0') {
    fail(`unsupported version ${JSON.stringify(data.version)} (only "1.0" is supported)`);
  }
  if (!('exemptions' in data)) {
    fail('missing required top-level field "exemptions"');
  }
  if (!Array.isArray(data.exemptions)) {
    fail('exemptions must be an array');
  }
  const seenIds = new Set();
  data.exemptions.forEach((entry, index) => {
    const label = `exemptions[${index}]`;
    if (!isPlainObject(entry)) {
      fail(`${label} is not an object`);
    }
    checkFieldSet(entry, EXEMPTION_KEYS, label);
    if (typeof entry.id !== 'string' || !/^equiv-\d{3,}$/.test(entry.id)) {
      fail(`${label}.id must match ^equiv-\\d{3,}$`);
    }
    if (seenIds.has(entry.id)) {
      fail(`duplicate exemption id "${entry.id}" (ids must be unique and never reused)`);
    }
    seenIds.add(entry.id);
    if (!isValidPosixPath(entry.file)) {
      fail(`${label}.file must be a project-root relative POSIX path (forward slashes, no "./" prefix)`);
    }
    if (!isPositiveInt(entry.line)) {
      fail(`${label}.line must be an integer >= 1`);
    }
    if (!MUTATION_TYPES.has(entry.mutationType)) {
      fail(`${label}.mutationType "${entry.mutationType}" is not in the closed enum (docs/formats/unified-mutation-report.md §4)`);
    }
    if (!isNonEmptyString(entry.reason)) {
      fail(`${label}.reason must be a non-empty string`);
    }
    if (!isNonEmptyString(entry.exemptedBy)) {
      fail(`${label}.exemptedBy must be a non-empty string`);
    }
    if (typeof entry.exemptedAt !== 'string' || !ISO_UTC_PATTERN.test(entry.exemptedAt)) {
      fail(`${label}.exemptedAt must be ISO-8601 UTC (YYYY-MM-DDTHH:MM:SSZ)`);
    }
    if (typeof entry.reviewRequired !== 'boolean') {
      fail(`${label}.reviewRequired must be a boolean`);
    }
  });
  return data.exemptions;
}

/**
 * 豁免匹配键：file + line + mutationType 三元组（equivalent-mutants.md §4.3）。
 * @param {object} entry - 豁免条目或 mutant
 * @returns {string} 三元组键
 */
function exemptionKey(entry) {
  return `${entry.file}\u0000${entry.line}\u0000${entry.mutationType}`;
}

/**
 * 应用豁免过滤：命中的变异体剔除；失配条目记为陈旧。
 * @param {object[]} survivors - status === 'Survived' 的变异体
 * @param {object[]|null} exemptions - 豁免条目（null 表示未提供豁免文件）
 * @returns {{kept: object[], exemptedCount: number, staleIds: string[]}}
 */
function applyExemptions(survivors, exemptions) {
  if (!exemptions) {
    return { kept: survivors, exemptedCount: 0, staleIds: [] };
  }
  const keys = new Set(exemptions.map(exemptionKey));
  const kept = [];
  let exemptedCount = 0;
  for (const mutant of survivors) {
    if (keys.has(exemptionKey(mutant))) {
      exemptedCount++;
    } else {
      kept.push(mutant);
    }
  }
  const staleIds = exemptions
    .filter((entry) => !survivors.some((mutant) => exemptionKey(mutant) === exemptionKey(entry)))
    .map((entry) => entry.id);
  return { kept, exemptedCount, staleIds };
}

/**
 * 按 file 字段分组（字节级精确相等），组按 file 升序（契约 §1 / 模板 §1）。
 * @param {object[]} mutants - 过滤后的存活变异体
 * @returns {{file: string, mutants: object[]}[]}
 */
function groupByFile(mutants) {
  const byFile = new Map();
  for (const mutant of mutants) {
    if (!byFile.has(mutant.file)) {
      byFile.set(mutant.file, []);
    }
    byFile.get(mutant.file).push(mutant);
  }
  return [...byFile.keys()].sort().map((file) => ({ file, mutants: byFile.get(file) }));
}

/**
 * issue 标题（模板契约 §2；survivors 恒复数）。
 * @param {string} file - 分组文件路径
 * @param {number} count - 豁免过滤后存活数
 * @returns {string} 标题
 */
function buildTitle(file, count) {
  return `[Mutation] ${file} - ${count} survivors`;
}

/**
 * 队列文件路径（模板契约 §4.1，保留子目录与大小写）。
 * @param {string} file - 分组文件路径
 * @returns {string} .mutation-queue/{file}.json
 */
function queuePathFor(file) {
  return `${QUEUE_DIR}/${file}.json`;
}

/**
 * body 预览路径（dry-run 供检查用，与队列文件同目录）。
 * @param {string} file - 分组文件路径
 * @returns {string} .mutation-queue/{file}.body.md
 */
function previewPathFor(file) {
  return `${QUEUE_DIR}/${file}.body.md`;
}

/**
 * 选择围栏：片段任一行含 ≥3 连续反引号时，用比最长反引号串更长的围栏
 * （模板契约 §3.3，CommonMark 规则）。
 * @param {string} original - 原始片段
 * @param {string} mutated - 变异后片段
 * @returns {string} 围栏（如 "```" 或 "````"）
 */
function pickFence(original, mutated) {
  let longest = 0;
  for (const snippet of [original, mutated]) {
    for (const line of snippet.split('\n')) {
      const runs = line.match(/`+/g) || [];
      for (const run of runs) {
        if (run.length > longest) {
          longest = run.length;
        }
      }
    }
  }
  return '`'.repeat(longest >= 3 ? longest + 1 : 3);
}

/**
 * 渲染单个变异体小节（模板契约 §3.1/§3.2，占位符原样代入）。
 * @param {object} mutant - 统一报告 mutant 对象
 * @param {string} fence - 围栏
 * @returns {string[]} 行列表
 */
function renderMutantSection(mutant, fence) {
  return [
    `### ${mutant.id}：line ${mutant.line}`,
    '',
    `- column：${mutant.column}`,
    `- mutationType：\`${mutant.mutationType}\``,
    `- status：\`${mutant.status}\``,
    '',
    'original：',
    '',
    `${fence}text`,
    mutant.original,
    fence,
    '',
    'mutated：',
    '',
    `${fence}text`,
    mutant.mutated,
    fence,
    ''
  ];
}

/**
 * 渲染 issue body（模板契约 §3：三小节固定、顺序固定、固定文案逐字）。
 * @param {string} tool - 报告顶层 tool
 * @param {string} timestamp - 报告顶层 timestamp
 * @param {string} file - 分组文件路径
 * @param {object[]} mutants - 该组变异体（报告顺序）
 * @param {string} queuePath - 队列文件相对路径
 * @returns {string} body 全文（单尾换行）
 */
function renderIssueBody(tool, timestamp, file, mutants, queuePath) {
  const lines = [];
  lines.push('## 存活变异体');
  lines.push('');
  lines.push(
    `\`${file}\` 在 ${timestamp} 的夜跑中有 ${mutants.length} 个存活变异体（工具：${tool}）。` +
      '以下清单与机读数据一致，处理方法见文末指引。'
  );
  lines.push('');
  for (const mutant of mutants) {
    lines.push(...renderMutantSection(mutant, pickFence(mutant.original, mutant.mutated)));
  }
  lines.push('## 机读数据');
  lines.push('');
  lines.push(`补测 agent 读取：[${queuePath}](${queuePath})`);
  lines.push('');
  lines.push('## 补测指引');
  lines.push('');
  lines.push(GUIDE_TEXT);
  return `${lines.join('\n')}\n`;
}

/**
 * 渲染队列文件对象（模板契约 §4.3；mutants 逐字段原样复制；
 * issueNumber 实跑在场——创建组为新建编号，去重跳过组为既有 open
 * issue 编号；dry-run 省略）。
 * @param {string} tool - 报告顶层 tool
 * @param {string} timestamp - 报告顶层 timestamp
 * @param {string} file - 分组文件路径
 * @param {object[]} mutants - 该组变异体（报告顺序）
 * @param {number|undefined} issueNumber - 创建组的新编号 / 跳过组的既有编号
 * @returns {object} 队列文件对象
 */
function buildQueueDoc(tool, timestamp, file, mutants, issueNumber) {
  const doc = {
    version: QUEUE_VERSION,
    file,
    tool,
    timestamp,
    mutants
  };
  if (issueNumber !== undefined) {
    doc.issueNumber = issueNumber;
  }
  return doc;
}

/**
 * 把某组的队列文件原子写盘。实跑在每组创建/跳过完成后立即调用（逐组
 * 持久化，gh 中途失败时已完成组的条目保留）；dry-run 在收尾循环调用。
 * @param {{tool: string, timestamp: string}} report - 已校验的统一报告
 * @param {{file: string, mutants: object[], queuePath: string}} plan - 组计划
 * @param {number|undefined} issueNumber - 创建组的新编号 / 跳过组的既有编号
 * @returns {void}
 */
function writeQueueFile(report, plan, issueNumber) {
  writeTextFile(
    plan.queuePath,
    `${JSON.stringify(buildQueueDoc(report.tool, report.timestamp, plan.file, plan.mutants, issueNumber), null, 2)}\n`
  );
}

/**
 * 删除某组既有的队列文件（实跑创建路径专用，gh 调用前调用）：上一轮运行
 * 可能遗留陈旧条目，先失效它，gh 失败时磁盘上不留过期数据误导 agent；
 * 成功路径随后由 writeQueueFile 用本轮数据重建。文件不存在时是 no-op；
 * 删除失败的原始 fs 错误照常上抛。
 * @param {string} queuePath - 队列文件路径
 * @returns {void}
 */
function removeStaleQueueFile(queuePath) {
  if (!fs.existsSync(queuePath)) {
    return;
  }
  fs.rmSync(queuePath, { force: true });
}

/**
 * 解析 gh 可执行 argv：默认 ['gh']，可用 MUTATION_ISSUES_GH 换成
 * "|"-分隔的 argv 前缀（测试钩子）。
 * @returns {string[]} argv 前缀
 */
function resolveGhArgv() {
  const spec = process.env.MUTATION_ISSUES_GH;
  if (!spec) {
    return ['gh'];
  }
  const argv = spec.split('|').filter((part) => part !== '');
  return argv.length > 0 ? argv : ['gh'];
}

/**
 * 运行 gh 子命令；spawn 失败或非零退出抛 GhError。
 * @param {string[]} ghArgs - gh 及其参数
 * @returns {string} stdout
 */
function runGh(ghArgs) {
  const base = resolveGhArgv();
  const result = spawnSync(base[0], [...base.slice(1), ...ghArgs], {
    encoding: 'utf8',
    windowsHide: true
  });
  if (result.error) {
    throw new GhError(`failed to run gh (${base.join(' ')}): ${result.error.message}`);
  }
  if (result.status !== 0) {
    const detail = `${result.stderr || ''}${result.stdout || ''}`.trim();
    throw new GhError(`gh ${ghArgs.join(' ')} failed with exit code ${result.status}: ${detail}`);
  }
  return result.stdout || '';
}

/**
 * 确保标签存在（模板契约 §5）：先 gh label list，缺哪个补哪个；已存在的
 * 同名标签不改动；并发创建的 "already exists" 容忍。
 * @returns {void}
 */
function ensureLabels() {
  const stdout = runGh(['label', 'list', '--json', 'name']);
  let names;
  try {
    const parsed = JSON.parse(stdout);
    names = new Set(parsed.map((entry) => entry && entry.name).filter(isNonEmptyString));
  } catch (err) {
    throw new GhError(`failed to parse gh label list output as JSON: ${err.message} (output: ${stdout.trim().slice(0, 200)})`);
  }
  for (const label of ISSUE_LABELS) {
    if (names.has(label.name)) {
      continue;
    }
    try {
      runGh([
        'label',
        'create',
        label.name,
        '--color',
        label.color,
        '--description',
        label.description
      ]);
    } catch (err) {
      if (err instanceof GhError && /already exists/i.test(err.message)) {
        continue;
      }
      throw err;
    }
  }
}

/**
 * 取回 open 状态、带 mutation 标签的 issue 候选（模板契约 §7 检索约定）。
 * @returns {{number: number, title: string}[]}
 */
function fetchOpenMutationIssues() {
  const stdout = runGh(['issue', 'list', '--state', 'open', '--label', 'mutation', '--json', 'number,title']);
  try {
    const parsed = JSON.parse(stdout);
    if (!Array.isArray(parsed)) {
      throw new Error('expected a JSON array');
    }
    return parsed
      .filter((entry) => isPlainObject(entry) && Number.isInteger(entry.number))
      .map((entry) => ({ number: entry.number, title: typeof entry.title === 'string' ? entry.title : '' }));
  } catch (err) {
    throw new GhError(`failed to parse gh issue list output as JSON: ${err.message} (output: ${stdout.trim().slice(0, 200)})`);
  }
}

/**
 * 从 gh issue create 的 stdout 解析 issue URL 与编号。
 * @param {string} stdout - gh 输出
 * @returns {{number: number, url: string}}
 */
function parseIssueUrl(stdout) {
  for (const line of stdout.split(/\r?\n/).reverse()) {
    const match = /^\s*((?:https?:\/\/)?\S+\/issues\/(\d+))\s*$/.exec(line);
    if (match) {
      const url = match[1].startsWith('http') ? match[1] : `https://${match[1]}`;
      return { url, number: Number(match[2]) };
    }
  }
  throw new GhError(`could not parse issue URL from gh issue create output: ${stdout.trim().slice(0, 200)}`);
}

/**
 * 创建单个 issue（模板契约 §3.3：body 经 --body-file 传入）。
 * @param {string} title - issue 标题
 * @param {string} body - body 全文
 * @param {string} bodyFile - 已写好的 body 临时文件路径
 * @param {string|undefined} assignee - 可选指派
 * @returns {{number: number, url: string}}
 */
function createIssue(title, body, bodyFile, assignee) {
  const ghArgs = [
    'issue',
    'create',
    '--title',
    title,
    '--body-file',
    bodyFile,
    '--label',
    'mutation',
    '--label',
    'nightly'
  ];
  if (assignee) {
    ghArgs.push('--assignee', assignee);
  }
  const stdout = runGh(ghArgs);
  return parseIssueUrl(stdout);
}

/**
 * 原子写文本文件（UTF-8、LF、按需递归建目录）：先写同目录临时文件再
 * rename 覆盖目标，写入中断或失败都不会留下半截目标文件。
 * @param {string} filePath - 目标路径（相对运行目录或绝对）
 * @param {string} content - 内容
 * @returns {void}
 */
function writeTextFile(filePath, content) {
  const dir = path.dirname(filePath);
  fs.mkdirSync(dir, { recursive: true });
  const tmpPath = path.join(dir, `.${path.basename(filePath)}.tmp-${process.pid}`);
  try {
    fs.writeFileSync(tmpPath, content, 'utf8');
    fs.renameSync(tmpPath, filePath);
  } catch (err) {
    try {
      fs.rmSync(tmpPath, { force: true });
    } catch {
      // 清理失败不掩盖原始写入错误
    }
    throw err;
  }
}

/**
 * 打印用法说明（--help）。
 */
function printHelp() {
  const lines = [
    'Usage: node scripts/create-mutation-issues.mjs --input <path> [options]',
    '',
    'Read a unified mutation report (docs/formats/unified-mutation-report.md), keep the',
    'mutants with status "Survived", apply .equivalent-mutants.json exemptions',
    '(file + line + mutationType triple match), group by file, and produce dual output',
    'per group (docs/formats/mutation-issue-template.md): a human-readable GitHub issue',
    'and a machine-readable queue file .mutation-queue/{file}.json for agents.',
    '',
    'Modes:',
    '  default (no mode flag)  Create: ensure labels (gh label list/create),',
    '                          dedup against open issues (prefix "[Mutation] {file} - "',
    '                          + mutation label), then create via gh issue create.',
    '  --dry-run               Preview: write queue files and body previews',
    '                          (.mutation-queue/{file}.body.md); never calls gh.',
    '  --create-issues         Accepted as a no-op for backward compatibility;',
    '                          creating issues is already the default. Combined with',
    '                          --dry-run it stays in preview mode.',
    '',
    'Options:',
    '  --input <path>       Unified mutation report JSON (required)',
    '  --exemptions <path>  .equivalent-mutants.json; missing file, invalid JSON or',
    '                       schema exit with code 1 (default: no filtering)',
    '  --output <path>      Write a manifest JSON (issue list + metadata + summary)',
    '  --assignee <login>   Assign created issues to this user (create mode only;',
    '                       refused together with --dry-run)',
    '  -h, --help           Show this help and exit',
    '',
    'Output:',
    '  Queue file .mutation-queue/{file}.json: { version: "1.0", file, tool, timestamp,',
    '  issueNumber (real run: the created issue number, or the existing open issue',
    '  number for skipped groups), mutants: [8-field copies in report order] }.',
    '  Queue files are written atomically (temp file + rename) immediately after each',
    '  create/skip completes, so a partial gh failure keeps entries for completed',
    '  operations; each run overwrites the previous queue files. Before each',
    "  issue-create gh call the group's pre-existing queue file is deleted first,",
    '  so a failed create leaves no stale entry from a previous run. Dry-run omits',
    '  issueNumber.',
    '  Body preview (dry-run): .mutation-queue/{file}.body.md, identical to the issue body.',
    '  Manifest (--output): { version, mode, tool, timestamp, generatedAt, input,',
    '  exemptionsFile, summary: { totalMutants, exempted, nonSurvivedDropped,',
    '  issuesCreated, issuesSkipped }, staleExemptionIds, issues: [{ file, title, labels,',
    '  queuePath, previewPath (dry-run), mutantCount, mutantIds, status',
    '  "dry-run|created|skipped", issueNumber + issueUrl (created), skippedIssueNumber',
    '  (skipped) }] }.',
    '  stdout carries a human-readable summary: total mutants, exempted,',
    '  issues created, issues skipped.',
    '',
    'Issue contract:',
    '  Title: "[Mutation] {file} - N survivors" (always plural; N is the count at',
    '  creation time). Labels: mutation + nightly. Body: three fixed sections',
    '  (survivor list, machine-readable data link, fixed testing guide).',
    '  Dedup key: open issue whose title starts with "[Mutation] {file} - " and has',
    '  the mutation label; matches are skipped and counted, and their queue file',
    '  carries the existing issue number as issueNumber. Closed same-name issues do',
    '  not block new ones.',
    '',
    'Environment:',
    '  MUTATION_ISSUES_GH  "|"-separated argv prefix replacing gh (testing hook),',
    '                      e.g. "node|C:/tools/fake-gh.mjs"',
    '',
    'Examples:',
    '  node scripts/create-mutation-issues.mjs --input unified-mutation-report.json',
    '  node scripts/create-mutation-issues.mjs --input unified-mutation-report.json --dry-run',
    '  node scripts/create-mutation-issues.mjs --input report.json \\',
    '      --exemptions .equivalent-mutants.json --output manifest.json',
    '  node scripts/create-mutation-issues.mjs --input report.json --assignee alice',
    '',
    'Exit codes:',
    '  0  success (including empty lists and skipped duplicates)',
    '  1  user error: bad arguments, missing file, invalid JSON, unified report or',
    '     exemptions schema violation, flag conflicts',
    '  2  tool failure: gh CLI spawn failure, non-zero exit, or unparseable output'
  ];
  process.stdout.write(`${lines.join('\n')}\n`);
}

/**
 * 打印单行用法（缺 --input 时输出到 stderr）。
 * @param {NodeJS.WriteStream} stream - 输出流
 */
function printUsage(stream) {
  stream.write('Usage: node scripts/create-mutation-issues.mjs --input <unified-report.json> [options]\n');
  stream.write('Run with --help for details.\n');
}

/**
 * CLI 入口：解析参数、校验报告与豁免、分组、按模式产出，返回退出码。
 * @param {string[]} argv - process.argv.slice(2)
 * @returns {number} 退出码：0 成功；1 用户错误；2 gh 失败
 */
function main(argv) {
  const args = parseArgs(argv);
  if (args.help) {
    printHelp();
    return 0;
  }
  if (!args.input) {
    process.stderr.write('Error: --input <unified-mutation-report.json> is required\n');
    printUsage(process.stderr);
    return 1;
  }
  // 默认即实跑（fix-issue-creator-defaults）；--dry-run 显式进入预览，
  // --create-issues 为兼容 no-op，不再参与模式判定。
  const createMode = !args.dryRun;

  const report = validateReport(readJsonFile(args.input, 'unified mutation report'), args.input);
  const survivors = report.mutants.filter((mutant) => mutant.status === 'Survived');
  const nonSurvivedDropped = report.mutants.length - survivors.length;

  const exemptions = args.exemptions
    ? validateExemptions(readJsonFile(args.exemptions, 'exemptions file'), args.exemptions)
    : null;
  const applied = applyExemptions(survivors, exemptions);

  const groups = groupByFile(applied.kept);
  const plans = groups.map((group) => {
    const queuePath = queuePathFor(group.file);
    return {
      file: group.file,
      mutants: group.mutants,
      title: buildTitle(group.file, group.mutants.length),
      queuePath,
      previewPath: previewPathFor(group.file),
      body: renderIssueBody(report.tool, report.timestamp, group.file, group.mutants, queuePath),
      status: 'pending',
      issueNumber: undefined,
      issueUrl: undefined,
      skippedIssueNumber: undefined
    };
  });

  let issuesCreated = 0;
  let issuesSkipped = 0;
  if (createMode && plans.length > 0) {
    ensureLabels();
    const existing = fetchOpenMutationIssues().sort((a, b) => a.number - b.number);
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'mutation-issue-body-'));
    try {
      plans.forEach((plan, index) => {
        const prefix = `[Mutation] ${plan.file} - `;
        const hit = existing.find((issue) => issue.title.startsWith(prefix));
        if (hit) {
          plan.status = 'skipped';
          plan.skippedIssueNumber = hit.number;
          issuesSkipped++;
          // 跳过也是完成态：队列文件（带既有编号）立即落盘
          writeQueueFile(report, plan, hit.number);
          process.stdout.write(
            `create-mutation-issues: skip "${plan.title}" -> existing open issue #${hit.number}\n`
          );
          return;
        }
        const bodyFile = path.join(tmpDir, `body-${index}.md`);
        fs.writeFileSync(bodyFile, plan.body, 'utf8');
        // 创建 gh 调用前先失效该组旧队列文件：失败时不留上一轮陈旧条目
        removeStaleQueueFile(plan.queuePath);
        const created = createIssue(plan.title, plan.body, bodyFile, args.assignee);
        plan.status = 'created';
        plan.issueNumber = created.number;
        plan.issueUrl = created.url;
        issuesCreated++;
        // 创建成功即刻持久化该组队列文件，后续 gh 失败不影响已完成组
        writeQueueFile(report, plan, created.number);
      });
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  } else {
    for (const plan of plans) {
      plan.status = 'dry-run';
      writeQueueFile(report, plan, undefined);
      writeTextFile(plan.previewPath, plan.body);
    }
  }

  if (args.output) {
    const manifest = {
      version: MANIFEST_VERSION,
      mode: createMode ? 'create' : 'dry-run',
      tool: report.tool,
      timestamp: report.timestamp,
      generatedAt: isoTimestampUtc(),
      input: args.input,
      exemptionsFile: args.exemptions || null,
      summary: {
        totalMutants: report.mutants.length,
        exempted: applied.exemptedCount,
        nonSurvivedDropped,
        issuesCreated,
        issuesSkipped
      },
      staleExemptionIds: applied.staleIds,
      issues: plans.map((plan) => ({
        file: plan.file,
        title: plan.title,
        labels: ['mutation', 'nightly'],
        queuePath: plan.queuePath,
        ...(createMode ? {} : { previewPath: plan.previewPath }),
        mutantCount: plan.mutants.length,
        mutantIds: plan.mutants.map((mutant) => mutant.id),
        status: plan.status,
        ...(plan.status === 'created' ? { issueNumber: plan.issueNumber, issueUrl: plan.issueUrl } : {}),
        ...(plan.status === 'skipped' ? { skippedIssueNumber: plan.skippedIssueNumber } : {})
      }))
    };
    writeTextFile(args.output, `${JSON.stringify(manifest, null, 2)}\n`);
  }

  process.stdout.write(`create-mutation-issues: mode=${createMode ? 'create' : 'dry-run'}\n`);
  process.stdout.write(`create-mutation-issues: total mutants: ${report.mutants.length}\n`);
  process.stdout.write(`create-mutation-issues: exempted: ${applied.exemptedCount}\n`);
  if (nonSurvivedDropped > 0) {
    process.stdout.write(`create-mutation-issues: non-survived dropped: ${nonSurvivedDropped}\n`);
  }
  process.stdout.write(`create-mutation-issues: issues created: ${issuesCreated}\n`);
  process.stdout.write(`create-mutation-issues: issues skipped: ${issuesSkipped}\n`);
  if (applied.staleIds.length > 0) {
    process.stdout.write(`create-mutation-issues: stale exemption entries: ${applied.staleIds.join(', ')}\n`);
  }
  return 0;
}

try {
  process.exit(main(process.argv.slice(2)));
} catch (err) {
  if (err instanceof CliError) {
    process.stderr.write(`Error: ${err.message}\n`);
    process.exit(1);
  }
  if (err instanceof GhError) {
    process.stderr.write(`Error: ${err.message}\n`);
    process.exit(2);
  }
  process.stderr.write(`Error: ${(err && err.stack) || String(err)}\n`);
  process.exit(1);
}
