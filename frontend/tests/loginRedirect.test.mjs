import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  appendReturnTo,
  buildAccessLoginUrl,
  hasAccessLogout,
  loginUrlForLocation,
  resolveAppBase,
  safeReturnPath,
} from '../src/utils/loginRedirect.ts';

test('app base matches the same gateway prefixes as the API base path', () => {
  assert.equal(resolveAppBase('/hr-certflow/'), '/hr-certflow');
  assert.equal(resolveAppBase('/hr-certflow'), '/hr-certflow');
  assert.equal(resolveAppBase('/hr-certflow/reviews/1'), '/hr-certflow');
  assert.equal(resolveAppBase('/hr-certflow-dev/x'), '/hr-certflow-dev');
  assert.equal(resolveAppBase('/'), undefined);
  assert.equal(resolveAppBase('/reviews'), undefined);
  assert.equal(resolveAppBase('/hr-certflowx/'), undefined);
});

test('release and dev prefixes both use the jxccs-access BFF login, not oauth2-proxy', () => {
  assert.equal(
    loginUrlForLocation({ pathname: '/hr-certflow/reviews', search: '?id=3&tab=a', hash: '#top' }),
    `/hr-certflow/auth/login?return_to=${encodeURIComponent('/hr-certflow/reviews?id=3&tab=a#top')}`,
  );
  assert.equal(
    loginUrlForLocation({ pathname: '/hr-certflow/', search: '', hash: '' }),
    '/hr-certflow/auth/login?return_to=%2Fhr-certflow%2F',
  );
  assert.equal(
    loginUrlForLocation({ pathname: '/hr-certflow-dev/reviews', search: '?id=3', hash: '#top' }),
    `/hr-certflow-dev/auth/login?return_to=${encodeURIComponent('/hr-certflow-dev/reviews?id=3#top')}`,
  );
  assert.equal(
    buildAccessLoginUrl('/hr-certflow-dev', '//evil.example/'),
    '/hr-certflow-dev/auth/login?return_to=%2Fhr-certflow-dev%2F',
  );
});

test('the login URL from the 401 body wins over the prefix fallback', () => {
  assert.equal(
    loginUrlForLocation({ pathname: '/hr-certflow/', search: '', hash: '' }, '/hr-certflow/auth/login'),
    '/hr-certflow/auth/login?return_to=%2Fhr-certflow%2F',
  );
  assert.equal(
    loginUrlForLocation({ pathname: '/hr-certflow/a', search: '?x=1', hash: '' }, '/hr-certflow/auth/login?flow=oidc'),
    `/hr-certflow/auth/login?flow=oidc&return_to=${encodeURIComponent('/hr-certflow/a?x=1')}`,
  );
  // 后端换路径时前端跟着走，不需要再发一次版本。
  assert.equal(
    loginUrlForLocation({ pathname: '/hr-certflow/', search: '', hash: '' }, '/hr-certflow/auth/login-v2'),
    '/hr-certflow/auth/login-v2?return_to=%2Fhr-certflow%2F',
  );
});

test('a backend login URL cannot become an open redirect', () => {
  const location = { pathname: '/hr-certflow/', search: '', hash: '' };
  const fallback = '/hr-certflow/auth/login?return_to=%2Fhr-certflow%2F';
  for (const bad of [
    'https://evil.example/login',
    '//evil.example/login',
    '/other/auth/login',
    '/hr-certflow-dev/auth/login',
    '/hr-certflow\\..',
    '/hr-certflow/../evil',
    '/hr-certflow/%2e%2e/evil',
    'enter code',
  ]) {
    assert.equal(loginUrlForLocation(location, bad), fallback, bad);
    assert.equal(appendReturnTo(bad, '/hr-certflow', '/hr-certflow/'), undefined, bad);
  }
  // 已有 return_to 会被当前页面地址覆盖，不能借 query 注入外站。
  assert.equal(
    appendReturnTo('/hr-certflow/auth/login?return_to=https%3A%2F%2Fevil.example%2F', '/hr-certflow', '/hr-certflow/a'),
    '/hr-certflow/auth/login?return_to=%2Fhr-certflow%2Fa',
  );
});

test('no redirect outside the gateway prefix (local / direct access)', () => {
  assert.equal(loginUrlForLocation({ pathname: '/', search: '', hash: '' }), undefined);
});

test('retired prefixes never redirect to login', () => {
  assert.equal(loginUrlForLocation({ pathname: '/hr-certflow-release/', search: '', hash: '' }), undefined);
});

test('rd only allows same-origin paths under the app base', () => {
  assert.equal(safeReturnPath('/hr-certflow', '/hr-certflow/a?b=1'), '/hr-certflow/a?b=1');
  assert.equal(safeReturnPath('/hr-certflow', '/hr-certflow'), '/hr-certflow');
  for (const bad of ['//evil.example/hr-certflow', 'https://evil.example/', '/other', '/hr-certflowx', '/hr-certflow\\..']) {
    assert.equal(safeReturnPath('/hr-certflow', bad), '/hr-certflow/');
  }
  assert.equal(buildAccessLoginUrl('/hr-certflow', '/other'), '/hr-certflow/auth/login?return_to=%2Fhr-certflow%2F');
});

test('logout is available on release, dev and local direct access only', () => {
  assert.equal(hasAccessLogout('/hr-certflow/'), true);
  assert.equal(hasAccessLogout('/hr-certflow/dashboard'), true);
  assert.equal(hasAccessLogout('/hr-certflow-dev/'), true);
  assert.equal(hasAccessLogout('/dashboard'), true); // 本地直连根路径，无网关前缀
  assert.equal(hasAccessLogout('/other/'), true); // 同上：没有识别到应用前缀时按本地直连处理
  assert.equal(hasAccessLogout('/hr-certflow-release/'), false);
});
