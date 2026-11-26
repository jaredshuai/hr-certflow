import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  createGlitchtipInitOptions,
  initGlitchtip,
  reportErrorToGlitchtip,
  resetGlitchtipForTests,
  resolveGlitchtipEnvironment,
  sanitizeGlitchtipEvent,
  shouldDropGlitchtipEvent,
} from '../src/utils/glitchtip.ts';

// node --test 没有 DOM：挂上最小 window 桩，生产代码里的 typeof window 守卫
// 与 __GLITCHTIP_CONFIG__ 读取都针对这个全局对象。
if (typeof globalThis.window === 'undefined') {
  globalThis.window = {};
}

function withConfig(config, run) {
  const hadConfig = '__GLITCHTIP_CONFIG__' in window;
  const previous = window.__GLITCHTIP_CONFIG__;
  if (config === undefined) {
    delete window.__GLITCHTIP_CONFIG__;
  } else {
    window.__GLITCHTIP_CONFIG__ = config;
  }
  try {
    return run();
  } finally {
    if (hadConfig) {
      window.__GLITCHTIP_CONFIG__ = previous;
    } else {
      delete window.__GLITCHTIP_CONFIG__;
    }
  }
}

function withLocationPathname(pathname, run) {
  const descriptor = Object.getOwnPropertyDescriptor(window, 'location');
  try {
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { ...window.location, pathname },
    });
    return run();
  } finally {
    if (descriptor) {
      Object.defineProperty(window, 'location', descriptor);
    }
  }
}

// ---------- 初始化决策：无 DSN 静默，有 DSN 才初始化 ----------

test('initGlitchtip does nothing when the config object is missing', () => {
  resetGlitchtipForTests();
  const sentry = { init() { assert.fail('Sentry.init must not be called'); } };
  assert.equal(withConfig(undefined, () => initGlitchtip(sentry)), false);
});

test('initGlitchtip does nothing when the dsn is empty or whitespace', () => {
  resetGlitchtipForTests();
  const sentry = { init() { assert.fail('Sentry.init must not be called'); } };
  assert.equal(withConfig({ dsn: '' }, () => initGlitchtip(sentry)), false);
  assert.equal(withConfig({ dsn: '   ' }, () => initGlitchtip(sentry)), false);
});

test('initGlitchtip initializes the sdk once when a non-empty dsn is injected', () => {
  resetGlitchtipForTests();
  const calls = [];
  const sentry = {
    init(options) {
      calls.push(options);
    },
  };
  const config = { dsn: 'http://public@monitoring.internal.invalid/3', environment: 'release' };
  assert.equal(
    withConfig(config, () => withLocationPathname('/hr-certflow/', () => initGlitchtip(sentry))),
    true,
  );
  assert.equal(calls.length, 1);
  assert.equal(calls[0].dsn, config.dsn);
  assert.equal(calls[0].environment, 'release');
  assert.equal(calls[0].sendDefaultPii, false);
  assert.equal(typeof calls[0].beforeSend, 'function');

  // 第二次调用不重复初始化。
  assert.equal(
    withConfig(config, () => withLocationPathname('/hr-certflow/', () => initGlitchtip(sentry))),
    true,
  );
  assert.equal(calls.length, 1);
});

test('initGlitchtip inferrs dev/release from the app base when no explicit environment', () => {
  resetGlitchtipForTests();
  const calls = [];
  const sentry = {
    init(options) {
      calls.push(options);
    },
  };
  const config = { dsn: 'http://public@monitoring.internal.invalid/3' };
  withConfig(config, () => withLocationPathname('/hr-certflow-dev/dashboard', () => initGlitchtip(sentry)));
  assert.equal(calls[0].environment, 'dev');
});

// ---------- 环境推断 ----------

test('resolveGlitchtipEnvironment prefers explicit config, then app base, then unspecified', () => {
  assert.equal(
    resolveGlitchtipEnvironment({ environment: 'custom-env' }, '/hr-certflow-dev/'),
    'custom-env',
  );
  assert.equal(resolveGlitchtipEnvironment({}, '/hr-certflow-dev/'), 'dev');
  assert.equal(resolveGlitchtipEnvironment({}, '/hr-certflow/dashboard'), 'release');
  assert.equal(resolveGlitchtipEnvironment({}, '/'), 'unspecified');
  assert.equal(resolveGlitchtipEnvironment({}, undefined), 'unspecified');
});

// ---------- beforeSend 脱敏与过滤 ----------

test('sanitizeGlitchtipEvent scrubs sensitive query params from urls', () => {
  const event = {
    request: {
      url: 'http://intranet.example/hr-certflow/dashboard?code=abc123&ticket=t-9&token=tok&SSOTOKEN=sso&keep=yes',
      data: { note: 'ok' },
    },
    breadcrumbs: [
      {
        category: 'xhr',
        data: { url: 'http://intranet.example/hr-certflow/auth/login?code=abc123&keep=yes' },
      },
    ],
  };
  const result = sanitizeGlitchtipEvent(event);
  const url = new URL(result.request.url);
  assert.equal(url.searchParams.get('code'), '[Filtered]');
  assert.equal(url.searchParams.get('ticket'), '[Filtered]');
  assert.equal(url.searchParams.get('token'), '[Filtered]');
  // URL query 键名大小写敏感：保留原键名、只替换取值。
  assert.equal(url.searchParams.get('SSOTOKEN'), '[Filtered]');

  const breadcrumbUrl = new URL(result.breadcrumbs[0].data.url);
  assert.equal(breadcrumbUrl.searchParams.get('code'), '[Filtered]');
  assert.equal(breadcrumbUrl.searchParams.get('keep'), 'yes');
});

test('sanitizeGlitchtipEvent drops authorization/cookie headers and sensitive keys recursively', () => {
  const event = {
    request: {
      headers: {
        Authorization: 'Bearer secret-token',
        Cookie: 'session=abc; other=1',
        'X-Request-Id': 'req-1',
        Accept: 'application/json',
      },
      data: {
        operator: {
          password: 'p',
          idNumber: '3301',
          certificate: { secret: 's', note: 'keep' },
        },
        attachment: { content: 'base64payload', filename: 'keep.pdf' },
      },
    },
    user: { id: '42', username: 'zhangsan', email: 'z@corp.example' },
  };
  const result = sanitizeGlitchtipEvent(event);
  assert.equal('Authorization' in result.request.headers, false);
  assert.equal('Cookie' in result.request.headers, false);
  assert.equal(result.request.headers['X-Request-Id'], 'req-1');
  assert.equal(result.request.headers.Accept, 'application/json');

  assert.equal(result.request.data.operator.password, '[Filtered]');
  assert.equal(result.request.data.operator.idNumber, '[Filtered]');
  assert.equal(result.request.data.operator.certificate.secret, '[Filtered]');
  assert.equal(result.request.data.operator.certificate.note, 'keep');
  assert.equal(result.request.data.attachment.content, '[Filtered]');
  assert.equal(result.request.data.attachment.filename, 'keep.pdf');

  // PII 兜底：sendDefaultPii 关闭后仍不携带 user 身份，HR 系统员工隐私零外泄。
  assert.equal('user' in result, false);
});

test('sanitizeGlitchtipEvent keeps unexpected payload shapes intact instead of throwing', () => {
  assert.equal(sanitizeGlitchtipEvent(undefined), undefined);
  assert.equal(sanitizeGlitchtipEvent(null), null);
  const weird = { request: { headers: 'not-an-object', data: null }, breadcrumbs: 'nope' };
  const result = sanitizeGlitchtipEvent(weird);
  assert.equal(result.request.headers, 'not-an-object');
  assert.equal(result.breadcrumbs, 'nope');
});

test('beforeSend drops auth-login noise but keeps real errors', () => {
  const { beforeSend } = createGlitchtipInitOptions({ dsn: 'http://x@y/1' }, '/');

  // umi request 抛出的 401 AxiosError。
  const axios401 = new Error('Request failed with status code 401');
  axios401.response = { status: 401, data: { detail: { code: 'UNAUTHENTICATED' } } };
  assert.equal(shouldDropGlitchtipEvent({}, { originalException: axios401 }), true);
  assert.equal(beforeSend({}, { originalException: axios401 }), null);

  // errorThrower 的 BizError：401 状态在 info.response.status / info.status。
  const biz401 = new Error('登录已失效');
  biz401.name = 'BizError';
  biz401.info = { response: { status: 401 } };
  assert.equal(shouldDropGlitchtipEvent({}, { originalException: biz401 }), true);

  // jxccs-access 的 SESSION_EXPIRED body（即便外层不是 401 状态）。
  const expired = new Error('session expired');
  expired.info = { data: { detail: { code: 'SESSION_EXPIRED' } } };
  assert.equal(shouldDropGlitchtipEvent({}, { originalException: expired }), true);

  // 普通渲染错误与 5xx 必须保留：那是真正的故障信号。
  assert.equal(shouldDropGlitchtipEvent({}, { originalException: new TypeError('boom') }), false);
  const err500 = new Error('Request failed with status code 500');
  err500.response = { status: 500 };
  assert.equal(shouldDropGlitchtipEvent({}, { originalException: err500 }), false);

  // 无 originalException（例如手工 captureException 传来的 hint）不丢。
  assert.equal(shouldDropGlitchtipEvent({}, {}), false);
});

test('reportErrorToGlitchtip forwards errors only after a successful init', async () => {
  resetGlitchtipForTests();
  const captured = [];
  const sentry = {
    init() {},
    captureException(error, hint) {
      captured.push([error, hint]);
    },
  };

  // 未初始化：完全 no-op，连 sdk 都不会碰。
  await reportErrorToGlitchtip(new Error('unrelated'), { componentStack: 'at X' });
  assert.equal(captured.length, 0);

  const config = { dsn: 'http://public@monitoring.internal.invalid/3' };
  withConfig(config, () => withLocationPathname('/hr-certflow/', () => initGlitchtip(sentry)));
  const renderError = new TypeError('render crashed');
  await reportErrorToGlitchtip(renderError, { componentStack: 'at X' });
  assert.equal(captured.length, 1);
  assert.equal(captured[0][0], renderError);
  assert.equal(captured[0][1].contexts.react.componentStack, 'at X');

  // 上报之后没有泄漏敏感身份。
  assert.equal(sentry.setUser, undefined);
});
