import assert from 'node:assert/strict';
import { test } from 'node:test';

import { buildRequestHeaders, setCsrfToken } from '../src/utils/requestHeaders.ts';

test('requests carry only X-Request-ID and no identity headers', () => {
  const headers = buildRequestHeaders({ Accept: 'application/json' }, 'req-1');

  assert.deepEqual(headers, { Accept: 'application/json', 'X-Request-ID': 'req-1' });
});

test('identity headers set by callers are stripped regardless of case', () => {
  const headers = buildRequestHeaders(
    { 'X-HR-Actor': 'Mallory', 'x-hr-actor-source': 'casdoor', 'Content-Type': 'application/json' },
    'req-2',
  );

  assert.deepEqual(Object.keys(headers).sort(), ['Content-Type', 'X-Request-ID']);
});

test('missing base headers still produce X-Request-ID only', () => {
  const headers = buildRequestHeaders(undefined, 'req-3');

  assert.deepEqual(headers, { 'X-Request-ID': 'req-3' });
});

test('CSRF token is attached only to unsafe methods once /me provided one', () => {
  setCsrfToken(undefined);
  assert.equal(buildRequestHeaders({}, 'req-4', 'post')['X-CSRF-Token'], undefined);

  setCsrfToken('csrf-1');
  try {
    assert.equal(buildRequestHeaders({}, 'req-5', 'post')['X-CSRF-Token'], 'csrf-1');
    assert.equal(buildRequestHeaders({}, 'req-6', 'PATCH')['X-CSRF-Token'], 'csrf-1');
    assert.equal(buildRequestHeaders({}, 'req-7', 'get')['X-CSRF-Token'], undefined);
    assert.equal(buildRequestHeaders({}, 'req-8')['X-CSRF-Token'], undefined);
    assert.equal(buildRequestHeaders({ 'x-csrf-token': 'forged' }, 'req-9', 'get')['x-csrf-token'], undefined);
  } finally {
    setCsrfToken(undefined);
  }
});
