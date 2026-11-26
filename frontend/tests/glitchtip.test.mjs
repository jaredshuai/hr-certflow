import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  createGlitchtipInitOptions,
  flushPendingGlitchtipReports,
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
    } else {
      // 首个用例注入的是自有属性；不删掉会让 pathname 泄漏给后续用例，形成顺序依赖。
      delete window.location;
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

// ---------- cubic 评审收敛（PR #49 首轮） ----------

test('sanitizeGlitchtipEvent scrubs bearer-token style query params (access_token/refresh_token/session_state)', () => {
  const event = {
    request: {
      url: 'http://intranet.example/hr-certflow/cb?access_token=a1&refresh_token=r2&session_state=s3&keep=yes',
    },
  };
  const result = sanitizeGlitchtipEvent(event);
  const url = new URL(result.request.url);
  assert.equal(url.searchParams.get('access_token'), '[Filtered]');
  assert.equal(url.searchParams.get('refresh_token'), '[Filtered]');
  assert.equal(url.searchParams.get('session_state'), '[Filtered]');
  assert.equal(url.searchParams.get('keep'), 'yes');
});

test('sanitizeGlitchtipEvent redacts camelCase token spellings in request bodies', () => {
  const event = {
    request: {
      data: {
        auth: {
          idToken: 'id-t',
          accessToken: 'a-t',
          refreshToken: 'r-t',
          operatorName: 'keep',
        },
      },
    },
  };
  const auth = sanitizeGlitchtipEvent(event).request.data.auth;
  assert.equal(auth.idToken, '[Filtered]');
  assert.equal(auth.accessToken, '[Filtered]');
  assert.equal(auth.refreshToken, '[Filtered]');
  assert.equal(auth.operatorName, 'keep');
});

test('sanitizeGlitchtipEvent redacts sessionId/session_id and idToken/id_token across body, extra and contexts', () => {
  const event = {
    request: {
      data: {
        auth: {
          sessionId: 'sess-camel',
          session_id: 'sess-snake',
          idToken: 'id-camel',
          id_token: 'id-snake',
          operatorName: 'keep',
        },
      },
    },
    extra: { sessionId: 'sess-extra', idToken: 'id-extra', note: 'keep' },
    contexts: { runtime: { session_id: 'sess-ctx', id_token: 'id-ctx', name: 'keep' } },
  };
  const result = sanitizeGlitchtipEvent(event);

  const auth = result.request.data.auth;
  assert.equal(auth.sessionId, '[Filtered]');
  assert.equal(auth.session_id, '[Filtered]');
  assert.equal(auth.idToken, '[Filtered]');
  assert.equal(auth.id_token, '[Filtered]');
  assert.equal(auth.operatorName, 'keep');

  assert.equal(result.extra.sessionId, '[Filtered]');
  assert.equal(result.extra.idToken, '[Filtered]');
  assert.equal(result.extra.note, 'keep');

  assert.equal(result.contexts.runtime.session_id, '[Filtered]');
  assert.equal(result.contexts.runtime.id_token, '[Filtered]');
  assert.equal(result.contexts.runtime.name, 'keep');
});

test('sanitizeGlitchtipEvent drops serialized string request bodies instead of forwarding them verbatim', () => {
  // sentry 浏览器集成常把 body 序列化成字符串：JSON、form-encoded、multipart。
  // 字符串形态无法按键脱敏，HR PII 底线是直接整段丢弃。
  const json = sanitizeGlitchtipEvent({ request: { data: '{"password":"p","name":"张三"}' } });
  assert.equal(json.request.data, '[Filtered]');

  const form = sanitizeGlitchtipEvent({ request: { data: 'password=p&idNumber=3301' } });
  assert.equal(form.request.data, '[Filtered]');

  // 非字符串结构仍走原有的按键递归脱敏，不被误伤。
  const objectBody = sanitizeGlitchtipEvent({ request: { data: { note: 'keep', password: 'p' } } });
  assert.equal(objectBody.request.data.note, 'keep');
  assert.equal(objectBody.request.data.password, '[Filtered]');
});

test('sanitizeGlitchtipEvent redacts sensitive keys at arbitrary depth without a depth cutoff', () => {
  let node = { password: 'deep-secret' };
  for (let i = 0; i < 12; i += 1) {
    node = { nest: node };
  }
  const result = sanitizeGlitchtipEvent({ request: { data: node } });
  let cursor = result.request.data;
  for (let i = 0; i < 12; i += 1) {
    cursor = cursor.nest;
  }
  assert.equal(cursor.password, '[Filtered]');
});

test('sanitizeGlitchtipEvent survives circular references without hanging or leaking', () => {
  const payload = { secret: 's', note: 'keep' };
  payload.self = payload;
  const result = sanitizeGlitchtipEvent({ extra: payload });
  assert.equal(result.extra.secret, '[Filtered]');
  assert.equal(result.extra.note, 'keep');
  // 循环引用被剪断而不是无限递归。
  assert.equal(result.extra.self, '[Circular]');
});

test('sanitizeGlitchtipEvent scrubs query values in every url-bearing breadcrumb field', () => {
  const event = {
    breadcrumbs: [
      {
        category: 'navigation',
        data: {
          from: '/hr-certflow/login?code=abc',
          to: '/hr-certflow/dashboard?ticket=t-1',
          url: 'http://intranet.example/x?token=tok',
        },
      },
    ],
  };
  const crumb = sanitizeGlitchtipEvent(event).breadcrumbs[0];
  assert.match(crumb.data.from, /code=%5BFiltered%5D|code=\[Filtered\]/);
  assert.match(crumb.data.to, /ticket=%5BFiltered%5D|ticket=\[Filtered\]/);
  const url = new URL(crumb.data.url);
  assert.equal(url.searchParams.get('token'), '[Filtered]');
});

test('reportErrorToGlitchtip buffers render errors raised while the sdk is still loading, then flushes', async () => {
  resetGlitchtipForTests();
  const captured = [];
  const sentry = {
    captureException(error, hint) {
      captured.push([error, hint]);
    },
  };
  // dsn 已注入、init 已判定启用，但 sdk 实例还没就绪（动态 import 还在路上）。
  const initSentry = {
    init() {},
    // 注意：captureException 缺席——模拟 sdk 尚未 adopt 的状态由单独调用
    // flushPendingGlitchtipReports 补齐（生产里即 import().then 的路径）。
  };
  withConfig({ dsn: 'http://public@monitoring.internal.invalid/3' }, () =>
    withLocationPathname('/hr-certflow/', () => initGlitchtip(initSentry)),
  );

  // sdk 尚未就绪（dsn 已注入、动态 import 还在路上）时的渲染崩溃绝不能丢：
  // 这正是首屏白屏路径。
  const early = new TypeError('first-render crash');
  await reportErrorToGlitchtip(early, { componentStack: 'at App' });

  // 模拟 sdk 动态加载完成（生产里由 init 的 import().then 触发同一条 flush 路径）。
  flushPendingGlitchtipReports(sentry);

  assert.equal(captured.length, 1);
  assert.equal(captured[0][0], early);
  assert.equal(captured[0][1].contexts.react.componentStack, 'at App');

  // 缓冲区只 flush 一次，后续上报走直通。
  const later = new Error('later');
  await reportErrorToGlitchtip(later);
  assert.equal(captured.length, 2);
  assert.equal(captured[1][0], later);
});
