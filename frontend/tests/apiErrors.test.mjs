import assert from 'node:assert/strict';
import { test } from 'node:test';

import { apiErrorLoginUrl, apiErrorMessage, apiErrorStatus, isAuthError, isReviewStaleActionError, loadFailureState } from '../src/utils/apiErrors.ts';
import { emptyDashboardSummary } from '../src/utils/dashboardSummary.ts';

function axiosError(status, detail) {
  const error = new Error(`Request failed with status code ${status}`);
  error.name = 'AxiosError';
  error.response = { status, data: detail === undefined ? 'Unauthorized' : { detail } };
  return error;
}

test('AxiosError 401 (gateway text/plain) exposes its status', () => {
  assert.equal(apiErrorStatus(axiosError(401)), 401);
});

test('AxiosError 409 exposes its status', () => {
  assert.equal(apiErrorStatus(axiosError(409, 'Review task has changed')), 409);
});

test('BizError from errorThrower still reads info.response.status / info.status', () => {
  const biz = Object.assign(new Error('x'), { info: { response: { status: 409 } } });
  assert.equal(apiErrorStatus(biz), 409);
  const flat = Object.assign(new Error('x'), { info: { status: 422 } });
  assert.equal(apiErrorStatus(flat), 422);
});

test('non-HTTP errors have no status', () => {
  assert.equal(apiErrorStatus(new Error('network')), undefined);
  assert.equal(apiErrorStatus(undefined), undefined);
  assert.equal(apiErrorStatus({ response: { status: '401' } }), undefined);
});

test('stale review detection rejects non-409 AxiosError with stale message', () => {
  const error = axiosError(500);
  error.message = 'Review task has changed';
  assert.equal(isReviewStaleActionError(error), false);
  const conflict = axiosError(409);
  conflict.message = 'Review task has changed';
  assert.equal(isReviewStaleActionError(conflict), true);
});

test('AxiosError 409 stale detail in response.data.detail is detected', () => {
  const conflict = axiosError(409, 'Review task has changed');
  assert.equal(apiErrorMessage(conflict, 'x'), 'Review task has changed');
  assert.equal(isReviewStaleActionError(conflict), true);
  assert.equal(apiErrorMessage(axiosError(401), 'fallback'), 'Request failed with status code 401');
});

test('jxccs-access {code} details map to Chinese messages', () => {
  assert.equal(
    apiErrorMessage(axiosError(403, { code: 'FORBIDDEN', requestId: 'r-1' }), '失败'),
    '没有执行此操作的权限，请联系管理员授权。',
  );
  assert.equal(apiErrorMessage(axiosError(403, { code: 'CSRF_TOKEN_INVALID' }), '失败'), '页面已过期，请刷新后重试。');
  assert.equal(
    apiErrorMessage(axiosError(503, { code: 'DEPENDENCY_UNAVAILABLE' }), '失败'),
    '权限服务暂时不可用，请稍后重试。',
  );
  assert.equal(apiErrorMessage(axiosError(400, { code: 'SOMETHING_ELSE' }), '失败'), 'Request failed with status code 400');
});

test('the 401 body loginUrl is read from both AxiosError and BizError shapes', () => {
  const detail = { code: 'UNAUTHENTICATED', loginUrl: '/hr-certflow/auth/login' };
  assert.equal(apiErrorLoginUrl(axiosError(401, detail)), '/hr-certflow/auth/login');
  assert.equal(
    apiErrorLoginUrl(Object.assign(new Error('x'), { info: { data: { detail }, status: 401 } })),
    '/hr-certflow/auth/login',
  );
  assert.equal(
    apiErrorLoginUrl(Object.assign(new Error('x'), { info: { response: { status: 401, data: { detail } } } })),
    '/hr-certflow/auth/login',
  );
});

test('a malformed or missing loginUrl is ignored', () => {
  for (const detail of [undefined, 'Unauthorized', {}, { code: 'UNAUTHENTICATED' }, { loginUrl: 42 }, { loginUrl: '  ' }]) {
    assert.equal(apiErrorLoginUrl(axiosError(401, detail)), undefined);
  }
  assert.equal(apiErrorLoginUrl(new Error('network')), undefined);
});

test('isAuthError 识别 401 与 jxccs-access 的会话失效 code', () => {
  assert.equal(isAuthError(axiosError(401)), true);
  assert.equal(isAuthError(axiosError(401, { code: 'UNAUTHENTICATED', loginUrl: '/hr-certflow/auth/login' })), true);
  assert.equal(isAuthError(axiosError(401, { code: 'SESSION_EXPIRED' })), true);
  // BizError（errorThrower）把 detail 放在 info.data.detail 下，同样要识别。
  assert.equal(
    isAuthError(Object.assign(new Error('x'), { info: { data: { detail: { code: 'SESSION_EXPIRED' } } } })),
    true,
  );
});

test('isAuthError 不把权限/普通故障误判为登录失效', () => {
  assert.equal(isAuthError(axiosError(403, { code: 'FORBIDDEN' })), false);
  assert.equal(isAuthError(axiosError(409, 'Review task has changed')), false);
  assert.equal(isAuthError(axiosError(500, 'boom')), false);
  assert.equal(isAuthError(new Error('network')), false);
  assert.equal(isAuthError(undefined), false);
});

test('loadFailureState：登录失效返回 null，其他错误退回空数据并给文案', () => {
  assert.equal(loadFailureState(axiosError(401), '工作台数据加载失败', emptyDashboardSummary), null);
  assert.equal(
    loadFailureState(axiosError(401, { code: 'SESSION_EXPIRED' }), '工作台数据加载失败', emptyDashboardSummary),
    null,
  );
  assert.deepEqual(loadFailureState(axiosError(500, 'boom'), '失败', 'empty'), {
    data: 'empty',
    loadError: 'boom',
  });
  assert.equal(
    loadFailureState(axiosError(403, { code: 'FORBIDDEN' }), '失败', 'empty').loadError,
    '没有执行此操作的权限，请联系管理员授权。',
  );
});

test('工作台收到 401 时不渲染错误红框、不清零已有数据', () => {
  // 与 pages/Dashboard/index.tsx 的 catch 同一条判定：loadFailureState 返回 null
  // 就直接 return，不执行 setSummary/setLoadError。
  let summary = { ...emptyDashboardSummary, expiring_count: 7, coverage: 62 };
  let loadError;
  function runDashboardCatch(error) {
    const failure = loadFailureState(error, '工作台数据加载失败', emptyDashboardSummary);
    if (!failure) return;
    summary = failure.data;
    loadError = failure.loadError;
  }

  runDashboardCatch(axiosError(401, { code: 'UNAUTHENTICATED' }));
  assert.equal(summary.expiring_count, 7);
  assert.equal(summary.coverage, 62);
  assert.equal(loadError, undefined);

  // 非登录故障仍然如实报错并退回空数据，避免把接口故障显示成 0 业务数据。
  runDashboardCatch(axiosError(500, 'boom'));
  assert.equal(summary.expiring_count, 0);
  assert.equal(loadError, 'boom');
});
