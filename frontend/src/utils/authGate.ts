// 本文件只依赖类型，便于 tests/ 下用 node --test 直接运行。
//
// 鉴权闸门的唯一判定：只有确认了操作人（真实会话或 dev 固定操作人）才允许挂载
// 业务页面。未确认时不挂载 children，业务页面就不会在 /me 返回前发出首包请求，
// 也不会把 401 渲染成「数据加载失败」。

import type { ActorState } from './actorState';

export type AuthGateMode = 'loading' | 'unauthenticated' | 'error' | 'ready';

export function authGateMode(state: ActorState): AuthGateMode {
  switch (state.status) {
    case 'loading':
      return 'loading';
    case 'authenticated':
    case 'dev-operator':
      return 'ready';
    case 'unauthenticated':
      return 'unauthenticated';
    case 'error':
      return 'error';
  }
}

/** 闸门展示的登录入口：只有未登录状态可能带 loginUrl。 */
export function authGateLoginUrl(state: ActorState): string | undefined {
  return state.status === 'unauthenticated' ? state.loginUrl : undefined;
}
