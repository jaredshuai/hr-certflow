# HR CertFlow Design System

## Overview

HR CertFlow is an enterprise HR certificate management system. The interface should feel trustworthy, quiet, and operationally precise: a white data-management workspace anchored by deep teal navigation, pale mint surfaces, clear status badges, and restrained green accents.

The visual direction is inspired by the MongoDB-style design family from `awesome-design-md`: deep teal structure, white documentation-like surfaces, rounded cards, pill actions, and green as a high-signal action color. Do not copy MongoDB branding, logos, or exact marketing patterns. Adapt the language into an HR operations product that values auditability, human review, and low-friction table workflows.

## Design Principles

- Business truth first: certificate state, review state, and audit history must be visually clear before decorative elements.
- Human review is prominent: AI extraction output should look provisional until HR confirms it.
- Calm density: pages can be data-rich, but spacing and hierarchy must prevent visual noise.
- Green is a signal, not wallpaper: use it for primary actions, success, active navigation, and selected states.
- Avoid generic admin grayness: keep the interface clean, but use teal surfaces and mint highlights to make the product recognizable.

## Color Tokens

### Core

| Token | Hex | Role |
|---|---:|---|
| `--cf-ink` | `#001e2b` | Primary text, high-emphasis headings |
| `--cf-teal-deep` | `#003d3a` | App identity, navigation emphasis, dark panels |
| `--cf-teal` | `#1f5f5b` | Active menu text, selected controls |
| `--cf-teal-mid` | `#00684a` | Links, confirmed actions, focused borders |
| `--cf-green` | `#00b545` | Primary CTA, success action |
| `--cf-green-soft` | `#dff6e8` | Success backgrounds, active soft badges |
| `--cf-canvas` | `#ffffff` | Main card and table surface |
| `--cf-bg` | `#f7faf9` | Page background |
| `--cf-bg-soft` | `#f1f6f4` | Secondary section background |
| `--cf-border` | `#dfe8e5` | Card and table borders |
| `--cf-border-soft` | `#edf2f0` | Quiet row dividers |
| `--cf-muted` | `#6b7f7a` | Secondary text |

### Semantic

| Token | Hex | Role |
|---|---:|---|
| `--cf-status-review` | `#1677ff` | Pending review, AI output awaiting HR |
| `--cf-status-warning` | `#d48806` | Expiring certificates, second reminders |
| `--cf-status-danger` | `#cf1322` | Expired certificates, rejected review, escalation |
| `--cf-status-success` | `#389e0d` | Active certificate, approved review, resolved task |
| `--cf-status-archived` | `#8c8c8c` | Replaced, archived, closed |

## Typography

Use a pragmatic enterprise sans stack. Prefer a font that renders Chinese well in production.

| Use | Size | Weight | Line Height | Notes |
|---|---:|---:|---:|---|
| Page title | 24px | 600 | 1.3 | Short Chinese titles, no all-caps |
| Section title | 18px | 600 | 1.4 | Card headers and table titles |
| Metric value | 30px | 600 | 1.2 | Dashboard counters |
| Body | 14px | 400 | 1.6 | Forms, descriptions, table text |
| Body emphasis | 14px | 500 | 1.5 | Labels, active tabs, action text |
| Caption | 12px | 400 | 1.4 | Helper text, timestamps, IDs |
| Badge | 12px | 500 | 1.3 | Status tags |

Recommended CSS stack:

```css
font-family: "Alibaba PuHuiTi 3.0", "PingFang SC", "Microsoft YaHei", "Noto Sans SC", sans-serif;
```

Use a monospace font only for technical identifiers, object keys, request IDs, or audit payload previews.

## Layout

- Keep Ant Design Pro as the structural base.
- Main page background: `--cf-bg`.
- Cards and tables sit on `--cf-canvas` with 1px `--cf-border`.
- Default content width is fluid, but inner grids should breathe with 16px to 24px gaps.
- Dashboard metrics should appear as a compact command center: four clear cards, then risk ledger.
- Table-heavy pages should prioritize filters, empty states, and action clarity over decorative hero sections.
- Upload/review pages may use a two-column layout on desktop and single-column stacking below tablet width.

## Shape And Elevation

| Token | Value | Use |
|---|---:|---|
| `--cf-radius-sm` | 6px | Tags, small buttons |
| `--cf-radius-md` | 8px | Inputs, selects |
| `--cf-radius-lg` | 12px | Cards, panels, upload areas |
| `--cf-radius-pill` | 999px | Primary action buttons and status pills |

Elevation should stay subtle:

- Default cards: no shadow, border only.
- Hoverable cards: `0 4px 14px rgba(0, 30, 43, 0.06)`.
- Modals/dropdowns: `0 16px 48px rgba(0, 30, 43, 0.14)`.

## Components

### Navigation

- Header stays white.
- Sidebar background uses `#f7f8fa` or `--cf-bg-soft`.
- Selected menu item uses soft mint background and deep teal text.
- Keep route labels Chinese and business-oriented: `工作台`, `人员管理`, `证书类型`, `持证记录`, `上传识别`, `待复核队列`, `提醒任务`, `审计日志`.

### Buttons

- Primary action: green or deep teal, pill-like where layout permits.
- Secondary action: white or transparent with teal/dark text and border.
- Destructive actions use Ant Design danger red; do not recolor them green.
- Link buttons in tables should stay compact and readable.

### Tables

- Use clear Chinese column labels.
- Never display raw backend enum values to end users.
- Status columns must render localized tags.
- Empty state copy should explain the next practical step.
- IDs may be shown for traceability, but use ellipsis and subdued text.

### Forms

- Required fields should have concise Chinese validation messages.
- Inputs use 40px to 44px height.
- Focus border should use deep teal or green, not blue, where feasible.
- For AI-prefilled fields, visually distinguish extracted content from HR-confirmed data.

### Cards

- Standard card: white, 12px radius, 1px border, 20px to 24px padding.
- Important workflow cards can use pale mint background.
- Dark teal panels are allowed only for high-level summaries or onboarding/help banners; do not use dark sections inside dense table pages.

### Status Tags

- Effective/active: green.
- Pending review/AI provisional: blue.
- Expiring/waiting feedback: gold/orange.
- Expired/rejected/escalated: red.
- Replaced/archived/closed: gray.

Status text must be Chinese:

- `ACTIVE` certificate: `有效`
- `ACTIVE` employee: `在职`
- `PENDING_REVIEW`: `待复核`
- `EXPIRING`: `即将到期`
- `EXPIRED`: `已过期`
- `RENEWED`: `已续证`
- `REPLACED`: `已替换`
- `ARCHIVED`: `已归档`

## Page Guidance

### 工作台

- Treat this as an operations cockpit, not a marketing dashboard.
- Use concise metric cards and a risk ledger.
- Empty risk state should feel positive and explicit: `暂无风险项`.

### 上传识别

- Left side: original certificate file and recognition status.
- Right side: AI-prefilled fields and HR confirmation.
- Show AI extraction quality before confirmation.
- Use copy that reinforces HR review as mandatory.

### 待复核队列

- Make incomplete AI extraction visually obvious.
- The primary row action is `复核`; `驳回` remains secondary and danger-colored.
- Do not let AI output look final before approval.

### 持证记录

- Status and dates are the main scanning anchors.
- Historical replacement should be represented by status/linkage, not overwritten data.
- Manual create/edit flows should feel administrative and auditable.

### 审计日志

- Translate actions and resource types for humans.
- Keep resource IDs visible but low-emphasis.
- This page should feel immutable and factual.

## Motion

Use motion sparingly:

- Page transitions may use a subtle 120ms to 180ms fade/slide.
- Buttons and cards can have small hover transitions.
- Avoid animated backgrounds, bouncing, or decorative motion in core HR workflows.

## Responsive Behavior

- Desktop: keep table density and two-column upload/review layouts.
- Tablet: collapse side-by-side workflow cards into stacked cards.
- Mobile: preserve task completion, but prioritize forms and action buttons over wide tables.
- Touch targets should be at least 40px high.

## Do

- Use deep teal and mint as the recognizable product identity.
- Keep Chinese UI copy specific and operational.
- Add empty/error states that tell HR what to do next.
- Prefer bordered cards over heavy shadows.
- Preserve Ant Design Pro patterns unless there is a clear usability reason to customize.

## Don't

- Do not introduce purple-gradient SaaS aesthetics.
- Do not use dark mode as the default business interface.
- Do not display raw enum values or English table controls where users see them.
- Do not use green for warnings, destructive actions, or large decorative backgrounds.
- Do not make AI extraction results look authoritative before HR approval.
- Do not hard-code vendor-specific storage or AI provider language into UI copy.

## Agent Prompt Guide

When modifying UI, use this instruction:

```text
Follow HR CertFlow DESIGN.md. Keep the Ant Design Pro structure, use a white enterprise workspace with deep teal navigation, mint-green accents, localized Chinese labels, clear status tags, and explicit empty/error states. Preserve auditability and make HR review required before AI output becomes formal certificate data.
```
