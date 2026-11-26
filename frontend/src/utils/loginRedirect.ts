// 本文件不引用任何其它模块，便于 tests/ 下用 node --test 直接运行。

const APP_BASE_PATTERN = /^\/(hr-certflow(?:-dev|-release)?)(\/|$)/;

/** 跳转登录前写入的防循环标记；/me 成功后清除。 */
export const LOGIN_REDIRECT_MARKER_KEY = 'hr-certflow:login-redirect-attempted';

/** 从页面 pathname 取应用前缀（如 `/hr-certflow`）；不在网关前缀下时返回 undefined。 */
export function resolveAppBase(pathname: string): string | undefined {
  const match = pathname.match(APP_BASE_PATTERN);
  return match ? `/${match[1]}` : undefined;
}

/** rd/return_to 只允许应用前缀下的同源路径；否则回到应用首页。 */
export function safeReturnPath(appBase: string, returnPath: string): string {
  const fallback = `${appBase}/`;
  if (returnPath.includes('\\') || returnPath.startsWith('//')) return fallback;
  const pathOnly = returnPath.split(/[?#]/, 1)[0];
  if (pathOnly !== appBase && !pathOnly.startsWith(`${appBase}/`)) return fallback;
  return returnPath;
}

/**
 * 挂了 jxccs-access BFF 的应用前缀：dev 与 release 共用同一份前端镜像，
 * 两个前缀的 `/auth/login`、`/auth/logout` 都由后端提供。
 */
const ACCESS_BASES: readonly string[] = ['/hr-certflow', '/hr-certflow-dev'];

/** 已退役的前缀（含 `-release`）没有登录入口，永不跳转。 */
function isAccessBase(appBase: string): boolean {
  return ACCESS_BASES.includes(appBase);
}

/** jxccs-access BFF 登录入口（后端挂在 `<appBase>/auth/login`）。 */
export function buildAccessLoginUrl(appBase: string, returnPath: string): string {
  return `${appBase}/auth/login?return_to=${encodeURIComponent(safeReturnPath(appBase, returnPath))}`;
}

/**
 * 把后端 401 body 里的 `detail.loginUrl` 变成可跳转的登录地址。
 *
 * 后端下发的是应用自己的登录入口（如 `/hr-certflow/auth/login`），但它是网络
 * 输入：只接受当前应用前缀下的同源相对路径，并强制用当前页面地址覆盖
 * `return_to`，避免被改写成开放重定向。不合格时返回 undefined，由前端用前缀
 * 兜底映射。
 */
export function appendReturnTo(loginUrl: string, appBase: string, returnPath: string): string | undefined {
  const trimmed = loginUrl.trim();
  if (!trimmed.startsWith('/') || trimmed.startsWith('//') || trimmed.includes('\\')) return undefined;
  if (trimmed !== appBase && !trimmed.startsWith(`${appBase}/`)) return undefined;

  let parsed: URL;
  try {
    // 相对地址需要一个基址才能解析；只取 pathname/search，基址不参与结果。
    parsed = new URL(trimmed, 'http://app.invalid');
  } catch {
    return undefined;
  }
  // URL 解析会把 `..`、`%2e%2e` 归一化掉，必须用归一化后的 pathname 再校验一次前缀。
  if (parsed.origin !== 'http://app.invalid') return undefined;
  if (parsed.pathname !== appBase && !parsed.pathname.startsWith(`${appBase}/`)) return undefined;

  parsed.searchParams.set('return_to', safeReturnPath(appBase, returnPath));
  return `${parsed.pathname}${parsed.search}`;
}

export interface LoginRedirectLocation {
  pathname: string;
  search: string;
  hash: string;
}

/**
 * 当前页面对应的登录入口。
 *
 * 优先采用后端 401 body 的 `detail.loginUrl`（网关/后端切换登录路径时前端无需
 * 跟着改）；没有或不合格时回退到按前缀的兜底映射。不在有登录入口的前缀下
 * （本地/直连、已退役前缀）时返回 undefined，不跳转。
 */
export function loginUrlForLocation(
  location: LoginRedirectLocation,
  backendLoginUrl?: string,
): string | undefined {
  const appBase = resolveAppBase(location.pathname);
  if (!appBase || !isAccessBase(appBase)) return undefined;

  const returnPath = `${location.pathname}${location.search}${location.hash}`;
  if (backendLoginUrl) {
    const fromBackend = appendReturnTo(backendLoginUrl, appBase, returnPath);
    if (fromBackend) return fromBackend;
  }
  return buildAccessLoginUrl(appBase, returnPath);
}

/** 挂了后端 jxccs-access `/auth/logout` 的前缀（dev 与 release）；本地直连根路径也可用。 */
export function hasAccessLogout(pathname: string): boolean {
  const appBase = resolveAppBase(pathname);
  return appBase === undefined || isAccessBase(appBase);
}
