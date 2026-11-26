// 本文件不引用任何其它模块（类型除外），便于 tests/ 下用 node --test 直接运行。

import type {
  DashboardChartRow,
  DashboardPipelineStep,
  DashboardRiskRow,
  DashboardSummary,
} from '@/types/domain';

/** 工作台接口不可用时的兜底数据；所有字段都必须存在，渲染层不再判空。 */
export const emptyDashboardSummary: DashboardSummary = {
  expiring_count: 0,
  expired_count: 0,
  pending_review_count: 0,
  coverage: 0,
  certificate_status_rows: [],
  workload_rows: [],
  pipeline_steps: [],
  risk_rows: [],
};

function numberOrZero(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function objectRows(value: unknown): Record<string, unknown>[] {
  if (!Array.isArray(value)) return [];
  return value.filter(
    (item): item is Record<string, unknown> => typeof item === 'object' && item !== null && !Array.isArray(item),
  );
}

function chartRows(value: unknown): DashboardChartRow[] {
  return objectRows(value).map((row) => ({
    category: text(row.category),
    count: numberOrZero(row.count),
    target_path: text(row.target_path),
  }));
}

function pipelineSteps(value: unknown): DashboardPipelineStep[] {
  return objectRows(value).map((step) => ({
    title: text(step.title),
    description: text(step.description),
    count: numberOrZero(step.count),
    target_path: text(step.target_path),
  }));
}

function riskRows(value: unknown): DashboardRiskRow[] {
  return objectRows(value).map((row) => ({
    id: text(row.id),
    metric: text(row.metric),
    count: numberOrZero(row.count),
    status: text(row.status),
    target_path: text(row.target_path),
  }));
}

/**
 * 把 `/dashboard/summary` 的原始响应收敛成可安全渲染的结构。
 *
 * 接口返回 200 但 body 为空、是 HTML（例如网关兜底页）、被包了一层或缺数组字段时，
 * 旧实现直接解引用 `summary.pipeline_steps.some(...)` 会抛 TypeError，而全站没有
 * ErrorBoundary 兜底，结果是整页白屏。这里对每个字段逐层判空，保留可用的部分。
 */
export function normalizeDashboardSummary(raw: unknown): DashboardSummary {
  const value =
    typeof raw === 'object' && raw !== null && !Array.isArray(raw) ? (raw as Record<string, unknown>) : {};
  return {
    expiring_count: numberOrZero(value.expiring_count),
    expired_count: numberOrZero(value.expired_count),
    pending_review_count: numberOrZero(value.pending_review_count),
    coverage: numberOrZero(value.coverage),
    certificate_status_rows: chartRows(value.certificate_status_rows),
    workload_rows: chartRows(value.workload_rows),
    pipeline_steps: pipelineSteps(value.pipeline_steps),
    risk_rows: riskRows(value.risk_rows),
  };
}
