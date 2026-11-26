import assert from 'node:assert/strict';
import { test } from 'node:test';

import { authGateMode, authGateView } from '../src/utils/authGate.ts';

test('loading / unauthenticated / error never let business pages through', () => {
  assert.equal(authGateMode({ status: 'loading' }), 'loading');
  assert.equal(authGateMode({ status: 'unauthenticated' }), 'unauthenticated');
  assert.equal(
    authGateMode({ status: 'unauthenticated', loginUrl: '/hr-certflow/auth/login' }),
    'unauthenticated',
  );
  assert.equal(authGateMode({ status: 'error' }), 'error');
});

test('only a confirmed actor (real session or dev operator) opens the gate', () => {
  assert.equal(authGateMode({ status: 'authenticated', name: '张三', source: 'oidc' }), 'ready');
  assert.equal(authGateMode({ status: 'dev-operator', name: 'dev-unauthenticated' }), 'ready');
});

test('a page is not mounted, and therefore sends no first request, until auth resolves', () => {
  // AuthGate.tsx renders children only when authGateView(state).renderChildren is true;
  // this exercises that production boundary rather than a second copy of the rule.
  let pageMounts = 0;
  let firstRequests = 0;
  function renderGate(state) {
    if (!authGateView(state).renderChildren) return null;
    pageMounts += 1;
    firstRequests += 1; // the Dashboard useEffect request fires on mount
    return 'page';
  }

  assert.equal(renderGate({ status: 'loading' }), null);
  assert.equal(renderGate({ status: 'unauthenticated', loginUrl: '/hr-certflow/auth/login' }), null);
  assert.equal(renderGate({ status: 'error' }), null);
  assert.equal(pageMounts, 0);
  assert.equal(firstRequests, 0);

  assert.equal(renderGate({ status: 'authenticated', name: '张三', source: 'oidc' }), 'page');
  assert.equal(pageMounts, 1);
  assert.equal(firstRequests, 1);
});

test('the manual login link only exists for unauthenticated state', () => {
  assert.equal(
    authGateView({ status: 'unauthenticated', loginUrl: '/hr-certflow/auth/login' }).loginUrl,
    '/hr-certflow/auth/login',
  );
  assert.equal(authGateView({ status: 'unauthenticated' }).loginUrl, undefined);
  assert.equal(authGateView({ status: 'loading' }).loginUrl, undefined);
  assert.equal(authGateView({ status: 'error' }).loginUrl, undefined);
});
