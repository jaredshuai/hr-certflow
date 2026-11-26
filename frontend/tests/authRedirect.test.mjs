import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  clearRedirectMarker,
  hasRedirectMarker,
  redirectToLoginOnce,
  setRedirectMarker,
} from '../src/utils/loginRedirect.ts';

function memoryStorage() {
  const values = new Map();
  return {
    getItem: (key) => (values.has(key) ? values.get(key) : null),
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: (key) => values.delete(key),
  };
}

function redirectEnv({ pathname = '/hr-certflow/dashboard', search = '', hash = '#/dashboard' } = {}) {
  const assigned = [];
  const storage = memoryStorage();
  return {
    assigned,
    storage,
    env: {
      location: { pathname, search, hash },
      storage,
      assign: (url) => assigned.push(url),
    },
  };
}

test('并发 401 只导航一次（handleAuthError 的防重入契约）', () => {
  const { assigned, env } = redirectEnv();
  const first = redirectToLoginOnce(env, '/hr-certflow/auth/login');
  const second = redirectToLoginOnce(env, '/hr-certflow/auth/login');

  assert.equal(first.redirected, true);
  assert.equal(second.redirected, false);
  assert.equal(assigned.length, 1);
  assert.equal(first.loginUrl, second.loginUrl);
  assert.match(assigned[0], /^\/hr-certflow\/auth\/login\?/);
});

test('返回地址被当前页面覆盖，登录入口不能变成开放重定向', () => {
  const { assigned, env } = redirectEnv();
  redirectToLoginOnce(env, '/hr-certflow/auth/login?return_to=https%3A%2F%2Fevil.example');

  assert.equal(assigned.length, 1);
  assert.match(assigned[0], /return_to=%2Fhr-certflow%2Fdashboard%23%2Fdashboard/);
  assert.doesNotMatch(assigned[0], /evil\.example/);
});

test('/me 成功后清标记，下一次真正过期还能再跳', () => {
  const { assigned, storage, env } = redirectEnv();
  assert.equal(redirectToLoginOnce(env, undefined).redirected, true);
  assert.equal(hasRedirectMarker(storage), true);

  clearRedirectMarker(storage);
  assert.equal(hasRedirectMarker(storage), false);

  // 模拟 30 分钟空闲后的再次 401
  assert.equal(redirectToLoginOnce(env, undefined).redirected, true);
  assert.equal(assigned.length, 2);
});

test('已写过标记（例如刚退出登录）只给登录入口，不自动跳转', () => {
  const { assigned, storage, env } = redirectEnv();
  assert.equal(setRedirectMarker(storage), true);

  const outcome = redirectToLoginOnce(env, undefined);
  assert.equal(outcome.redirected, false);
  assert.equal(outcome.loginUrl, '/hr-certflow/auth/login?return_to=%2Fhr-certflow%2Fdashboard%23%2Fdashboard');
  assert.equal(assigned.length, 0);
});

test('没有登录入口的前缀（本地直连/已退役前缀）不跳转，也不给链接', () => {
  const { assigned, env } = redirectEnv({ pathname: '/local/dashboard', hash: '#/dashboard' });
  const outcome = redirectToLoginOnce(env, undefined);

  assert.equal(outcome.redirected, false);
  assert.equal(outcome.loginUrl, undefined);
  assert.equal(assigned.length, 0);
});

test('sessionStorage 不可用时放弃自动跳转，只给手动登录入口', () => {
  const assigned = [];
  const env = {
    location: { pathname: '/hr-certflow/dashboard', search: '', hash: '' },
    storage: null,
    assign: (url) => assigned.push(url),
  };

  const outcome = redirectToLoginOnce(env, undefined);
  assert.equal(outcome.redirected, false);
  assert.equal(outcome.loginUrl, '/hr-certflow/auth/login?return_to=%2Fhr-certflow%2Fdashboard');
  assert.equal(assigned.length, 0);
});
