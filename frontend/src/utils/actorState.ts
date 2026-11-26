// 本文件不引用任何其它模块，便于 tests/ 下用 node --test 直接运行。

export interface MeResponse {
  name: string | null;
  source: string | null;
  authenticated: boolean;
  /** 仅 jxccs-access 会话（dev）返回：写请求放进 X-CSRF-Token 头。 */
  csrf_token?: string | null;
}

/** 后端 AUTH_REQUIRED=false（仅 local/dev）时的固定开发操作人来源。 */
export const DEV_OPERATOR_SOURCE = 'dev-unauthenticated';

export type ActorState =
  | { status: 'loading' }
  | { status: 'authenticated'; name: string; source: string | null }
  | { status: 'dev-operator'; name: string }
  /**
   * 未登录。`redirecting` 为 true 表示已经发起自动登录跳转（静默 SSO 往返中），
   * 界面应保持平滑加载态；false/缺省表示停在手动登录兜底（如刚退出、无法自动跳转）。
   */
  | { status: 'unauthenticated'; loginUrl?: string; redirecting?: boolean }
  | { status: 'error' };

/** 当前操作人只来自 GET /me；前端不再有任何 mock 兜底身份。 */
export function actorStateFromMe(me: MeResponse | null | undefined): ActorState {
  if (!me?.name) return { status: 'unauthenticated' };
  if (me.source === DEV_OPERATOR_SOURCE) return { status: 'dev-operator', name: me.name };
  if (me.authenticated) return { status: 'authenticated', name: me.name, source: me.source };
  return { status: 'unauthenticated' };
}

export function actorStateFromErrorStatus(status: number | undefined): ActorState {
  return status === 401 ? { status: 'unauthenticated' } : { status: 'error' };
}

/**
 * 401 之后的未登录状态。
 *
 * 第一次 401 且真的发起了 `window.location.assign` 时 `redirecting=true`，闸门保持
 * 平滑加载态直到文档离开；并发的后续 401（导航已发起、本次 redirectToLoginOnce
 * 返回 false）必须沿用 `redirecting=true`，否则会退回手动登录页闪出「登录已失效」。
 * 只有从未发起跳转（刚退出命中防循环标记、无登录入口）才是手动兜底态。
 */
export function unauthenticatedStateFromRedirect(
  previous: ActorState,
  outcome: { redirected: boolean; loginUrl?: string },
): Extract<ActorState, { status: 'unauthenticated' }> {
  const loginUrl =
    outcome.loginUrl ?? (previous.status === 'unauthenticated' ? previous.loginUrl : undefined);
  const alreadyRedirecting = previous.status === 'unauthenticated' && previous.redirecting === true;
  return {
    status: 'unauthenticated',
    ...(loginUrl ? { loginUrl } : {}),
    redirecting: outcome.redirected || alreadyRedirecting,
  };
}
