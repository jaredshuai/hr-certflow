import assert from 'node:assert/strict';
import { test } from 'node:test';

import { actorStateFromErrorStatus, actorStateFromMe, unauthenticatedStateFromRedirect } from '../src/utils/actorState.ts';

test('authenticated /me shows the gateway identity', () => {
  assert.deepEqual(actorStateFromMe({ name: '张三', source: 'casdoor', authenticated: true }), {
    status: 'authenticated',
    name: '张三',
    source: 'casdoor',
  });
});

test('dev fixed operator is labelled, not shown as a logged-in person', () => {
  assert.deepEqual(
    actorStateFromMe({ name: 'dev-unauthenticated', source: 'dev-unauthenticated', authenticated: false }),
    { status: 'dev-operator', name: 'dev-unauthenticated' },
  );
});

test('missing identity never falls back to a mock actor', () => {
  for (const me of [null, undefined, { name: null, source: null, authenticated: false }]) {
    assert.deepEqual(actorStateFromMe(me), { status: 'unauthenticated' });
  }
  assert.deepEqual(actorStateFromMe({ name: 'HR 管理员', source: 'mock', authenticated: false }), {
    status: 'unauthenticated',
  });
});

test('401 from /me means unauthenticated; other failures are errors', () => {
  assert.deepEqual(actorStateFromErrorStatus(401), { status: 'unauthenticated' });
  assert.deepEqual(actorStateFromErrorStatus(500), { status: 'error' });
  assert.deepEqual(actorStateFromErrorStatus(undefined), { status: 'error' });
});

test('a real login redirect keeps the gate in the redirecting (spinner) state', () => {
  assert.deepEqual(
    unauthenticatedStateFromRedirect({ status: 'loading' }, { redirected: true, loginUrl: '/hr-certflow/auth/login' }),
    { status: 'unauthenticated', loginUrl: '/hr-certflow/auth/login', redirecting: true },
  );
});

test('concurrent 401s stay redirecting instead of falling back to the manual login screen', () => {
  const first = unauthenticatedStateFromRedirect(
    { status: 'loading' },
    { redirected: true, loginUrl: '/hr-certflow/auth/login' },
  );
  // 第二个并发请求：导航已发起，redirectToLoginOnce 返回 redirected=false。
  assert.deepEqual(unauthenticatedStateFromRedirect(first, { redirected: false, loginUrl: '/hr-certflow/auth/login' }), {
    status: 'unauthenticated',
    loginUrl: '/hr-certflow/auth/login',
    redirecting: true,
  });
  // 后续请求没带上 loginUrl 时，沿用第一次的入口。
  assert.deepEqual(unauthenticatedStateFromRedirect(first, { redirected: false }), {
    status: 'unauthenticated',
    loginUrl: '/hr-certflow/auth/login',
    redirecting: true,
  });
});

test('only a non-redirecting 401 (logout / no login entry) shows the manual fallback', () => {
  assert.deepEqual(
    unauthenticatedStateFromRedirect(
      { status: 'authenticated', name: '张三', source: 'oidc' },
      { redirected: false, loginUrl: '/hr-certflow/auth/login' },
    ),
    { status: 'unauthenticated', loginUrl: '/hr-certflow/auth/login', redirecting: false },
  );
  assert.deepEqual(unauthenticatedStateFromRedirect({ status: 'loading' }, { redirected: false }), {
    status: 'unauthenticated',
    redirecting: false,
  });
});
