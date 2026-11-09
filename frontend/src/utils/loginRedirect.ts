// 本文件不引用任何其它模块，便于 tests/ 下用 node --test 直接运行。

const APP_BASE_PATTERN = /^\/(hr-certflow(?:-dev|-release)?)(\/|$)/;

/** 跳转登录前写入的防循环标记；/me 成功后清除。 */
export const LOGIN_REDIRECT_MARKER_KEY = 'hr-certflow:login-redirect-attempted';

/** 从页面 pathname 取应用前缀（如 `/hr-certflow`）；不在网关前缀下时返回 undefined。 */
export function resolveAppBase(pathname: string): string | undefined {
  const match = pathname.match(APP_BASE_PATTERN);
  return match ? `/${match[1]}` : undefined;
}

/** rd 只允许应用前缀下的同源路径；否则回到应用首页。 */
export function safeReturnPath(appBase: string, returnPath: string): string {
  const fallback = `${appBase}/`;
  if (returnPath.includes('\\') || returnPath.startsWith('//')) return fallback;
  const pathOnly = returnPath.split(/[?#]/, 1)[0];
  if (pathOnly !== appBase && !pathOnly.startsWith(`${appBase}/`)) return fallback;
  return returnPath;
}

export function buildLoginUrl(appBase: string, returnPath: string): string {
  return `${appBase}/oauth2/start?rd=${encodeURIComponent(safeReturnPath(appBase, returnPath))}`;
}

export interface LoginRedirectLocation {
  pathname: string;
  search: string;
  hash: string;
}

/** jxccs-access BFF 登录入口（#33 第 3 步，后端挂在 `<appBase>/auth/login`）。 */
export function buildAccessLoginUrl(appBase: string, returnPath: string): string {
  return `${appBase}/auth/login?return_to=${encodeURIComponent(safeReturnPath(appBase, returnPath))}`;
}

/**
 * 各前缀的登录入口：release 前缀走 oauth2-proxy 网关登录；dev 前缀走后端 jxccs-access 登录。
 * 其它前缀（含已退役的 -release）没有登录入口，永不跳转。
 */
const LOGIN_ENTRIES: Record<string, (appBase: string, returnPath: string) => string> = {
  '/hr-certflow': buildLoginUrl,
  '/hr-certflow-dev': buildAccessLoginUrl,
};

/** 当前页面对应的登录入口；不在有登录入口的前缀下（本地/直连）时返回 undefined，不跳转。 */
export function loginUrlForLocation(location: LoginRedirectLocation): string | undefined {
  const appBase = resolveAppBase(location.pathname);
  const entry = appBase ? LOGIN_ENTRIES[appBase] : undefined;
  if (!appBase || !entry) return undefined;
  return entry(appBase, `${location.pathname}${location.search}${location.hash}`);
}
