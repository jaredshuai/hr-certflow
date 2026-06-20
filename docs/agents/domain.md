# Domain 文档

工程类技能在探索代码库时，如何消费本仓库的领域文档。

本仓库采用**单上下文**布局：仓库根目录一个 `CONTEXT.md` 和一个 `docs/adr/`，`backend/` 和 `frontend/` 共用。HR 证书业务（员工、证书类型、提取、审核、提醒、审计）是一套连贯业务，前后端都读这一份。

## 探索前先读

- 仓库根目录的 **`CONTEXT.md`**；或
- 若根目录存在 **`CONTEXT-MAP.md`**，它会指向每个上下文各自的 `CONTEXT.md`，读与本次主题相关的那些。
- **`docs/adr/`** —— 读与你即将改动的区域相关的 ADR。

如果这些文件不存在，**静默继续**。不要提示它们缺失，也不要主动建议提前创建。`/domain-modeling` 技能（经 `/grill-with-docs` 和 `/improve-codebase-architecture` 触发）会在真正敲定术语或决定时按需创建它们。

## 文件结构

单上下文仓库（本仓库）：

```
/
├── CONTEXT.md
├── docs/adr/
│   ├── 0001-event-sourced-orders.md
│   └── 0002-postgres-for-write-model.md
├── backend/
└── frontend/
```

多上下文仓库（根目录存在 `CONTEXT-MAP.md`）——本仓库不使用：

```
/
├── CONTEXT-MAP.md
├── docs/adr/                          ← 系统级决定
└── src/
    ├── ordering/
    │   ├── CONTEXT.md
    │   └── docs/adr/                  ← 上下文特定决定
    └── billing/
        ├── CONTEXT.md
        └── docs/adr/
```

## 使用术语表里的用词

当你的产出（issue 标题、重构建议、假设、测试名）要命名一个领域概念时，用 `CONTEXT.md` 里定义的词，不要漂移到术语表明确避免的同义词。

如果你需要的概念还不在术语表里，这是一个信号——要么你在发明项目不用的语言（重新考虑），要么确实存在缺口（记下来给 `/domain-modeling`）。

## 标出与 ADR 的冲突

如果你的产出和某个已有 ADR 矛盾，要明确指出，而不是悄悄覆盖：

> _与 ADR-0007（事件溯源订单）冲突——但值得重开此议题，因为……_
