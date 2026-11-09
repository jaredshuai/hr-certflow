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

/** 只有 release 前缀挂了 oauth2-proxy 登录入口；dev 不接登录，永不跳转。 */
const GATEWAY_LOGIN_APP_BASES = new Set(['/hr-certflow']);

/** 当前页面对应的登录入口；不在网关登录前缀下（本地/直连/dev）时返回 undefined，不跳转。 */
export function loginUrlForLocation(location: LoginRedirectLocation): string | undefined {
  const appBase = resolveAppBase(location.pathname);
  if (!appBase || !GATEWAY_LOGIN_APP_BASES.has(appBase)) return undefined;
  return buildLoginUrl(appBase, `${location.pathname}${location.search}${location.hash}`);
}
