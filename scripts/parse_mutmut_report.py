#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/parse_mutmut_report.py
@version 1.0.0

mutmut 结果解析器（夜跑闭环 M2）：读取 mutmut 的运行输出文本捕获、结果导出
JSON 或原生 .mutmut-cache（SQLite），提取 Survived / Suspicious 两类变异体，
转换为统一变异体报告格式（docs/formats/unified-mutation-report.md，契约 v1.1）：
    { tool: 'mutmut', timestamp, mutants: [...], score? }
mutant 字段 id/file/line/column/mutationType/original/mutated/status 按契约
§2/§3 归一化：id 为 mutmut-<序号>（按 §3.5 排序后从 1 起数）；mutmut 原生
数据缺列号时按 diff 行内差异位置计算，整行/多行片段回退填 1；original 取
mutmut show diff 的 - 行、mutated 取 + 行（剥离 diff 前缀），单行对按词法
记号求最小替换片段（对齐契约 §7.2 示例口径），无法求出时回退整行；
mutationType 按 §4.2 映射表从 diff 文本归类，归类不了写 Unknown 并向 stderr
打警告；路径仅归一分隔符与 ./ 前缀，大小写逐字保留；mutants 按
file/line/column 升序。
分数：导出 JSON 显式分数（metrics.mutationScore → mutationScore → score）
原样记录；否则按检出口径 round2((killed+timeout)/total*100)（Timeout 计入
检出、Suspicious 不计入，与 mutation-baseline.mjs 同口径）；文本捕获的分数
统计以节标题计数（如 "Killed (9) Survived (1)"）为权威口径，逐行条目仅在
节标题无计数时回退参与统计；变异范围为空记 100；纯 show diff 捕获无运行
统计，省略 score 字段（契约 v1.1 可选）。
输入形态（自动识别，详见 --help）：(1) mutmut 文本捕获 = `mutmut results`
输出（状态节 + path:line 条目，进度噪声行忽略）+ `mutmut show` 的 unified
diff 块，survived/suspicious 条目必须有配对 diff，否则报错退出；
(2) mutmut 结果导出 JSON { killed/survived/timeout/suspicious/untested/
skipped: [...] }，survived/suspicious 条目必须是带 original+mutated 或 diff
的富对象，纯字符串无法提供替换片段，报错退出；
(3) mutmut 2.x 原生缓存 .mutmut-cache（SQLite，按文件头魔数识别，只读
打开）：缓存有权威的 mutant id、状态（ok_killed/bad_survived/bad_timeout/
ok_suspicious/skipped/untested）、源文件路径与 0 基行号（输出统一 +1 转
1 基），但没有替换片段，survived/suspicious 条目须用 --show 提供
`mutmut show` 输出配对（`mutmut show all` 的 "# mutant <id>" 标记
按 id 精确配对，纯 `mutmut show` 输出按 file+line 回退配对，带标记的块
只按 id 认领以免 killed 块误配同行存活者），缺配对报错退出；分数按全
缓存计数计算（ok_killed 计检出、bad_timeout 计入检出）。
零依赖（Python 标准库，3.8+），解析为纯函数，CLI 入口在文件底部。
未接 hook/CI。

用法:
    python scripts/parse_mutmut_report.py --input <path> [--show <path>] [--output <path>] [--help]

退出码: 0 成功（含空清单）；1 用户错误（缺参、文件缺失、输入不是 mutmut
        格式、survived/suspicious 条目缺片段、未知状态类别、片段非法）。
"""

import errno
import json
import math
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path


class CliError(Exception):
    """CLI 用法/输入错误：只向 stderr 输出 message 并以退出码 1 结束。"""


VALUE_FLAGS = ('--input', '--output', '--show')

# 契约 §5.2 的 mutmut 状态词 → 统一状态（文本节标题与导出类别共用，小写键）。
STATUS_WORDS = {
    'survived': 'Survived',
    'suspicious': 'Suspicious',
    'timeout': 'Timeout',
    'killed': 'Killed',
    'skipped': 'Skipped',
    'no tests': 'NoCoverage',
    'untested': 'NoCoverage',
    'not checked': 'Pending',
    'excluded': 'Ignored',
    'ignored': 'Ignored'
}

# 导出 JSON 的已知状态类别（"untested" 为 mutation-baseline.mjs 既有口径）。
EXPORT_KEYS = ('killed', 'survived', 'timeout', 'suspicious', 'untested', 'skipped',
               'no tests', 'not checked', 'excluded', 'ignored')

# mutmut 2.x 原生缓存（.mutmut-cache，SQLite）Mutant.status 取值 → 统一状态
# （取值集合依据 mutmut 2.5.1 源码：UNTESTED/OK_KILLED/OK_SUSPICIOUS/
# BAD_TIMEOUT/BAD_SURVIVED/SKIPPED；未知值按契约 §5.3 报错退出）。
CACHE_STATUS_WORDS = {
    'bad_survived': 'Survived',
    'ok_suspicious': 'Suspicious',
    'bad_timeout': 'Timeout',
    'ok_killed': 'Killed',
    'skipped': 'Skipped',
    'untested': 'NoCoverage'
}

# SQLite 文件头魔数（缓存与文本/JSON 输入的自动识别依据）。
SQLITE_MAGIC = b'SQLite format 3\x00'

# mutmut 2.5.1（Pony ORM）的缓存 schema 版本；其他版本仍尝试解析并打警告。
CACHE_DB_VERSION = 4

# 夜跑闭环提取的变异体状态（施工票：survived + suspicious）。
EXTRACTED_STATUSES = ('Survived', 'Suspicious')

MUTATION_TYPES = frozenset([
    'ArithmeticOperator', 'ArrayDeclaration', 'ArrowFunction', 'Block',
    'BooleanLiteral', 'ConditionalExpression', 'EqualityOperator',
    'LogicalOperator', 'MethodExpression', 'MethodName', 'NegateCondition',
    'NumberLiteral', 'ObjectLiteral', 'OptionalChaining', 'Regex',
    'StringLiteral', 'SwitchStatement', 'UnaryOperator', 'UpdateOperator',
    'BreakContinue', 'ComparisonOperator', 'DecoratorRemoval',
    'KeywordArgument', 'KeywordLiteral', 'Unknown'
])

# 文本 results 节标题（mutmut 会附 emoji 与计数，余下内容忽略）。
SECTION_RE = re.compile(
    r'^\s*(survived|suspicious|timeout|killed|skipped|no tests|untested|not checked|excluded|ignored)\b',
    re.IGNORECASE
)

# 节标题括号里的计数（如 "Killed 🔪 (9)"）；词与括号间容忍 emoji 等任意
# 非括号字符，同一行合并多个 "词 (计数)" 时逐个提取（分数的权威统计口径）。
SUMMARY_COUNT_RE = re.compile(
    r'\b(?P<status>survived|suspicious|timeout|killed|skipped|no tests|untested|not checked|excluded|ignored)'
    r'[^()\n]*?\(\s*(?P<count>\d+)\s*\)',
    re.IGNORECASE
)

# results 条目："<path>.py:<line>"，容忍 ":<col>" 与 " - Mutation <n>" 后缀。
ENTRY_RE = re.compile(r'^\s*(?P<path>\S+?\.py):(?P<line>\d+)(?::\d+)?\s*(?:-\s*.*)?$')

# mutmut show 的 unified diff 头与 hunk 头。
DIFF_OLD_RE = re.compile(r'^--- (?:a/)?(?P<path>.+?)\s*$')
DIFF_NEW_RE = re.compile(r'^\+\+\+ (?:b/)?(?P<path>.+?)\s*$')
HUNK_RE = re.compile(r'^@@ -(?P<line>\d+)(?:,\d+)? \+\d+(?:,\d+)? @@')

# mutmut show all 在每个 diff 前打印的 mutant id 标记。
SHOW_MARKER_RE = re.compile(r'^#\s*mutant\s+(\d+)\s*$', re.IGNORECASE)

# mutmut show all 的文件分隔头（"---- <path> (n) ----"）。以 4+ 个
# 连字符开头，与 unified diff 的 "--- <path>" 头和 "- <del>" 行都不同形；
# 在 diff 块未闭合时出现应终结当前块，而不是被当成删除行吞掉。
SHOW_FILE_HEADER_RE = re.compile(r'^-{4,}\s.*\s-{4,}$')

# 词法记号：空白、多字符运算符优先、词、单字符标点（用于最小片段与列号）。
TOKEN_RE = re.compile(r'\s+|\*\*|//|<<|>>|<=|>=|==|!=|->|\w+|[^\w\s]')

EQ_TOKENS = ('==', '!=', 'is', 'is not', 'in', 'not in')
CMP_TOKENS = ('<', '<=', '>', '>=')
ARITH_TOKENS = ('+', '-', '*', '/', '//', '%', '**')
LOGIC_TOKENS = ('and', 'or')
KEYWORD_LITERALS = ('None', 'True', 'False')


def round2(value):
    """四舍五入到两位小数（正值半进位，与 mutation-baseline.mjs 的 JS 同口径）。"""
    return math.floor(value * 100.0 + 0.5) / 100.0


def iso_timestamp_utc():
    """当前时刻的 ISO-8601 UTC 时间戳（秒精度，契约 §1）。"""
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def write_out(text):
    """stdout 走字节流写 UTF-8，避免 Windows 控制台编码差异破坏 JSON。"""
    stream = getattr(sys.stdout, 'buffer', None)
    if stream is not None:
        stream.write(text.encode('utf-8'))
        stream.flush()
    else:
        sys.stdout.write(text)


def write_err(text):
    """stderr 同样走字节流写 UTF-8。"""
    stream = getattr(sys.stderr, 'buffer', None)
    if stream is not None:
        stream.write(text.encode('utf-8'))
        stream.flush()
    else:
        sys.stderr.write(text)


def warn(message):
    write_err('warning: %s\n' % message)


def parse_args(argv):
    """解析命令行参数（手写以保持退出码契约并检出重复旗标）。"""
    args = {'help': False, 'input': None, 'output': None, 'show': None}
    index = 0
    while index < len(argv):
        token = argv[index]
        if token in ('--help', '-h'):
            args['help'] = True
            index += 1
            continue
        if token not in VALUE_FLAGS:
            raise CliError('unknown option: %s (see --help)' % token)
        if index + 1 >= len(argv):
            raise CliError('missing value for %s' % token)
        key = token[2:]
        if args[key] is not None:
            raise CliError('duplicate option: %s' % token)
        args[key] = argv[index + 1]
        index += 2
    return args


def read_text_file(path, label):
    """读取 UTF-8 文本（容忍 BOM），缺失与读取失败分别给出清晰提示。"""
    try:
        with open(path, 'r', encoding='utf-8-sig') as handle:
            return handle.read()
    except OSError as err:
        if err.errno == errno.ENOENT:
            raise CliError('%s not found: %s' % (label, path))
        raise CliError('failed to read %s %s: %s' % (label, path, err))


def read_binary_file(path, label):
    """读取原始字节（SQLite 魔数识别与文本解码共用入口）。"""
    try:
        with open(path, 'rb') as handle:
            return handle.read()
    except OSError as err:
        if err.errno == errno.ENOENT:
            raise CliError('%s not found: %s' % (label, path))
        raise CliError('failed to read %s %s: %s' % (label, path, err))


def decode_text(raw, path):
    """字节解码为 UTF-8 文本（容忍 BOM），非法序列给出清晰提示。"""
    try:
        return raw.decode('utf-8-sig')
    except UnicodeDecodeError as err:
        raise CliError('input is not valid UTF-8 text: %s (%s)' % (err, path))


def parse_json_text(raw, path):
    """把文本解析为 JSON，语法错误给出清晰提示。"""
    try:
        return json.loads(raw)
    except ValueError as err:
        raise CliError('failed to parse mutmut output as JSON: %s (%s)' % (err, path))


def normalize_path(raw_path, source_path):
    """归一化为契约 §3.2 的 POSIX 相对路径：反斜杠转正斜杠、去 ./ 前缀，大小写保留。"""
    if not isinstance(raw_path, str) or raw_path.strip() == '':
        raise CliError('mutmut path must be a non-empty string, got %r (%s)' % (raw_path, source_path))
    posix = raw_path.replace('\\', '/')
    while posix.startswith('./'):
        posix = posix[2:]
    if posix == '':
        raise CliError('mutmut path normalizes to an empty path: %r (%s)' % (raw_path, source_path))
    return posix


def tokenize_with_offsets(line):
    tokens = []
    offsets = []
    for match in TOKEN_RE.finditer(line):
        tokens.append(match.group(0))
        offsets.append(match.start())
    return tokens, offsets


def extract_fragment_pair(old_line, new_line):
    """单行 -/+ 对按词法记号求最小替换片段与列号（契约 §3.3/§3.4、§7.2 口径）。

    求不出（多处差异、纯插入/删除、空片段）时回退整行、列号 1
    （mutmut 的 diff 原语是整行，契约 §3.4 允许整块）。
    """
    if '\n' in old_line or '\n' in new_line:
        return old_line, new_line, 1
    old_tokens, old_offsets = tokenize_with_offsets(old_line)
    new_tokens, _ = tokenize_with_offsets(new_line)
    matcher = SequenceMatcher(None, old_tokens, new_tokens, autojunk=False)
    replacements = [op for op in matcher.get_opcodes() if op[0] != 'equal']
    if len(replacements) == 1 and replacements[0][0] == 'replace':
        _, a1, a2, b1, b2 = replacements[0]
        original = ''.join(old_tokens[a1:a2])
        mutated = ''.join(new_tokens[b1:b2])
        if original and mutated and original != mutated:
            return original, mutated, old_offsets[a1] + 1
    return old_line, new_line, 1


def _diff_cores(old, new):
    """去掉公共前后缀，留下真正变化的核心（用于整行片段的分类）。"""
    start = 0
    end_old, end_new = len(old), len(new)
    while start < end_old and start < end_new and old[start] == new[start]:
        start += 1
    while end_old > start and end_new > start and old[end_old - 1] == new[end_new - 1]:
        end_old -= 1
        end_new -= 1
    return old[start:end_old], new[start:end_new]


def _without_not(text):
    stripped = re.sub(r'(?<![\w])not\s+', '', text, count=1)
    if stripped != text:
        return stripped
    return re.sub(r'\s+not(?![\w])', '', text, count=1)


def _is_number(text):
    try:
        int(text, 0)
        return True
    except ValueError:
        pass
    try:
        float(text)
        return True
    except ValueError:
        return False


def _classify_tokens(old, new):
    """契约 §4.2 映射表第 1-10 行的记号级匹配；命中返回类型，未命中返回 None。"""
    if old == new:
        return None
    if old in EQ_TOKENS and new in EQ_TOKENS:
        return 'EqualityOperator'
    if old in CMP_TOKENS and new in CMP_TOKENS:
        return 'ComparisonOperator'
    if old in LOGIC_TOKENS and new in LOGIC_TOKENS:
        return 'LogicalOperator'
    if _without_not(old) == new or _without_not(new) == old:
        return 'NegateCondition'
    if old in ARITH_TOKENS and new in ARITH_TOKENS:
        return 'ArithmeticOperator'
    if old in ('+', '-') and new == '':
        return 'UnaryOperator'
    if new in ('+', '-') and old == '':
        return 'UnaryOperator'
    if len(old) >= 2 and old[0] in ('+', '-') and old[1:] == new:
        return 'UnaryOperator'
    if len(new) >= 2 and new[0] in ('+', '-') and new[1:] == old:
        return 'UnaryOperator'
    if _is_number(old) and _is_number(new):
        return 'NumberLiteral'
    if (len(old) >= 2 and len(new) >= 2 and old[0] == new[0]
            and old[0] in ('"', "'") and old.endswith(old[0]) and new.endswith(new[0])):
        return 'StringLiteral'
    if old in ('break', 'continue') and new in ('break', 'continue'):
        return 'BreakContinue'
    if old in KEYWORD_LITERALS and new in KEYWORD_LITERALS:
        return 'KeywordLiteral'
    return None


def _classify_heuristics(old, new):
    """映射表第 11-13 行的启发式（kwarg / decorator / block）；未命中返回 None。"""
    if old == new:
        return None
    if (('=' in old and new == '') or ('=' in new and old == '')
            or ('=' in old and '=' in new)):
        return 'KeywordArgument'
    if (old.startswith('@') or new.startswith('@')) and old.startswith('@') != new.startswith('@'):
        return 'DecoratorRemoval'
    if 'pass' in new.split() or 'pass' in old.split():
        return 'Block'
    return None


def classify_mutation(original, mutated):
    """归一化 mutationType（§4.2）：整片段与变化核心各过一遍记号级与启发式匹配。"""
    old = original.strip()
    new = mutated.strip()
    if old == new:
        return 'Unknown'
    core_old, core_new = _diff_cores(old, new)
    core_old = core_old.strip()
    core_new = core_new.strip()
    result = _classify_tokens(old, new)
    if result is not None:
        return result
    if (core_old, core_new) != (old, new):
        result = _classify_tokens(core_old, core_new)
        if result is not None:
            return result
    result = _classify_heuristics(old, new)
    if result is not None:
        return result
    if (core_old, core_new) != (old, new):
        result = _classify_heuristics(core_old, core_new)
        if result is not None:
            return result
    return 'Unknown'


def build_mutant(file_path, line, column, original, mutated, status, source_path):
    """构造契约 §2 的 mutant 对象并校验字段约束（id 在排序后统一编号）。"""
    if not isinstance(line, int) or isinstance(line, bool) or line < 1:
        raise CliError('mutant line must be an integer >= 1, got %r for "%s" (%s)' % (line, file_path, source_path))
    if not isinstance(column, int) or isinstance(column, bool) or column < 1:
        raise CliError('mutant column must be an integer >= 1, got %r for "%s" (%s)' % (column, file_path, source_path))
    if not isinstance(original, str) or original == '':
        raise CliError('mutant original must be a non-empty string for "%s:%s" (%s)' % (file_path, line, source_path))
    if not isinstance(mutated, str) or mutated == '':
        raise CliError('mutant produces an empty replacement for "%s:%s"; the unified format requires non-empty original and mutated (%s)' % (file_path, line, source_path))
    if original == mutated:
        raise CliError('mutant replacement is identical to the original fragment %r for "%s:%s" (%s)' % (original, file_path, line, source_path))
    if status not in EXTRACTED_STATUSES:
        raise CliError('unexpected extracted status %r for "%s:%s" (%s)' % (status, file_path, line, source_path))
    mutation_type = classify_mutation(original, mutated)
    if mutation_type == 'Unknown':
        warn('could not classify mutation %r -> %r at %s:%s, using Unknown' % (original, mutated, file_path, line))
    return {
        'id': None,
        'file': file_path,
        'line': line,
        'column': column,
        'mutationType': mutation_type,
        'original': original,
        'mutated': mutated,
        'status': status
    }


def finalize_diff_block(block, source_path):
    """收束一个 show diff 块：校验头/行号并提取 -/+ 片段与坐标。"""
    if block['new_path'] is None and not block['deleted'] and not block['added']:
        return None
    if block['new_path'] is None:
        raise CliError('diff block for "%s" has no "+++" header (%s)' % (block['path'], source_path))
    old_file = normalize_path(block['path'], source_path)
    new_file = normalize_path(block['new_path'], source_path)
    if old_file != new_file:
        raise CliError('diff block headers disagree: "--- %s" vs "+++ %s" (%s)' % (block['path'], block['new_path'], source_path))
    if block['line'] is None:
        raise CliError('diff block for "%s" has no @@ hunk header (%s)' % (old_file, source_path))
    if not block['deleted'] or not block['added']:
        raise CliError('diff block for "%s:%s" is a pure insertion or deletion; the unified format requires non-empty original and mutated (%s)' % (old_file, block['line'], source_path))
    if len(block['deleted']) == 1 and len(block['added']) == 1:
        original, mutated, column = extract_fragment_pair(block['deleted'][0], block['added'][0])
    else:
        original = '\n'.join(block['deleted'])
        mutated = '\n'.join(block['added'])
        column = 1
    return {'file': old_file, 'line': block['line'], 'original': original, 'mutated': mutated, 'column': column}


def parse_diff_blocks(text, source_path, collect_markers=False):
    """扫描文本中的 mutmut show unified diff 块（其余行视为噪声忽略）。

    行号取第一个 - 行在源文件中的行号（hunk 头起点 + 前置上下文行推进）。
    collect_markers 为真时返回 (标记 id 或 None, 块) 列表：标记来自
    `mutmut show all` 在 diff 前打印的 "# mutant <id>" 行，绑定到
    其后紧跟的第一个 diff 块。
    """
    blocks = []
    block = None
    pending_marker = None

    def finish(current):
        finished = finalize_diff_block(current, source_path)
        if finished is None:
            return
        if collect_markers:
            blocks.append((current.get('marker'), finished))
        else:
            blocks.append(finished)

    for raw_line in text.split('\n'):
        line = raw_line[:-1] if raw_line.endswith('\r') else raw_line
        marker_match = SHOW_MARKER_RE.match(line)
        if marker_match:
            pending_marker = int(marker_match.group(1))
            continue
        old_match = DIFF_OLD_RE.match(line)
        if old_match:
            if block is not None:
                finish(block)
            block = {'path': old_match.group('path'), 'new_path': None, 'line': None,
                     'deleted': [], 'added': [], 'in_hunk': False, 'old_cursor': 0,
                     'marker': pending_marker}
            pending_marker = None
            continue
        if block is None:
            continue
        new_match = DIFF_NEW_RE.match(line)
        if new_match and block['new_path'] is None:
            block['new_path'] = new_match.group('path')
            continue
        hunk_match = HUNK_RE.match(line)
        if hunk_match and block['new_path'] is not None:
            if block['line'] is None:
                block['old_cursor'] = int(hunk_match.group('line'))
            block['in_hunk'] = True
            continue
        if block['new_path'] is not None and block['in_hunk']:
            if SHOW_FILE_HEADER_RE.match(line):
                # show all 的下一个文件分隔头：终结当前块。
                finish(block)
                block = None
                continue
            if line.startswith('+'):
                block['added'].append(line[1:])
                continue
            if line.startswith('-'):
                if block['line'] is None:
                    block['line'] = block['old_cursor']
                block['deleted'].append(line[1:])
                block['old_cursor'] += 1
                continue
            # 上下文行（含空行）推进旧侧行号。
            block['old_cursor'] += 1
    if block is not None:
        finish(block)
    return blocks


def parse_results_entries(text, source_path):
    """扫描文本 results 节与条目。

    返回 (条目列表, 是否见过统计节, summary 计数映射)：计数映射把统一状态
    映到节标题括号里的数字（如 "Killed 🔪 (9)" → {'Killed': 9}），同一行
    合并多组 "词 (计数)" 时逐个提取，同状态冲突时保留先见值并向 stderr
    打警告。
    """
    entries = []
    saw_summary = False
    section_counts = {}
    current_status = None
    for raw_line in text.split('\n'):
        line = raw_line[:-1] if raw_line.endswith('\r') else raw_line
        stripped = line.lstrip()
        if stripped.startswith(('+', '-', '@')):
            continue
        section = SECTION_RE.match(line)
        if section:
            current_status = STATUS_WORDS[section.group(1).lower()]
            saw_summary = True
            for count_match in SUMMARY_COUNT_RE.finditer(line):
                status = STATUS_WORDS[count_match.group('status').lower()]
                count = int(count_match.group('count'))
                if status in section_counts:
                    if section_counts[status] != count:
                        warn('conflicting summary counts for %s in %s: keeping %d, ignoring %d'
                             % (status, source_path, section_counts[status], count))
                else:
                    section_counts[status] = count
            continue
        entry = ENTRY_RE.match(line)
        if entry:
            status = current_status if current_status is not None else 'Survived'
            entries.append({
                'file': normalize_path(entry.group('path'), source_path),
                'line': int(entry.group('line')),
                'status': status
            })
            saw_summary = True
    return entries, saw_summary, section_counts


def mutant_from_block(block, status, source_path):
    return build_mutant(block['file'], block['line'], block['column'],
                        block['original'], block['mutated'], status, source_path)


def parse_text_capture(text, source_path):
    """解析 mutmut 文本捕获：条目定状态、diff 块定片段，按 file+line 配对。"""
    entries, saw_summary, section_counts = parse_results_entries(text, source_path)
    blocks = parse_diff_blocks(text, source_path)
    entry_index = {}
    for entry in entries:
        entry_index.setdefault((entry['file'], entry['line']), entry)
    mutants = []
    matched_keys = set()
    unpaired_blocks = 0
    for block in blocks:
        key = (block['file'], block['line'])
        entry = entry_index.get(key)
        if entry is None:
            unpaired_blocks += 1
            mutants.append(mutant_from_block(block, 'Survived', source_path))
        elif entry['status'] in EXTRACTED_STATUSES:
            matched_keys.add(key)
            mutants.append(mutant_from_block(block, entry['status'], source_path))
        # 配到 killed/timeout 等条目的 diff 块只参与统计，不进入输出。
    for entry in entries:
        if entry['status'] in EXTRACTED_STATUSES and (entry['file'], entry['line']) not in matched_keys:
            raise CliError('survived mutant %s:%s has no "mutmut show" diff in the capture; '
                           'include the show output for every survived/suspicious mutant (%s)'
                           % (entry['file'], entry['line'], source_path))
    if not entries and not saw_summary and not blocks:
        raise CliError('input does not look like mutmut output: no results sections, '
                       'result entries, or "mutmut show" diffs found (%s)' % source_path)
    if section_counts:
        # 节标题计数是工具亲口报出的统计（捕获可能只截取了部分条目行），
        # 比逐行重数条目更可靠，作为分数的权威口径；未配对 diff 块不再加回。
        stats = stats_from_summary_counts(section_counts)
    else:
        stats = count_entry_stats(entries, extra_survived=unpaired_blocks)
    return mutants, stats, saw_summary


def count_entry_stats(entries, extra_survived=0):
    """按统一状态计数（total 含所有条目；未配对 diff 块计为 Survived）。"""
    stats = {'total': len(entries) + extra_survived, 'killed': 0, 'timeout': 0}
    for entry in entries:
        if entry['status'] == 'Killed':
            stats['killed'] += 1
        elif entry['status'] == 'Timeout':
            stats['timeout'] += 1
    return stats


def stats_from_summary_counts(section_counts):
    """按 summary 节计数构建统计（total = 各节计数之和；分数的权威口径）。"""
    stats = {'total': 0, 'killed': 0, 'timeout': 0}
    for status, count in section_counts.items():
        stats['total'] += count
        if status == 'Killed':
            stats['killed'] = count
        elif status == 'Timeout':
            stats['timeout'] = count
    return stats


def read_mutmut_cache(path):
    """只读解析 mutmut 2.x 的 .mutmut-cache（SQLite，Pony ORM schema）。

    返回 (survived/suspicious 条目列表, 全缓存统计)。缓存是状态、路径与
    0 基行号的权威来源（输出统一 +1 转 1 基），但不含替换片段；片段由
    pair_cache_entries 按 --show 文本配对补齐。以 mode=ro URI 打开，不在
    缓存旁产生任何副作用文件。
    """
    uri = Path(os.path.abspath(path)).as_uri() + '?mode=ro'
    try:
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as err:
        raise CliError('failed to open mutmut cache %s: %s' % (path, err))
    try:
        try:
            tables = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            missing = sorted({'SourceFile', 'Line', 'Mutant'} - tables)
            if missing:
                raise CliError('not a mutmut cache: missing tables %s (%s)'
                               % (', '.join(missing), path))
            version_row = None
            if 'MiscData' in tables:
                version_row = conn.execute(
                    "SELECT value FROM MiscData WHERE key='version'").fetchone()
            total = conn.execute('SELECT COUNT(*) FROM "Mutant"').fetchone()[0]
            rows = conn.execute(
                'SELECT m."id", m."status", l."line_number", l."line", f."filename"'
                ' FROM "Mutant" AS m'
                ' JOIN "Line" AS l ON m."line" = l."id"'
                ' JOIN "SourceFile" AS f ON l."sourcefile" = f."id"'
                ' ORDER BY m."id"').fetchall()
        except sqlite3.DatabaseError as err:
            raise CliError('failed to read mutmut cache %s: %s' % (path, err))
    finally:
        conn.close()
    if version_row is not None and version_row[0] is not None:
        raw_version = str(version_row[0]).strip()
        if raw_version != str(CACHE_DB_VERSION):
            warn('mutmut cache version %s differs from the supported version %d; '
                 'parsing may be inaccurate (%s)' % (raw_version, CACHE_DB_VERSION, path))
    if len(rows) != total:
        raise CliError('broken mutmut cache: %d of %d mutants have no line/sourcefile rows (%s)'
                       % (total - len(rows), total, path))
    entries = []
    stats = {'total': total, 'killed': 0, 'timeout': 0}
    for cache_id, status_raw, line_number, line_text, filename in rows:
        status = CACHE_STATUS_WORDS.get(status_raw) if isinstance(status_raw, str) else None
        if status is None:
            raise CliError('unknown mutmut cache status %r for mutant %s (expected one of %s) (%s)'
                           % (status_raw, cache_id, ', '.join(sorted(CACHE_STATUS_WORDS)), path))
        if status == 'Killed':
            stats['killed'] += 1
        elif status == 'Timeout':
            stats['timeout'] += 1
        if status not in EXTRACTED_STATUSES:
            continue
        if not isinstance(line_number, int) or isinstance(line_number, bool) or line_number < 0:
            raise CliError('mutmut cache line_number must be an integer >= 0, got %r for mutant %s (%s)'
                           % (line_number, cache_id, path))
        entries.append({
            'cache_id': cache_id,
            'status': status,
            'file': normalize_path(filename, path),
            'line': line_number + 1,
            'source_line': line_text if isinstance(line_text, str) else ''
        })
    return entries, stats


def pair_cache_entries(entries, show_path, source_path):
    """把缓存存活条目配对到 --show 文本的 diff 块并构造 mutant。

    "# mutant <id>" 标记按缓存 mutant id 精确认领（mutmut show all
    口径，同 file+line 的多个变异体也能区分）；无标记的纯 `mutmut show`
    输出按 file+line 回退配对。带标记的块只按 id 认领，避免把 killed
    变异体的 diff 误配给同行存活者；缺配对的条目整体报错退出，落单块
    打警告忽略。
    """
    if not entries:
        return []
    if not show_path:
        listing = '; '.join('mutant %s at %s:%s' % (entry['cache_id'], entry['file'], entry['line'])
                            for entry in entries)
        raise CliError('survived/suspicious mutants in the cache carry no replaced fragments; '
                       'pass the "mutmut show" output via --show '
                       '(e.g. `mutmut show all > show.txt`); missing: %s (%s)'
                       % (listing, source_path))
    marked_blocks = parse_diff_blocks(read_text_file(show_path, 'show output'),
                                      source_path, collect_markers=True)
    by_id = {}
    by_pos = {}
    for marker, block in marked_blocks:
        if marker is not None:
            by_id.setdefault(marker, []).append(block)
        else:
            by_pos.setdefault((block['file'], block['line']), []).append(block)
    mutants = []
    missing = []
    for entry in entries:
        block = None
        id_queue = by_id.get(entry['cache_id'])
        if id_queue:
            block = id_queue.pop(0)
        else:
            pos_queue = by_pos.get((entry['file'], entry['line']))
            if pos_queue:
                block = pos_queue.pop(0)
        if block is None:
            missing.append('mutant %s at %s:%s' % (entry['cache_id'], entry['file'], entry['line']))
            continue
        if block['file'] != entry['file'] or block['line'] != entry['line']:
            warn('show diff header %s:%s disagrees with cache entry mutant %s at %s:%s; '
                 'using the cache location (%s)' % (block['file'], block['line'], entry['cache_id'],
                                                    entry['file'], entry['line'], source_path))
            block['file'] = entry['file']
            block['line'] = entry['line']
        mutants.append(mutant_from_block(block, entry['status'], source_path))
    if missing:
        commands = ', '.join('"mutmut show %s"' % item.split()[1] for item in missing)
        raise CliError('survived/suspicious mutants in the cache have no matching diff in the '
                       'show output: %s; run %s and pass the output via --show (%s)'
                       % ('; '.join(missing), commands, source_path))
    for cache_id, queue in by_id.items():
        for block in queue:
            warn('ignoring show diff marked "# mutant %s": not a survived/suspicious mutant '
                 'in the cache (%s)' % (cache_id, source_path))
    for (file_path, line), queue in by_pos.items():
        for block in queue:
            warn('ignoring show diff for %s:%s: no survived/suspicious cache entry at that '
                 'location (%s)' % (file_path, line, source_path))
    return mutants


def looks_like_mutmut_export(data, source_path):
    """识别 mutmut 结果导出：至少一个已知类别是数组；未知类别数组报错（§5.3）。"""
    if not isinstance(data, dict):
        return False
    saw_category = False
    for key, value in data.items():
        if key in EXPORT_KEYS:
            if not isinstance(value, list):
                raise CliError('mutmut export category "%s" must be an array, got %s (%s)' % (key, type(value).__name__, source_path))
            saw_category = True
        elif isinstance(value, list):
            raise CliError('unknown mutmut status category "%s" in export (expected one of %s) (%s)'
                           % (key, ', '.join(EXPORT_KEYS), source_path))
    return saw_category


def extract_entry_diff(item, source_path):
    """解析富条目的 diff 字段：必须恰含一个 diff 块。"""
    diff_text = item.get('diff')
    if not isinstance(diff_text, str) or diff_text.strip() == '':
        raise CliError('export entry diff must be a non-empty string (%s)' % source_path)
    blocks = parse_diff_blocks(diff_text, source_path)
    if len(blocks) != 1:
        raise CliError('export entry diff must contain exactly one diff block, got %d (%s)' % (len(blocks), source_path))
    return blocks[0]


def build_export_candidate(item, status, source_path):
    """把 survived/suspicious 导出条目转成统一 mutant（片段必填）。"""
    if isinstance(item, str):
        raise CliError('survived/suspicious export entry %r carries no replaced-fragment data; '
                       'use objects like {"file", "line", "original", "mutated"} or {"file", "line", "diff"} '
                       '(plain location strings cannot satisfy the unified format) (%s)' % (item, source_path))
    if not isinstance(item, dict):
        raise CliError('survived/suspicious export entry must be a string location or an object, got %s (%s)'
                       % (type(item).__name__, source_path))
    file_path = normalize_path(item.get('file'), source_path)
    line = item.get('line')
    if 'original' in item or 'mutated' in item:
        column = item.get('column')
        if column is not None and (not isinstance(column, int) or isinstance(column, bool) or column < 1):
            raise CliError('export entry column must be an integer >= 1, got %r for "%s" (%s)' % (column, file_path, source_path))
        return build_mutant(file_path, line, column if column is not None else 1,
                            item.get('original'), item.get('mutated'), status, source_path)
    if 'diff' in item:
        block = extract_entry_diff(item, source_path)
        if block['file'] != file_path:
            warn('export entry file %s disagrees with diff header %s; using the entry file' % (file_path, block['file']))
        return build_mutant(file_path, line if line is not None else block['line'], block['column'],
                            block['original'], block['mutated'], status, source_path)
    raise CliError('survived/suspicious export entry for "%s" needs "original"+"mutated" or "diff" fields (%s)'
                   % (file_path, source_path))


def parse_json_export(data, source_path):
    """解析 mutmut 结果导出 JSON：全类别计数，survived/suspicious 富条目转 mutant。"""
    stats = {'total': 0, 'killed': 0, 'timeout': 0}
    mutants = []
    for key in EXPORT_KEYS:
        value = data.get(key)
        if not isinstance(value, list):
            continue
        stats['total'] += len(value)
        if key == 'killed':
            stats['killed'] = len(value)
        elif key == 'timeout':
            stats['timeout'] = len(value)
        if key in ('survived', 'suspicious'):
            status = STATUS_WORDS[key]
            for item in value:
                mutants.append(build_export_candidate(item, status, source_path))
    return mutants, stats, True


def pick_explicit_score(data, source_path):
    """从导出对象挑显式分数（metrics.mutationScore → mutationScore → score）。"""
    if not isinstance(data, dict):
        return None
    metrics = data.get('metrics')
    candidates = []
    if isinstance(metrics, dict):
        candidates.append(metrics.get('mutationScore'))
    candidates.append(data.get('mutationScore'))
    candidates.append(data.get('score'))
    for candidate in candidates:
        if candidate is not None:
            if isinstance(candidate, bool) or not isinstance(candidate, (int, float)) \
                    or not math.isfinite(candidate) or candidate < 0 or candidate > 100:
                raise CliError('mutmut export explicit score must be a number in [0, 100], got %r (%s)'
                               % (candidate, source_path))
            return candidate
    return None


def resolve_score(data, stats, has_summary, source_path):
    """显式分数原样记录；否则按检出口径计算；无统计节时省略（返回 None）。"""
    explicit = pick_explicit_score(data, source_path)
    if explicit is not None:
        return explicit
    if not has_summary:
        return None
    if stats['total'] == 0:
        return 100
    return round2((stats['killed'] + stats['timeout']) / stats['total'] * 100.0)


def assemble_report(mutants, score):
    """按契约 §3.5 排序并从 1 起编号 id，组装统一报告（字段顺序与 §2 一致）。"""
    ordered = sorted(mutants, key=lambda m: (m['file'], m['line'], m['column']))
    sorted_mutants = []
    for index, mutant in enumerate(ordered, 1):
        sorted_mutants.append({
            'id': 'mutmut-%d' % index,
            'file': mutant['file'],
            'line': mutant['line'],
            'column': mutant['column'],
            'mutationType': mutant['mutationType'],
            'original': mutant['original'],
            'mutated': mutant['mutated'],
            'status': mutant['status']
        })
    report = {
        'tool': 'mutmut',
        'timestamp': iso_timestamp_utc(),
        'mutants': sorted_mutants
    }
    if score is not None:
        report['score'] = score
    return report


def render_summary_line(report, output_path):
    return 'parse_mutmut_report: survived=%d suspicious=%d score=%s wrote %s' % (
        sum(1 for m in report['mutants'] if m['status'] == 'Survived'),
        sum(1 for m in report['mutants'] if m['status'] == 'Suspicious'),
        report.get('score', 'n/a'),
        output_path
    )


def print_help():
    lines = [
        'Usage: python scripts/parse_mutmut_report.py --input <path> [options]',
        '',
        'Parse mutmut output (text capture, results-export JSON, or the native',
        '.mutmut-cache SQLite file), keep the mutants with status Survived or',
        'Suspicious, and convert them to the unified mutation report format',
        '(docs/formats/unified-mutation-report.md, contract v1.1).',
        '',
        'Options:',
        '  --input <path>     Path to the mutmut capture, results-export JSON, or',
        '                     .mutmut-cache SQLite file (required)',
        '  --show <path>      Text file holding "mutmut show" outputs (unified diffs,',
        '                     optionally preceded by "# mutant <id>" markers); required',
        '                     with a .mutmut-cache input to fill original/mutated',
        '  --output <path>    Write the unified report JSON to this file (default: stdout)',
        '  -h, --help         Show this help and exit',
        '',
        'Accepted input shapes (auto-detected):',
        '  1. Text capture: the output of `mutmut results` (category sections such as',
        '     "Survived (1)" with "<path>.py:<line> - Mutation <n>" entries) followed by',
        '     the `mutmut show` diff blocks for the survived/suspicious mutants',
        '     (unified diff: "--- <path>", "+++ <path>", "@@ ... @@"). Progress lines',
        '     and other noise are ignored. Every survived/suspicious entry needs a diff',
        '     block matched by file and line, otherwise parsing fails with exit code 1.',
        '  2. mutmut results-export JSON:',
        '     { "killed": [...], "survived": [...], "timeout": [...], "suspicious": [...],',
        '       "untested": [...], "skipped": [...] }',
        '     Entries of killed/timeout/untested/skipped/excluded categories are only',
        '     counted. Survived/suspicious entries must be objects carrying the replaced',
        '     fragments:',
        '       {"file": "src/a.py", "line": 4, "original": "<=", "mutated": "<"}',
        '       {"file": "src/a.py", "line": 4, "diff": "--- src/a.py\\n+++ ..."}',
        '     Plain string entries carry no fragment data and are rejected (exit code 1).',
        '  3. mutmut 2.x SQLite cache (.mutmut-cache), auto-detected by the SQLite file',
        '     header and opened read-only. The cache is the authoritative source for',
        '     mutant ids, statuses (ok_killed, bad_survived, bad_timeout, ok_suspicious,',
        '     skipped, untested), file paths, and 0-based line numbers (converted to',
        '     1-based in the output), but it does NOT store the replaced fragments.',
        '     Survived/suspicious mutants therefore need their "mutmut show" diffs via',
        '     --show: the output of `mutmut show all` is matched exactly by its',
        '     "# mutant <id>" markers (safe when several mutants share one line);',
        '     concatenated `mutmut show <id>` output without markers is matched by file',
        '     and line. Survivors without a matching diff fail with exit code 1 and list',
        '     the "mutmut show <id>" commands to run.',
        '     Version note: in mutmut 2.x the results command takes no flags; capture',
        '     the diffs with `mutmut show all` (or `mutmut show <file>`). mutmut 3.x',
        '     no longer writes the .mutmut-cache file this parser reads.',
        '',
        'Output:',
        '  Unified report JSON (UTF-8, LF, 2-space indent):',
        '  { tool: "mutmut", timestamp: ISO-8601 UTC, mutants: [...], score: <0-100> }',
        '  mutant fields: id ("mutmut-<sequence>"), file, line, column, mutationType,',
        '  original, mutated, status ("Survived" or "Suspicious"). Sorted by file, then',
        '  line, then column; ids are sequential in that order and are not stable across',
        '  runs. With --output the JSON goes to the file and stdout carries a summary line.',
        '',
        'Score semantics:',
        '  An explicit export score (metrics.mutationScore, or top-level',
        '  mutationScore/score) is preserved verbatim; otherwise',
        '  score = round2((killed + timeout) / total * 100) (Timeout counts as detected,',
        '  Suspicious does not). In text captures the section header counts (e.g.',
        '  "Killed (9) Survived (1)") are the authoritative run statistics for the',
        '  score; entry lines are only counted when no header carries a count. For a',
        '  .mutmut-cache input the score is computed from the full cache counts',
        '  (killed = ok_killed, timeout = bad_timeout, total = all mutants). An',
        '  empty mutation range scores 100. Show-only diff captures carry no run',
        '  statistics, so the optional score field is omitted.',
        '',
        'Exit codes:',
        '  0  success (including an empty survivors list)',
        '  1  user error: bad arguments, missing file, invalid JSON, input that is not',
        '     mutmut output, survived/suspicious entries without diff fragments, unknown',
        '     status categories, broken or foreign SQLite caches, inconsistent fragments'
    ]
    write_out('\n'.join(lines) + '\n')


def main(argv):
    args = parse_args(argv)
    if args['help']:
        print_help()
        return 0
    if not args['input']:
        write_err('Error: --input <mutmut-output> is required\n')
        write_err('Usage: python scripts/parse_mutmut_report.py --input <path> [--show <path>] [--output <path>]\n')
        write_err('Run with --help for details.\n')
        return 1
    raw = read_binary_file(args['input'], 'mutmut output')
    is_cache = raw.startswith(SQLITE_MAGIC)
    if args['show'] and not is_cache:
        raise CliError('--show is only used when --input is a mutmut SQLite cache (.mutmut-cache) (%s)'
                       % args['input'])
    if is_cache:
        entries, stats = read_mutmut_cache(args['input'])
        mutants = pair_cache_entries(entries, args['show'], args['input'])
        score = resolve_score(None, stats, True, args['input'])
    else:
        text = decode_text(raw, args['input'])
        if text.lstrip().startswith('{'):
            data = parse_json_text(text, args['input'])
            if not looks_like_mutmut_export(data, args['input']):
                raise CliError('mutmut report format not recognized: expected a results-export object '
                               'with category arrays {"killed": [...], "survived": [...], ...} (%s)' % args['input'])
            mutants, stats, has_summary = parse_json_export(data, args['input'])
            score = resolve_score(data, stats, has_summary, args['input'])
        else:
            mutants, stats, has_summary = parse_text_capture(text, args['input'])
            score = resolve_score(None, stats, has_summary, args['input'])
    report = assemble_report(mutants, score)
    text = json.dumps(report, ensure_ascii=False, indent=2) + '\n'
    if args['output']:
        try:
            with open(args['output'], 'wb') as handle:
                handle.write(text.encode('utf-8'))
        except OSError as err:
            raise CliError('failed to write output file %s: %s' % (args['output'], err))
        write_out(render_summary_line(report, args['output']) + '\n')
    else:
        write_out(text)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv[1:]))
    except CliError as err:
        write_err('Error: %s\n' % err)
        sys.exit(1)
    except Exception as err:  # noqa: BLE001 - 非 CliError 兜底，保持退出码契约
        write_err('Error: %s: %s\n' % (type(err).__name__, err))
        sys.exit(1)
