// 前端错误监控（GlitchTip / Sentry 协议）的运行时接线。
//
// 纪律约束（Item #51）：
// - DSN 不进仓库：构建产物里只有空的 `window.__GLITCHTIP_CONFIG__` 占位，
//   真实 DSN 由部署侧 ConfigMap 覆盖注入；无 DSN 时整体静默、零副作用。
// - 本文件不 import '@sentry/browser'：sdk 只在确认有 DSN 后动态加载，
//   未启用监控的环境连 sdk 字节都不会进主 bundle。
// - 本文件只依赖无运行时依赖的叶子模块，便于 tests/ 下用 node --test 直接运行。

// node --test 需要显式扩展名；umi bundler 模式同样接受。
import { isAuthError } from './apiErrors.ts';

/** 运行时注入的监控配置（由 glitchtip-config.js 写入 window）。 */
export interface GlitchtipConfig {
  dsn?: string;
  environment?: string;
  release?: string;
}

/** 手动上报的附加上下文（对齐 Sentry captureException hint 的最小形状）。 */
type CaptureHint = {
  contexts?: Record<string, Record<string, unknown>>;
} & Record<string, unknown>;

type SentryLike = {
  init?: (options: Record<string, unknown>) => void;
  captureException?: (error: unknown, hint?: CaptureHint) => void;
};

declare global {
  interface Window {
    __GLITCHTIP_CONFIG__?: GlitchtipConfig;
  }
}

// ---------------------------------------------------------------------------
// 环境推断：优先显式 environment，否则按应用前缀区分 dev/release，
// 最后兜底 'unspecified'（本地开发 & 未知前缀），不在源码里写死任何内网地址。
// ---------------------------------------------------------------------------

export function resolveGlitchtipEnvironment(
  config: GlitchtipConfig | undefined,
  pathname: string | undefined,
): string {
  const explicit = config?.environment?.trim();
  if (explicit) return explicit;
  if (typeof pathname === 'string') {
    if (/^\/hr-certflow-dev(\/|$)/.test(pathname)) return 'dev';
    if (/^\/hr-certflow(\/|$)/.test(pathname)) return 'release';
  }
  return 'unspecified';
}

// ---------------------------------------------------------------------------
// beforeSend 脱敏：HR 系统含员工 PII，宁可丢信息也不外泄隐私。
// ---------------------------------------------------------------------------

// URL query 中常见的会话/票据/凭据参数，命中即抹掉取值（保留键名方便判断“被过滤了”）。
// 覆盖 OIDC 回跳参数与 bearer token 常见 URL 形态，大小写不敏感。
const SENSITIVE_QUERY_PARAMS: Record<string, true> = {
  token: true,
  access_token: true,
  refresh_token: true,
  id_token: true,
  ticket: true,
  code: true,
  ssotoken: true,
  session_state: true,
  state: true,
};

// 请求/响应体、extras 等结构里按键名递归脱敏的字段（不区分大小写，键按小写匹配）。
const SENSITIVE_FIELD_NAMES: Record<string, true> = {
  authorization: true,
  cookie: true,
  'set-cookie': true,
  password: true,
  passwd: true,
  secret: true,
  token: true,
  accesstoken: true,
  access_token: true,
  refreshtoken: true,
  refresh_token: true,
  id_token: true,
  idtoken: true,
  sessionid: true,
  session_id: true,
  ssotoken: true,
  ticket: true,
  // 文件内容/识别原文，属员工隐私数据
  content: true,
  body: true,
  idnumber: true,
  idcard: true,
  idcardno: true,
  phone: true,
  mobile: true,
  email: true,
};

const REDACTED = '[Filtered]';
const CIRCULAR = '[Circular]';

function scrubUrl(rawUrl: unknown): unknown {
  if (typeof rawUrl !== 'string' || !rawUrl.includes('?')) return rawUrl;
  try {
    // 相对地址需要一个基址才能解析；只重写 search，基址不进结果。
    const url = new URL(rawUrl, 'http://scrub.invalid');
    let touched = false;
    for (const key of Array.from(url.searchParams.keys())) {
      if (key.toLowerCase() in SENSITIVE_QUERY_PARAMS) {
        url.searchParams.set(key, REDACTED);
        touched = true;
      }
    }
    if (!touched) return rawUrl;
    const serialized = url.toString();
    return rawUrl.startsWith('/') ? serialized.replace(/^https?:\/\/scrub\.invalid/, '') : serialized;
  } catch {
    return rawUrl;
  }
}

// 深度不限的循环安全递归：敏感键在任何层级都被脱敏，循环引用剪断为 [Circular]。
function scrubValue(value: unknown, seen: WeakSet<object>): unknown {
  if (Array.isArray(value)) {
    if (seen.has(value)) return CIRCULAR;
    seen.add(value);
    return value.map((item) => scrubValue(item, seen));
  }
  if (value && typeof value === 'object') {
    if (seen.has(value)) return CIRCULAR;
    seen.add(value);
    const result: Record<string, unknown> = {};
    for (const [key, item] of Object.entries(value as Record<string, unknown>)) {
      result[key] = key.toLowerCase() in SENSITIVE_FIELD_NAMES ? REDACTED : scrubValue(item, seen);
    }
    return result;
  }
  return value;
}

function scrubHeaders(headers: unknown): unknown {
  if (!headers || typeof headers !== 'object' || Array.isArray(headers)) return headers;
  const result: Record<string, unknown> = {};
  for (const [key, item] of Object.entries(headers as Record<string, unknown>)) {
    const lowered = key.toLowerCase();
    if (lowered === 'authorization' || lowered === 'cookie' || lowered === 'set-cookie') continue;
    result[key] = item;
  }
  return result;
}

function scrubBreadcrumbs(breadcrumbs: unknown): unknown {
  if (!Array.isArray(breadcrumbs)) return breadcrumbs;
  return breadcrumbs.map((crumb) => {
    if (!crumb || typeof crumb !== 'object') return crumb;
    const copy: Record<string, unknown> = { ...(crumb as Record<string, unknown>) };
    const data = copy.data;
    if (data && typeof data === 'object' && !Array.isArray(data)) {
      const dataCopy: Record<string, unknown> = { ...(data as Record<string, unknown>) };
      // 导航面包屑的 from/to/url 等字段都可能携带回跳参数：所有字符串值过一遍 query 脱敏。
      for (const [key, item] of Object.entries(dataCopy)) {
        if (typeof item === 'string' && item.includes('?')) {
          dataCopy[key] = scrubUrl(item);
        }
      }
      copy.data = scrubValue(dataCopy, new WeakSet());
    }
    return copy;
  });
}

type SanitizableEvent = Record<string, unknown>;

/**
 * 事件级脱敏（beforeSend 主体）：
 * - 删除 request.headers 里的 Authorization / Cookie / Set-Cookie 与 request.cookies；
 * - URL 与 breadcrumb 字符串字段中的敏感 query 参数值替换为 [Filtered]；
 * - request.data / extra / contexts 循环安全地按键名递归脱敏（不设深度截断）；
 * - 整个 user 字段删除（sendDefaultPii: false 之外的第二道闸）。
 *
 * 异常形态（headers 非对象、缺字段等）一律原样放行，绝不因脱敏自身报错而丢事件。
 */
export function sanitizeGlitchtipEvent<T>(event: T): T {
  if (!event || typeof event !== 'object' || Array.isArray(event)) return event;
  const source = event as SanitizableEvent;
  const result: SanitizableEvent = { ...source };
  delete result.user;

  const request = result.request;
  if (request && typeof request === 'object' && !Array.isArray(request)) {
    const requestCopy: SanitizableEvent = { ...(request as SanitizableEvent) };
    if (typeof requestCopy.url === 'string') {
      requestCopy.url = scrubUrl(requestCopy.url);
    }
    if ('headers' in requestCopy) {
      requestCopy.headers = scrubHeaders(requestCopy.headers);
    }
    if ('data' in requestCopy) {
      requestCopy.data = scrubValue(requestCopy.data, new WeakSet());
    }
    if ('cookies' in requestCopy) {
      delete requestCopy.cookies;
    }
    result.request = requestCopy;
  }

  for (const section of ['extra', 'contexts'] as const) {
    const value = result[section];
    if (value && typeof value === 'object') {
      result[section] = scrubValue(value, new WeakSet());
    }
  }

  result.breadcrumbs = scrubBreadcrumbs(result.breadcrumbs);

  // 顶层 message / logentry 不回写：错误消息本身可能在 detail 中带敏感串，
  // 但它们是排障必要信号；网络输入路径已按 URL 与请求体两道规则处理。
  return result as T;
}

function originalExceptionFrom(hint: unknown): unknown {
  if (!hint || typeof hint !== 'object' || !('originalException' in hint)) return undefined;
  return (hint as { originalException?: unknown }).originalException;
}

/**
 * 401/会话失效是正常登录跳转流程（鉴权闸门已接管），上报只会制造告警噪声；
 * 真正的故障（渲染崩溃、5xx、业务异常）必须保留。
 */
export function shouldDropGlitchtipEvent(_event: unknown, hint: unknown): boolean {
  return isAuthError(originalExceptionFrom(hint));
}

// ---------------------------------------------------------------------------
// 初始化：只有 window.__GLITCHTIP_CONFIG__ 注入了非空 DSN 才启用。
// ---------------------------------------------------------------------------

export function createGlitchtipInitOptions(
  config: GlitchtipConfig,
  pathname: string | undefined,
): Record<string, unknown> {
  const options: Record<string, unknown> = {
    dsn: config.dsn,
    environment: resolveGlitchtipEnvironment(config, pathname),
    // HR 系统含员工 PII：关闭 PII、不开 Session Replay（默认即关闭，保持显式不接入）。
    sendDefaultPii: false,
    beforeSend(event: unknown, hint: unknown) {
      if (shouldDropGlitchtipEvent(event, hint)) return null;
      return sanitizeGlitchtipEvent(event);
    },
  };
  if (config.release?.trim()) {
    options.release = config.release.trim();
  }
  return options;
}

type PendingReport = {
  error: unknown;
  hint?: CaptureHint;
};

// sdk 动态加载完成前到达的上报先入缓冲区（有界），加载完成后按原顺序 flush；
// sdk 加载失败或从未初始化时缓冲自然丢弃——监控是增强，绝不反过来拖垮应用。
const PENDING_REPORT_LIMIT = 20;

type GlitchtipState = {
  initialized: boolean;
  sentry: SentryLike | undefined;
  pending: PendingReport[];
};

const state: GlitchtipState = { initialized: false, sentry: undefined, pending: [] };

/** 单测专用：重置模块级初始化状态。生产代码不得调用。 */
export function resetGlitchtipForTests(): void {
  state.initialized = false;
  state.sentry = undefined;
  state.pending = [];
}

/** sdk 就绪后把缓冲期内积累的上报按原顺序补发，之后上报走直通。 */
export function flushPendingGlitchtipReports(sentry: SentryLike): void {
  state.sentry = sentry;
  if (!sentry.captureException) {
    state.pending = [];
    return;
  }
  const queued = state.pending;
  state.pending = [];
  for (const item of queued) {
    sentry.captureException(item.error, item.hint);
  }
}

function adoptSentry(sentry: SentryLike, options?: Record<string, unknown>): void {
  if (options && sentry.init) {
    sentry.init(options);
  }
  flushPendingGlitchtipReports(sentry);
}

export function initGlitchtip(sentryOverride?: SentryLike): boolean {
  if (state.initialized) return true;
  if (typeof window === 'undefined') return false;
  const config = window.__GLITCHTIP_CONFIG__;
  const dsn = config?.dsn?.trim();
  if (!dsn) return false;

  const pathname = window.location?.pathname;
  const options = createGlitchtipInitOptions({ ...config, dsn }, pathname);

  if (sentryOverride) {
    state.initialized = true;
    adoptSentry(sentryOverride, options);
    return true;
  }

  // 生产路径：sdk 仅在确认启用时动态加载，未配置 DSN 的环境主 bundle 不含它。
  state.initialized = true; // 先置位，避免并发触发重复加载；失败时降级为静默无监控。
  void import('@sentry/browser')
    .then((sdk) => {
      adoptSentry(sdk, options);
    })
    .catch((error) => {
      // 监控是增强而非业务依赖：sdk 加载失败只记日志，绝不影响应用本身。
      state.pending = [];
      console.error('[hr-certflow] GlitchTip SDK 加载失败，已跳过错误监控', error);
    });
  return true;
}

function captureHintFrom(hint?: Record<string, unknown>): CaptureHint | undefined {
  if (!hint) return undefined;
  const result: CaptureHint = { ...hint };
  const componentStack = result.componentStack;
  if (typeof componentStack === 'string') {
    // React ErrorBoundary 的 componentStack 统一收进 contexts.react，与 sentry
    // 官方 React 集成上报的形状一致，脱敏规则也能覆盖 contexts 段。
    delete result.componentStack;
    result.contexts = { ...(result.contexts ?? {}), react: { componentStack } };
  }
  return result;
}

/**
 * ErrorBoundary 等手动上报入口。sdk 就绪前（含从未初始化）先缓冲，
 * init 完成加载后由 flushPendingGlitchtipReports 补发；未启用监控时整体 no-op。
 */
export async function reportErrorToGlitchtip(
  error: unknown,
  hint?: Record<string, unknown>,
): Promise<void> {
  const captureHint = captureHintFrom(hint);
  const sentry = state.sentry;
  if (sentry?.captureException) {
    sentry.captureException(error, captureHint);
    return;
  }
  if (!state.initialized) return;
  if (state.pending.length < PENDING_REPORT_LIMIT) {
    state.pending.push({ error, hint: captureHint });
  }
}
