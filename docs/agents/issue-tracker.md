# Issue 追踪：GitHub

本仓库的 issue 和 PRD 都以 GitHub issue 的形式存放。所有操作使用 `gh` CLI。

## 约定

- **创建 issue**：`gh issue create --title "..." --body "..."`，多行正文用 heredoc。
- **读取 issue**：`gh issue view <number> --comments`，用 `jq` 过滤评论并同时取标签。
- **列出 issue**：`gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'`，按需加 `--label`、`--state` 筛选。
- **评论**：`gh issue comment <number> --body "..."`
- **打标签 / 移除标签**：`gh issue edit <number> --add-label "..."` / `--remove-label "..."`
- **关闭**：`gh issue close <number> --comment "..."`

仓库从 `git remote -v` 推断，在 clone 内运行 `gh` 会自动识别。

## 把 PR 当作 triage 来源

**PR 是否作为请求来源：否。**（若本仓库把外部 PR 当作功能请求，改成 `yes`；`/triage` 会读这个开关。）

设为 `yes` 时，PR 会走和 issue 相同的标签与状态机，用 `gh pr` 对应命令：

- **读取 PR**：`gh pr view <number> --comments`，diff 用 `gh pr diff <number>`。
- **列出待 triage 的外部 PR**：`gh pr list --state open --json number,title,body,labels,author,authorAssociation,comments`，只保留 `authorAssociation` 为 `CONTRIBUTOR`、`FIRST_TIME_CONTRIBUTOR` 或 `NONE` 的（去掉 `OWNER`/`MEMBER`/`COLLABORATOR`）。
- **评论 / 标签 / 关闭**：`gh pr comment`、`gh pr edit --add-label`/`--remove-label`、`gh pr close`。

GitHub 的 issue 和 PR 共享同一套编号，所以单独一个 `#42` 可能是二者之一——先用 `gh pr view 42`，取不到再用 `gh issue view 42`。

## 当技能要求“发布到 issue 追踪器”时

创建一条 GitHub issue。

## 当技能要求“取相关工单”时

运行 `gh issue view <number> --comments`。
