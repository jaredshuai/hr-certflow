import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  emptyDashboardSummary,
  isDashboardSummary,
  normalizeDashboardSummary,
} from '../src/utils/dashboardSummary.ts';

test('empty, HTML and non-object bodies fall back to the full empty summary', () => {
  for (const raw of [undefined, null, '', '<!DOCTYPE html><html></html>', 42, [], ['x']]) {
    assert.deepEqual(normalizeDashboardSummary(raw), emptyDashboardSummary);
  }
});

test('missing, wrong-typed and negative fields are coerced instead of left undefined', () => {
  assert.deepEqual(normalizeDashboardSummary({ expiring_count: '3', coverage: null }), emptyDashboardSummary);
  assert.deepEqual(normalizeDashboardSummary({ expiring_count: -2, coverage: -1 }), emptyDashboardSummary);
  assert.deepEqual(
    normalizeDashboardSummary({ expiring_count: 2, coverage: 12.5, certificate_status_rows: null }),
    { ...emptyDashboardSummary, expiring_count: 2, coverage: 12.5 },
  );
});

test('array rows are filtered and field-normalised before rendering', () => {
  const summary = normalizeDashboardSummary({
    expired_count: 1,
    certificate_status_rows: [
      { category: '已过期', count: 1, target_path: '/certificates?status=EXPIRED' },
      { category: '缺目标路径也可以上图', count: 'oops' },
      { category: '', count: 1, target_path: '/certificates' },
      null,
      'x',
    ],
    workload_rows: [{ category: '已过期', count: 'oops', target_path: '/certificates?status=EXPIRED' }],
    pipeline_steps: [
      { title: '上传原件', description: '1 份待识别', count: 1, target_path: '/documents' },
      {},
      { title: '缺目标路径' },
    ],
    risk_rows: [
      { id: 'expired-certificates', metric: '已过期证书', count: 1, status: '高危', target_path: '/x' },
      { id: '', metric: '缺 id', count: 1, status: '高危', target_path: '/x' },
      7,
    ],
  });

  assert.deepEqual(summary.certificate_status_rows, [
    { category: '已过期', count: 1, target_path: '/certificates?status=EXPIRED' },
    { category: '缺目标路径也可以上图', count: 0, target_path: '' },
  ]);
  assert.deepEqual(summary.workload_rows, [
    { category: '已过期', count: 0, target_path: '/certificates?status=EXPIRED' },
  ]);
  assert.deepEqual(summary.pipeline_steps, [
    { title: '上传原件', description: '1 份待识别', count: 1, target_path: '/documents' },
  ]);
  assert.deepEqual(summary.risk_rows, [
    { id: 'expired-certificates', metric: '已过期证书', count: 1, status: '高危', target_path: '/x' },
  ]);
});

test('normalising a valid payload keeps every number and row', () => {
  const valid = {
    expiring_count: 3,
    expired_count: 1,
    pending_review_count: 2,
    coverage: 66.7,
    certificate_status_rows: [{ category: '生效', count: 8, target_path: '/certificates' }],
    workload_rows: [{ category: '已过期', count: 1, target_path: '/certificates?status=EXPIRED' }],
    pipeline_steps: [{ title: '上传原件', description: '0 份待识别', count: 0, target_path: '/documents' }],
    risk_rows: [{ id: 'pending-reviews', metric: '待复核识别', count: 2, status: '处理中', target_path: '/review-queue' }],
  };
  assert.deepEqual(normalizeDashboardSummary(valid), valid);
});

test('only a complete summary payload is treated as valid', () => {
  const valid = {
    expiring_count: 0,
    expired_count: 0,
    pending_review_count: 0,
    coverage: 0,
    certificate_status_rows: [],
    workload_rows: [],
    pipeline_steps: [],
    risk_rows: [],
  };
  assert.equal(isDashboardSummary(valid), true);
  assert.equal(isDashboardSummary({ ...valid, risk_rows: undefined }), false);
  assert.equal(isDashboardSummary({ ...valid, coverage: '0' }), false);
  assert.equal(isDashboardSummary({ ...valid, expiring_count: -1 }), false);
  assert.equal(isDashboardSummary({ ...valid, coverage: Number.NaN }), false);
  for (const raw of [undefined, null, '', '<html></html>', [], 42]) {
    assert.equal(isDashboardSummary(raw), false);
  }
});
