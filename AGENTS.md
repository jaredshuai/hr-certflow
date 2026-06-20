# HR CertFlow Agent Guide

HR CertFlow is the internal HR certificate lifecycle system of record. Future
work in this repository must optimize for a complete day-to-day HR operations
product, not an MVP/demo, AI showcase, or one-off script workflow.

## Hard Boundaries

- Work only inside `D:\codespace\hr-certflow` unless the user explicitly names
  another path.
- Do not modify `D:\infra` or deployment infrastructure by hand unless the user
  explicitly asks.
- Do not output secrets, kubeconfigs, Redis URLs, passwords, tokens, signed
  URLs, or infra credentials.
- Preserve dirty worktrees. Never reset, checkout, or discard unrelated changes.
- Keep business truth in FastAPI/PostgreSQL.
- Treat Dify only as an AI extraction provider. Dify must not own review state,
  certificate state, reminder state, audit state, or workflow decisions.
- Treat object storage as S3-compatible; do not hard-code production behavior to
  one vendor.
- Keep Paperless-ngx, RAGFlow, n8n, and Temporal outside the core product path
  unless explicitly requested.

## Runtime Rules

- Also follow `C:\Users\jared\.codex\RTK.md` when running shell commands in
  this workspace.
- Prefix shell commands with `rtk` when available so long outputs are filtered
  before they enter the agent context. If a tool wrapper cannot execute through
  `rtk`, use the wrapper normally and keep output scoped.
- Use Conventional Commits for git commit messages, for example
  `feat: add certificate expiry drill-down`, `fix: persist failed extraction
  status`, or `docs: update release evidence checklist`.

## Product North Star

- `docs/delivery-north-star.md` is the final complete-product contract.
- `docs/delivery-gap-register.md` is the active gap checklist. If it conflicts
  with the North Star, correct the gap register.
- Do not describe the target as an MVP. Older MVP wording is historical scaffold
  context only.
- The product is not complete until HR can operate the full loop without
  developer intervention: employee/type management, upload confirmation, Dify
  extraction, human review, formal certificate ledger, replacement history,
  reminder simulation/dispatch, feedback closure, dashboard drill-down, reports,
  exports, and audit traceability.
- Local implementation is not enough for North Star completion. Completion also
  requires promoted dev/release evidence through the existing GitHub
  Actions/GitOps path, including Web/API smoke, Celery/Redis smoke, and an
  end-to-end HR scenario.

## Product Rules

- HR review is required before AI output becomes formal certificate data.
- New certificates replace old records by status/linkage, not by destructive
  overwrite.
- State changes that affect HR decisions must be auditable.
- Failed states must be persisted, visible, and recoverable through the product
  workflow.
- Dashboard/report numbers must come from FastAPI/PostgreSQL business state and
  drill down to source records; do not use frontend-only approximations for
  business truth.
- Visible coworker-facing UI copy should be Chinese.
- Technical URL slugs, route IDs, component names, and internal identifiers
  should stay ASCII/English unless there is a strong reason otherwise.

## Preferred Implementation Shape

- Backend: FastAPI, SQLAlchemy 2.x, Pydantic v2, Celery.
- Frontend: Ant Design Pro / Umi Max, AntD, and ProComponents.
- Data visualization: use AntV for charts and dashboard visuals.
- Prefer mature library glue over handwritten UI/state plumbing:
  ProTable/ProList for data operations, ModalForm/DrawerForm/Steps/Result/Alert
  for workflows, AntD App/message APIs for feedback, and AntV for charts.
- Do not add a new dependency when an existing AntD/ProComponents/AntV capability
  solves the problem cleanly.
- Keep custom code focused on business mapping, validation, API integration, and
  audit/trace behavior.

## Release And Verification

- Dev/release deployment must continue through the existing GitHub Actions and
  GitOps workflows. Do not manually patch infra or GitOps output to simulate a
  release.
- For backend changes, prefer running:

```bash
rtk uv sync --project backend --extra dev
rtk uv run --project backend --extra dev ruff check backend/app backend/tests backend/migrations scripts
rtk uv run --project backend --extra dev ty check backend/app
rtk uv run --project backend --extra dev pytest backend/tests -q
```

- For frontend changes, prefer running:

```bash
cd frontend
rtk npm ci
rtk npm run lint
rtk npm run build
```

- If `DATABASE_URL` is missing, DB-backed pytest cases may skip. Report skipped
  integration coverage honestly and do not treat it as full DB evidence.
- Use `rtk git diff --check` before finalizing broad edits.

<!-- CODEGRAPH_START -->
## CodeGraph And Fast Context Routing

This project has a CodeGraph MCP server (`codegraph_*` tools) configured.
CodeGraph is a tree-sitter-parsed knowledge graph of every symbol, edge, and
file. Use it for deterministic structure. Use `fast-context` for semantic or
intent-based discovery (AI-driven semantic code search that returns file paths
with line ranges and grep keywords). Native file reads are still fine for
literal text, already-known files, or final confirmation.

> The previous `ace-tool` MCP is retired: its relay endpoint
> (`acemcp.heroman.wtf`) is offline and the server is disabled in
> `~/.zcode/cli/config.json`. Default to `fast-context` for semantic discovery.

Use the smallest reliable inspection path. Do not loop through multiple tools
when one specialized tool answers the question.

### Tool Overview

| Tool | Nature | Good at / Bad at |
| --- | --- | --- |
| **CodeGraph** (`codegraph_explore`/`callers`/`node`/`search`; local static symbol graph) | tree-sitter parse → symbol relationship graph, fully local | ✅ symbol relationships, call flows, impact analysis, reading source / ❌ Chinese concept words, pure natural-language intent |
| **Fast Context** (`fast_context_search`; remote AI semantic retrieval) | remote AI locates relevant code by natural-language intent | ✅ fuzzy intent, Chinese concept words, unknown symbol names / ❌ call graphs, reading source (returns file + line range only, no content) |
| **rg** (ripgrep; local text search) | regex / string matching | ✅ finding strings, regex, extension filters, file existence / ❌ semantics, symbol relationships |

### Decision Table By Problem Type (Mandatory)

These rules are keyed to **problem type** and are mandatory — violating them is
an error and must be redone with the correct tool. Do not substitute a default
grep or full-file scan "because it is handy"; measured against the designated
tool they are slower and less accurate.

| What you are doing | Must use | Fallback if unavailable |
| --- | --- | --- |
| **Exact call relationships**: who calls X, what X calls | `codegraph_callers` / `codegraph_callees` | rg for the symbol + Read to infer manually; tell the user you degraded |
| **Concrete symbol name** to trace a flow / impact / refactor (you can name the function or class) | `codegraph_explore` | fast_context to fish for files + Read; tell the user you degraded |
| Reading source of a single **known symbol** | `codegraph_node` (symbol mode) | Read |
| **Pure field name / data field** to find definition and usage (no same-named function in backend) | `fast_context_search` | rg + Read; results may be inaccurate, say so |
| **Chinese business concept / workflow word** (e.g. "user auth flow", "order state machine") | `fast_context_search` | rg + Read; results may be inaccurate, say so |
| **No symbol name at all**, only a fuzzy business description | `fast_context_search` | rg + Read (second best) |
| Find a string, regex match, filter by extension, check whether a file exists | **`rg`** | rg is required on this machine; if unavailable treat it as an environment fault and report it — do **not** fall back |
| Sensitive code / offline scenarios | CodeGraph (fully local) | — |

### Core Rule: Whether To Use `codegraph_explore` Depends On A "Symbol Anchor"

This is the easiest point to get wrong. `codegraph_explore` hit quality
**depends on the query containing a symbol anchor** (a concrete function or
class name):

| Query word type | explore behavior | Use |
| --- | --- | --- |
| Concrete function/class name (e.g. `loginUser`, `OrderService`) | ✅ precise, direct hit | explore |
| Field name **+ backend has a same-named function** (e.g. `risk_level` → `_resolve_risk_level`) | ✅ usually hits | explore |
| Pure field name, backend has **no** same-named function (e.g. pure data field `created_at`) | ❌ easily pulled off by generative client code (e.g. OpenAPI-generated model files) | fast_context |
| Chinese / natural-language concept or workflow word (e.g. "login auth", "export report") | ❌ easily returns "No relevant code found" or gets pulled off by generated artifacts | fast_context |

> **When unsure**: first run `fast_context_search` to fish for files (it hits
> business code reliably across query types); once you have concrete symbol
> names, use `explore` to dig into call relationships. This combo is more
> reliable than betting on a single tool.

### Known Pitfalls (Empirically Verified On This Repo)

- **"Who calls X" is not always a CodeGraph job**: if X is a test function,
  `main`, or a leaf entry point, `codegraph_callers` returns "No callers found"
  (correct, but not what you asked). In that case use rg to find all
  occurrences of X, or fast_context to locate context.
- **Do not re-Read source returned by `explore`**: if a source block returned
  by `explore` is tagged "treat as already Read", use it directly — do not Read
  again, to save tokens. If output is truncated by budget, **re-issue `explore`
  with the specific symbol name** rather than blindly Reading the file.
- **`fast_context` does not do call graphs**: when asked "who calls X" it only
  returns related files — it does not answer the question. Do not use it for
  call relationships.
- **Generative client code is a noise source**: if the project has
  OpenAPI/Orval/tRPC/protobuf-generated client code (e.g. `src/api/model/*`,
  `*.pb.ts`) and it is indexed, `explore` on queries without a symbol anchor
  gets pulled off by them. Such projects must especially follow the split
  above.
- **Windows reserved device-name trap**: `nul`/`con`/`aux`/`prn`/`com1` etc.
  are Win32 reserved device names. `Get-ChildItem -Filter "nul"` will
  **false-positive** match the NUL device in every directory. To check whether
  a file exists use `rg --files -g "<name>"`, `Test-Path`, or
  `Get-ChildItem | Where-Object Name -eq "<name>"` (filter after the pipe, not
  via `-Filter`).

### Use `CodeGraph` For Structural Proof

- Use `CodeGraph` when the question depends on exact syntax or relationships:
  symbol definition, references, implementations, caller/callee chains,
  import/export dependencies, and refactor impact.
- Do not use `CodeGraph` for vague natural-language searches. First locate the
  area semantically or by direct source reading, then use `CodeGraph` on the
  concrete symbols.
- For flow questions, start with `codegraph_trace` instead of manually chaining
  search, callers, and callees.
- For broad context on a known area, prefer `codegraph_context` and then at most
  one focused `codegraph_explore` over many repeated node reads.
- Trust `CodeGraph` for AST-derived relationships. Do not re-verify structural
  answers with grep unless generated files or recent edits may not be indexed.
- If the project has no `.codegraph/` index and the CodeGraph server reports
  "not initialized", ask before running `codegraph init -i`.

### Use `fast-context` For Semantic Location

- Use `fast-context` when the query is about intent rather than a known symbol:
  where a workflow is handled, where a business rule is enforced, how similar
  errors are formatted, or which files likely matter for a feature.
- Do not use `fast-context` as proof for exact call stacks, dependency edges, or
  refactor blast radius.
- Treat semantic/AI output as a locator. Confirm critical behavior in source
  code, tests, or `CodeGraph` before editing.
- Use `fast-context` before outsourcing or starting a large multi-file
  implementation when the task would otherwise be underspecified.
- `fast-context` is tunable: `tree_depth` (1-6) controls how much directory
  structure the remote AI sees (reduce on payload errors, increase for small
  repos), `max_turns` (1-5) controls search rounds, `max_results` (1-30)
  caps returned files, and `exclude_paths` shrinks payload on large repos
  (e.g. `['node_modules', 'dist', '.git']`). Read the `[config]` and
  `[diagnostic]` lines in its response to decide whether to retry with
  different parameters.

### Hybrid Workflow

1. Locate ambiguous feature areas with `fast-context` or direct file inspection.
2. Trace exact symbols, flows, and impact with `CodeGraph` once concrete names
   are known.
3. Edit with source context, then verify with lint, type checks, tests, and
   builds. Do not immediately depend on a graph index that may lag recent file
   writes.

### CodeGraph Maintenance And Known Pitfalls

- Auto-sync is enabled by default. CodeGraph watches the project and updates
  the graph on every file change — while the agent edits code, or files are
  added, modified, or deleted. The index is never stale, and there is nothing
  to re-run.
- For a full rebuild (e.g. after a schema-level restructuring), run
  `codegraph index` manually.
- The index lives in `.codegraph/codegraph.db` (SQLite, WAL mode). The
  `-wal`/`-shm` sidecars are normal; a multi-MB WAL that stops growing is
  healthy, not a sign of corruption. Do not delete them while a `codegraph`
  process is running.
- If `codegraph` reports a stale lock after a crash, run `codegraph unlock`
  to clear it; do not manually delete lock files.
- `codegraph query <term>` relevance scores can display oddly (e.g. `5131%`);
  this is a display quirk, not data corruption. Trust the symbol/file matches.
- If `.codegraph/` is missing or the server reports "not initialized", ask
  before running `codegraph init -i`.

### Fast Context MCP Notes

- The `fast-context` MCP is launched via `npx -y --prefer-online
  @sammysnake/fast-context-mcp`. The old standalone `npx@10.2.2` has been
  removed from this machine; `npx` now resolves to the npm 11.12.1 built-in.
- `fast-context` needs a `WINDSURF_API_KEY` env var; the config lists it under
  `env.env_vars`. Confirm it is set in the launching shell/MCP environment,
  otherwise semantic search calls will fail at request time.
<!-- CODEGRAPH_END -->
