import assert from 'node:assert/strict';
import { test } from 'node:test';

import { apiErrorMessage, apiErrorStatus, isReviewStaleActionError } from '../src/utils/apiErrors.ts';

function axiosError(status, detail) {
  const error = new Error(`Request failed with status code ${status}`);
  error.name = 'AxiosError';
  error.response = { status, data: detail === undefined ? 'Unauthorized' : { detail } };
  return error;
}

test('AxiosError 401 (oauth2-proxy text/plain) exposes its status', () => {
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
