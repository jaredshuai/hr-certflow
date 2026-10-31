# Issue 追踪：GitHub

本仓库的 issue 和 spec 都以 GitHub issue 的形式存放（`jaredshuai/hr-certflow`）。所有操作使用 `gh` CLI。

## 约定

- **创建 issue**：`gh issue create --title "..." --body "..."`，多行正文用 heredoc。
- **读取 issue**：`gh issue view <number> --json number,title,body,labels,comments`。
- **列出 issue**：`gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'`，按需加 `--label`、`--state` 筛选。
- **挂为父 issue 的子 issue**：`gh issue create --parent <parent> ...`，或事后 `gh issue edit <parent> --add-sub-issue <child>`（`gh` 2.94+）。旧版 `gh`：`gh api --method POST repos/<owner>/<repo>/issues/<parent>/sub_issues -F sub_issue_id=<child-db-id>`（数据库 id，同下方**阻塞**）。不支持子 issue 时，在子 issue 正文顶部写 `Part of #<parent>`。
- **阻塞**：使用 GitHub **原生 issue 依赖**，这是标准且 UI 可见的表示。用 `gh issue create --blocked-by <n>,<n> ...` 或 `gh issue edit <child> --add-blocked-by <blocker>`（`gh` 2.94+）添加依赖边。旧版 `gh`：`gh api --method POST repos/<owner>/<repo>/issues/<child>/dependencies/blocked_by -F issue_id=<blocker-db-id>`，其中 `<blocker-db-id>` 是阻塞方的数值**数据库 id**（`gh api repos/<owner>/<repo>/issues/<n> --jq .id`，不是 `#number` 也不是 `node_id`）。不支持依赖时，退回到在子 issue 正文顶部写 `Blocked by: #<n>, #<n>`。所有阻塞方都关闭后，该工单即解除阻塞。
- **统计未关闭的阻塞方**：`gh api repos/<owner>/<repo>/issues/<n> --jq .issue_dependencies_summary.blocked_by`（只计未关闭的；0 表示可以开工）。`gh issue view <n> --json blockedBy` 也会列出已关闭的阻塞方，需要过滤：`--jq '[.blockedBy.nodes[] | select(.state == "OPEN")] | length'`。
- **评论**：`gh issue comment <number> --body "..."`
- **打标签 / 移除标签**：`gh issue edit <number> --add-label "..."` / `--remove-label "..."`
- **关闭**：先用 `gh issue comment <number> --body "..."` 发说明，再 `gh issue close <number>`。对已关闭的 issue，`gh issue close --comment` 会丢掉评论但仍返回 0。

仓库从 `git remote -v` 推断，在 clone 内运行 `gh` 会自动识别。

只往用户自己的仓库提 issue。除非用户拥有 `mattpocock/skills`（这些技能的来源仓库），否则绝不往那里提。在 fork 中 `gh` 可能默认指向上游父仓库，所以每个会话第一次 `gh issue create` 之前，用 `gh repo view --json nameWithOwner` 核对目标；若不是用户自己的仓库，先和用户确认。

## 把 PR 当作 triage 来源

**PR 是否作为请求来源：否。**（若本仓库把外部 PR 当作功能请求，改成 `yes`；`/triage` 会读这个开关。）

设为 `yes` 时，PR 会走和 issue 相同的标签与状态机，用 `gh pr` 对应命令：

- **读取 PR**：先 `gh pr view <number>`，再 `gh pr view <number> --comments`（非 TTY 下 `--comments` 只输出评论、不含正文），diff 用 `gh pr diff <number>`。
- **列出待 triage 的外部 PR**：`gh api --paginate 'repos/{owner}/{repo}/pulls?state=open' --jq '.[] | select(.author_association | IN("OWNER","MEMBER","COLLABORATOR") | not) | {number, title, author: .user.login, author_association, labels: [.labels[].name]}'`。
- **评论 / 标签 / 关闭**：`gh pr comment`、`gh pr edit --add-label`/`--remove-label`、`gh pr close`。

GitHub 的 issue 和 PR 共享同一套编号，所以单独一个 `#42` 可能是二者之一——先用 `gh pr view 42`，取不到再用 `gh issue view 42`。

## 当技能要求“发布到 issue 追踪器”时

创建一条 GitHub issue。

## 当技能要求“取相关工单”时

按上面**读取 issue**的方式读取。

## Wayfinding 操作

供 `/wayfinder` 使用。**地图（map）** 是单个 issue，**子（child）** issue 是具体工单。

- **地图**：一个打了 `wayfinder:map` 标签的 issue，正文包含 Notes / Decisions-so-far / Fog。`gh issue create --label wayfinder:map`。
- **子工单**：作为 GitHub 子 issue 挂到地图下（见**挂为父 issue 的子 issue**）。不支持子 issue 时，在地图正文的任务列表里加上该子工单，并在子工单正文顶部写 `Part of #<map>`。标签：`wayfinder:<type>`（`research`/`prototype`/`grilling`/`task`）。被认领后指派给推进它的开发者。
- **阻塞**：见“约定”中的**阻塞**。
- **前沿查询**：列出地图下未关闭的子工单（`gh issue list --state open`，限定在地图的子 issue / 任务列表内），去掉有未关闭阻塞方（见**统计未关闭的阻塞方**，或 `Blocked by` 行中仍未关闭的 issue）或已有指派人的；按地图顺序取第一个。
- **认领**：`gh issue edit <n> --add-assignee @me`，作为会话的第一个写操作。
- **解决**：`gh issue comment <n> --body "<答案>"`，然后 `gh issue close <n>`，再把一条上下文指针（要点 + 链接）追加到地图的 Decisions-so-far。
