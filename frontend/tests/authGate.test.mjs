import assert from 'node:assert/strict';
import { test } from 'node:test';

import { authGateMode, authGateScreen } from '../src/utils/authGate.ts';

test('loading / redirecting / unauthenticated / error never let business pages through', () => {
  assert.equal(authGateMode({ status: 'loading' }), 'loading');
  assert.equal(authGateMode({ status: 'unauthenticated' }), 'unauthenticated');
  assert.equal(
    authGateMode({ status: 'unauthenticated', loginUrl: '/hr-certflow/auth/login' }),
    'unauthenticated',
  );
  assert.equal(
    authGateMode({ status: 'unauthenticated', loginUrl: '/hr-certflow/auth/login', redirecting: true }),
    'redirecting',
  );
  assert.equal(authGateMode({ status: 'error' }), 'error');
});

test('only a confirmed actor (real session or dev operator) opens the gate', () => {
  assert.equal(authGateMode({ status: 'authenticated', name: '张三', source: 'oidc' }), 'ready');
  assert.equal(authGateMode({ status: 'dev-operator', name: 'dev-unauthenticated' }), 'ready');
});

test('a page is not mounted, and therefore sends no first request, until auth resolves', () => {
  // AuthGate.tsx renders children only for screen.kind === 'content'; this exercises
  // that production boundary rather than a second copy of the rule.
  let pageMounts = 0;
  let firstRequests = 0;
  function renderGate(state) {
    if (authGateScreen(state).kind !== 'content') return null;
    pageMounts += 1;
    firstRequests += 1; // the Dashboard useEffect request fires on mount
    return 'page';
  }

  assert.equal(renderGate({ status: 'loading' }), null);
  assert.equal(renderGate({ status: 'unauthenticated', loginUrl: '/hr-certflow/auth/login' }), null);
  assert.equal(
    renderGate({ status: 'unauthenticated', loginUrl: '/hr-certflow/auth/login', redirecting: true }),
    null,
  );
  assert.equal(renderGate({ status: 'error' }), null);
  assert.equal(pageMounts, 0);
  assert.equal(firstRequests, 0);

  assert.equal(renderGate({ status: 'authenticated', name: '张三', source: 'oidc' }), 'page');
  assert.equal(pageMounts, 1);
  assert.equal(firstRequests, 1);
});

test('automatic SSO redirect keeps the smooth spinner and never shows the login-expired copy', () => {
  const loginUrl = '/hr-certflow/auth/login?return_to=%2Fhr-certflow%2Fdashboard';
  for (const state of [
    { status: 'loading' },
    { status: 'unauthenticated', loginUrl, redirecting: true },
  ]) {
    const screen = authGateScreen(state);
    assert.equal(screen.kind, 'spinner');
    assert.equal('title' in screen, false);
    assert.doesNotMatch(screen.text, /登录已失效/);
  }
  assert.deepEqual(authGateScreen({ status: 'unauthenticated', loginUrl, redirecting: true }), {
    kind: 'spinner',
    text: '正在跳转登录…',
  });
});

test('only a non-redirecting unauthenticated state shows the manual login fallback', () => {
  const loginUrl = '/hr-certflow/auth/login?return_to=%2Fhr-certflow%2Fdashboard';
  const screen = authGateScreen({ status: 'unauthenticated', loginUrl, redirecting: false });
  assert.deepEqual(screen, {
    kind: 'manual-login',
    title: '登录已失效，请重新登录',
    description: '请重新登录后继续使用。',
    loginUrl,
  });

  // 刚退出登录 / 没有登录入口时仍给手动兜底，而不是一直转圈。
  assert.deepEqual(authGateScreen({ status: 'unauthenticated' }), {
    kind: 'manual-login',
    title: '登录已失效，请重新登录',
    description: '当前环境未配置登录入口，请联系管理员。',
  });
});

test('auth state failure has its own retry screen', () => {
  assert.deepEqual(authGateScreen({ status: 'error' }), {
    kind: 'error',
    title: '登录状态加载失败',
    description: '请检查网络后重试；若持续失败，请联系管理员。',
  });
});
