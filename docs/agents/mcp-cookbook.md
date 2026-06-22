# MCP 代码探索 Cookbook（最终版 v7）

> 跨代码库实测总结。涵盖 4 个 MCP 共 18 个工具函数，经 4 个项目（Rust / Python / TypeScript / 混合）约 15 轮评测验证。
> 本版本已收敛，去除具体项目名称，只保留通用结论。
>
> 本仓库（hr-certflow）是验证样本之一：Python 后端 + TypeScript/React 前端，51,812 LOC，2,130 索引节点，6,952 边。

---

## 通用工作流

接手一个新任务时，按这个顺序走：

```
1. get_architecture(aspects=['all'])
   → 快速了解项目结构、热点、入口点、语言分布、聚类
   ⚠️ 大项目用 aspect 子集（["hotspots"] 等）省 token

2. fast_context_search("功能描述（中文/英文均可）")
   → 定位相关文件

3. codegraph_callers("核心函数")  或  trace_path("核心函数", risk_labels:true)
   → 看调用关系 + 影响面
   ⚠️ 公共服务函数（无 _ 前缀）callers 若为空，用 codegraph_explore 交叉验证

4. query_graph("MATCH (n:Function) WHERE n.complexity > 10 ...")
   → 找复杂函数（重构候选）
   ⚠️ 用 Function 而非 Method；混合项目 Method + Function 双查

5. get_code_snippet(qualified_name, include_neighbors: true)
   → 看具体符号的 25+ 个静态指标 + caller/callee 名称

6. search_code("确定的关键词", regex: true) 或 rg 兜底
   → 全文搜索验证
   ⚠️ 需要正则务必传 regex=true；context:N 获取源码上下文
```

---

## 一、fast_context_search（语义定位）

**核心能力**：语义理解、中文查询、跨层追踪、模糊兜底。

| 能力 | 评级 | 说明 |
|------|------|------|
| 语义定位（概念→文件） | ★★★★★ | 中文/英文均精准，即使查询词没出现在符号名中 |
| 跨层追踪（UI→后端） | ★★★★★ | 大项目（>100K 行）可能需分前后端两次查询 |
| 模糊语义/中文兜底 | ★★★★★ | 不可替代——其他工具做不到语义理解 |
| 空结果 | 正确行为 | 返回 "No relevant files" 不一定是 bug，可能代码库确实无对应概念 |

---

## 二、codegraph（调用图 + 符号索引）

### 2.1 codegraph_search —— 符号搜索

**kind 支持矩阵**：

| kind | Rust | Python | TS/React | 备注 |
|------|------|--------|----------|------|
| `function` | ✅ | ✅ | ✅ | 通用 |
| `method` | ✅ | ✅ | ✅ | 通用 |
| `class` | ✅ | ✅ | ✅ | 通用（struct/class） |
| `enum` | ✅ | ❌ | ❌ | |
| `interface` | ⚠️ | ✅ | ✅ | Rust trait 效果差 |
| `route` | ⚠️ 项目相关 | ⚠️ 项目相关 | ⚠️ 项目相关 | 部分项目可用（路径片段查询），不稳定。替代：search_graph(label:"Route") 或 get_architecture 的 routes |
| `type` | ❌ | ❌ | ✅ | TS type_alias 被索引 |
| `component` | ❌ | ❌ | ❌ | 均不支持（React 组件识别为 Function） |
| `variable` | ✅ | ✅ | ✅ | |

### 2.2 codegraph_callers —— 精确调用者

- ✅ 重名方法自动分组（提示 "N distinct definitions, narrow with file"）
- ⚠️ 可能漏报测试调用——影响面分析用 trace_path(include_tests:true)，精确行号用 codegraph_callers
- ⚠️ 公共服务函数（无 `_` 前缀）可能因 LSP 解析间隙返回 0 callers（大项目更易触发）——用 codegraph_explore 交叉验证

### 2.3 codegraph_node —— 符号 + 文件读取

- ✅ 大文件符号化：TSX 2000+ 行 → 100+ 符号；Rust 900+ 行 → 90+；Python 1500+ 行 → 45-55
- ✅ 单符号：源码 + signature + Trail（谁调我 + 我调谁）
- ❌ `__init__.py` / `mod.rs` / `index.ts` 等纯导出文件返回 0 或近 0（含 `__all__` 时 1 个 Variable）

### 2.4 codegraph_explore —— 重构影响面

- ✅ blast radius + 源码一站式输出（重构首选）
- ✅ 不依赖 CALLS 边索引，基于源码启发式，最可靠
- ❌ 测试覆盖标注不可信（按符号名匹配，行为驱动命名会被误报）

---

## 三、codebase-memory（图数据库 + 静态分析）

### 3.0 前置准备

```
index_repository(repo_path: "<路径>", mode: "moderate")
index_status(project: "<项目名>")
get_graph_schema(project: "<项目名>")
```

### 3.1 get_architecture —— 项目全景

- ✅ 节点数/边数/语言分布/热点/聚类/入口点/路由
- 💡 **aspect 子集省 token**：`["hotspots"]`/`["clusters"]`/`["routes"]` 等有效，未知 aspect 优雅降级

### 3.2 get_code_snippet —— 符号静态指标（25+ 字段）

必含：`complexity`, `cognitive`, `loop_count`, `loop_depth`, `param_count`, `max_access_depth`, `callers`, `callees`, `lines`, `is_exported`, `signature`, `return_type`, `parent_class`, `fp`, `sp`, `bt`

**include_neighbors 参数（重要）**：
- 默认/false：返回 `callers`/`callees` **计数**（数字）
- `include_neighbors=true`：**添加** `caller_names`/`callee_names` **名称数组**
- **需要看依赖名称时传 `include_neighbors=true`**

### 3.3 search_graph —— 语义排名搜索

- ✅ `query`（BM25 全文搜索）：精准排名，始终可靠
- ✅ `label` / `include_connected` / `exclude_entry_points` / `qn_pattern`：有效过滤器
- ❌ `min_degree` / `max_degree` / `relationship`：**被静默忽略**，用 Cypher WHERE 替代
- ❌ `semantic_query`：**results 字段全库 bug**（任何关键词都返回全库）。`semantic_results` 子字段项目相关（有的项目有，有的无）。**最稳妥用 `query`（BM25）**

### 3.4 query_graph —— Cypher 图查询

**支持的 Cypher 特性**：
- ✅ `DISTINCT`, `CONTAINS`, `STARTS WITH`, `ENDS WITH`, `toUpper()`, `IN [...]`
- ✅ `count()`, `sum()`, `max()`, `min()`, `collect()`（⚠️ collect() 输出被 CSV 截断）
- ✅ 隐式 `GROUP BY`, `SKIP ... LIMIT`, `ORDER BY`, `AND`, 范围 `>= <=`
- ✅ 变长 `*1..2`, 多跳链式 `(a)->(b)->(c)`
- ✅ `type(r)`（非聚合时正常返回字符串）
- ✅ 布尔比较 `WHERE n.x = true`（⚠️ **不支持简写** `WHERE n.x`——报错）

**不支持的 Cypher 特性**：
- ❌ `MATCH path=...`（路径变量，报错 `expected token type 66`）
- ❌ `WITH` 子句（静默丢结果）
- ❌ 反向遍历 `<-[:TYPE]-`（**项目相关**——部分项目支持，遇到报错改用正向写法）
- ⚠️ `!=` / `<>`：**字段 vs 字面量正常**（`n.x <> 'literal'`）；**字段 vs 字段项目相关**（部分项目失败）
- ⚠️ `type(r)` 与聚合函数同时使用时返回数字而非字符串

**最有价值的 Cypher 查询**（找重构候选）：
```cypher
MATCH (n:Function) WHERE n.complexity > 10
RETURN n.name, n.complexity, n.file_path ORDER BY n.complexity DESC LIMIT 10
```

### 3.5 trace_path —— 调用链追踪

- ✅ `calls` inbound/outbound + `risk_labels`（标注 CRITICAL）
- ✅ `include_tests:true` 包含测试中的调用
- ✅ `data_flow` 模式比 calls 更丰富（但可能混入同名不同语义的路径）
- ❌ `parameter_name` 参数**被静默忽略**（未实现参数级过滤）

### 3.6 search_code —— 文本搜索

**regex 参数（重要）**：
- 默认 `regex=false`：**纯字面量搜索**（`.`/`\b`/`\s` 等当字面字符）
- 传 `regex=true`：**完整 PCRE**（`.*`/`\w+`/`\d{4}`/`[a-z]+`/`^import`/`|` 全部支持）
- 工具遇 `|` 且 `regex=false` 时**主动警告**："Pass regex=true for 'foo|bar'"
- **需要正则务必传 `regex=true`**

**其他参数**：
- ✅ `context:N`：返回匹配点前后 N 行源码 + `context_start` 行号（**最有价值的模式**）
- ✅ `limit:N`：限制 results 数组大小，`total_results` 报全量；`limit:0` 返回空数组但 directories 仍填充
- ✅ `mode:files`：只看文件列表
- ❌ 无 `offset`（文档明确）

**dedup 陷阱**：`search_code` 有去重合并，`total_results` ≠ 原始匹配数。已知最高 **8.3x**（`from app` 982→119）。与模式文本量负相关（短模式 dedup 更激进）。`total_grep_matches` 有 500 上限截断。精确计数用 `rg -c`。

**跨语言特殊符号**：
- Rust：`#[test]`/`derive(`/`pub(crate)`/`cfg(` → ❌ 全崩，用 rg
- Python：`@staticmethod`/`@router`/`@app` → ✅ 正常
- TypeScript：`"use client"`/`@/`/`import.*from` → ✅ 正常（需 `regex=true`）

### 3.7 高级功能

| 功能 | 状态 | 说明 |
|------|------|------|
| `detect_changes` | ⚠️ 条件性 | 冷启动可能返回 0（全新首次索引无基线）。`scope`/`depth` 参数被接受但不解决冷启动 |
| `manage_adr` | ✅ | 正常读取/写入 |
| `ingest_traces` | ❌ 未实现 | 返回 `{status:'accepted', note:'not yet implemented'}`。监控脚本勿匹配旧字符串 |

### 3.8 高级特性（杀手级功能）

**💡 SIMILAR_TO 边（重构利器）**：
- Jaccard 相似度识别**几乎相同**的节点对（阈值 ≥0.95）
- 用于发现并行实现/重复代码/重构候选
- 测试文件内也有效（识别重复测试模式）
- ❌ 不适合松散相似性——后者用 search_graph query 或 fast_context

**💡 FILE_CHANGES_WITH 边**：
- coupling_score 支持变更影响分析

**💡 Route 节点**：
- `source` 三类：`decorator`（真实路由）、`""`（infra）、`infra`（compose 变量）
- 用 `WHERE r.source='decorator'` 过滤
- 装饰器 Route `start_line=0, end_line=0`，通过 DECORATES 边关联 Function（部分项目无此边）

**⚠️ is_test 字段不可信**：
- Function 节点上**全部为 false**（即使函数名明显是 `test_*`）
- `is_test=true` 只标记 Module（测试文件本身），不标记 Function
- 过滤测试代码用 `file_path CONTAINS 'tests/'` 或 `name STARTS WITH 'test_'`

---

## 四、rg 兜底命令（MCP 不可用时保命）

```bash
# Rust 特殊符号
rg -n "#\[test\]|#\[derive" --type rust src/
rg -n "pub\(crate\) (mod|use)" --type rust src/

# Python
rg -n "@router\.(get|post)" --type py backend/
rg -c "@staticmethod" --type py .

# TypeScript
rg -n "\"use client\"" --type tsx frontend/

# 计数（search_code dedup 后的验证）
rg -c "someFunction" src/ | awk -F: '{s+=$2} END {print s}'

# 导出分析
rg -n "^(pub|pub\(|pub use)" src/**/mod.rs
rg -n "^(from|import)" src/**/__init__.py

# 测试函数统计
rg -c "#\[test\]" --type rust src/ | wc -l
rg -c "def test_" --type py tests/ | wc -l
```

---

## 五、陷阱速查表

### 高影响陷阱（日常使用必须知道）

| # | 陷阱 | 应对 |
|---|------|------|
| 1 | `search_code` 默认 `regex=false` 是字面量搜索 | **需要正则务必传 `regex=true`** |
| 2 | `get_code_snippet` 默认不返回 caller/callee 名称 | 传 `include_neighbors=true` 获取名称数组 |
| 3 | `semantic_query` results 字段全库 bug | 用 `query`（BM25）替代 |
| 4 | `is_test` 字段在 Function 上全 false | 用 `file_path` 或 `name` 前缀过滤测试代码 |
| 5 | 公共服务函数 callers 可能为空（LSP 间隙） | 用 `codegraph_explore` 交叉验证 |
| 6 | `codegraph_explore` 测试覆盖标注不可信 | 用 `rg -c "#\[test\]"` 或 `def test_` 实数 |
| 7 | `search_code` dedup 最高 8.3x | 精确计数用 `rg -c` |
| 8 | `__init__.py`/`mod.rs` 返回 0 符号 | 用 rg 看导出 |

### Cypher 限制速查

| 特性 | 状态 |
|------|------|
| `path=` 变量 | ❌ 所有项目失败 |
| `WITH` 子句 | ❌ 静默丢结果 |
| 布尔简写 `WHERE n.x` | ❌ 报错，必须 `= true` |
| `type(r)` + 聚合 | ⚠️ 返回数字非字符串 |
| 反向遍历 `<-[:]-` | ⚠️ 项目相关 |
| `!=`/`<>` 字段 vs 字段 | ⚠️ 项目相关 |
| `!=`/`<>` 字段 vs 字面量 | ✅ 正常 |
| `DISTINCT`/`CONTAINS`/`STARTS WITH`/`ENDS WITH`/`IN` | ✅ |
| `GROUP BY`/`count`/`sum`/`max`/`min`/`SKIP LIMIT` | ✅ |

### 条件性陷阱（项目相关，遇到时实测）

| 陷阱 | 触发条件 |
|------|---------|
| C2-revised LSP 公共服务间隙 | 大项目 + 公共服务函数（无 `_` 前缀） |
| C5 反向遍历 | 部分项目支持，部分报错 |
| N14 字段 vs 字段不等比较 | 部分项目失败 |
| `semantic_results` 子字段 | 部分项目有，部分无 |
| `route` kind | 项目相关，部分可用部分不可用 |
| `detect_changes` 冷启动 | 全新首次索引返回 0 |

---

## 六、每次新代码库必须验证的事项

```
□ codegraph_search 支持哪些 kind（语言差异）
□ search_code 需要正则时传 regex=true
□ search_code context:N 获取源码上下文（最有价值模式）
□ search_code dedup 上限（已知最高 8.3x），精确计数用 rg -c
□ semantic_query 用 query（BM25），不用 semantic_query
□ codegraph_node 对 __init__.py 返回空或近空
□ get_code_snippet include_neighbors=true 获取名称数组
□ get_architecture aspect 子集省 token
□ React/TSX 项目：query_graph 查 Function 而非 Method
□ 混合语言项目：query_graph Method + Function 双查
□ Python 项目业务方法多索引为 Function
□ 公共服务函数 callers 若为空，用 codegraph_explore 交叉验证
□ is_test 字段不可信，过滤测试用 file_path 或 name 前缀
□ Cypher 不用 path= 变量 / WITH 子句 / 布尔简写
□ SIMILAR_TO 找重复/并行结构（重构利器）
```

---

## 附录：一句话总结

```
fast_context     = "这个概念在哪"   → 语义理解，不可替代
codegraph        = "谁调用谁"       → 调用图 + 符号化，不可替代
codebase-memory  = "静态指标 + 全景" → 图数据库 + 25 个维度，不可替代
rg               = "文本在哪"       → 兜底线，不可替代（特殊符号/计数/mod.rs）
```

### 18 个工具索引

| 工具 | 所属 | 一句话用途 |
|------|------|-----------|
| `fast_context_search` | fast_context | 语义定位：概念→文件、中文、跨层追踪 |
| `codegraph_search` | codegraph | 按 kind 搜符号 |
| `codegraph_callers` | codegraph | 精确调用者（注意漏报测试） |
| `codegraph_node` | codegraph | 读符号源码 + Trail，大文件符号化 |
| `codegraph_explore` | codegraph | blast radius + 源码一站式（重构首选，最可靠） |
| `index_repository` | codebase-memory | 索引仓库 |
| `index_status` | codebase-memory | 确认索引状态 |
| `list_projects` | codebase-memory | 查看已索引项目 |
| `get_graph_schema` | codebase-memory | 查看图数据模型 |
| `get_architecture` | codebase-memory | 项目全景：热点/聚类/路由（支持 aspect 子集） |
| `get_code_snippet` | codebase-memory | 25+ 静态指标（传 include_neighbors=true 获取名称） |
| `search_graph` | codebase-memory | BM25 语义排名搜索（用 query，不用 semantic_query） |
| `query_graph` | codebase-memory | Cypher 图查询（限制见速查表） |
| `trace_path` | codebase-memory | 调用链 + hop 深度 + risk 标签 |
| `search_code` | codebase-memory | 文本搜索（regex=true 解锁 PCRE，context:N 最有价值） |
| `detect_changes` | codebase-memory | Git diff（冷启动可能 0） |
| `manage_adr` | codebase-memory | 架构决策记录 |
| `ingest_traces` | codebase-memory | 运行时追踪（未实现） |
