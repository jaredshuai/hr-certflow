// 本文件不引用任何其它模块，便于 tests/ 下用 node --test 直接运行。

export interface MeResponse {
  name: string | null;
  source: string | null;
  authenticated: boolean;
}

/** 后端 AUTH_REQUIRED=false（仅 local/dev）时的固定开发操作人来源。 */
export const DEV_OPERATOR_SOURCE = 'dev-unauthenticated';

export type ActorState =
  | { status: 'loading' }
  | { status: 'authenticated'; name: string; source: string | null }
  | { status: 'dev-operator'; name: string }
  | { status: 'unauthenticated' }
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
