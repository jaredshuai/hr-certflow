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

export interface AuthGateView {
  mode: AuthGateMode;
  /** 是否挂载业务页面；只有确认了操作人才为 true。 */
  renderChildren: boolean;
  /** 未登录且当前前缀有登录入口时的手动兜底链接。 */
  loginUrl?: string;
}

/**
 * `AuthGate` 实际渲染所依据的边界：业务页面是否挂载只有这一个出口。
 * 单测直接调用它，避免另写一份判定而在组件回归时仍然全绿。
 */
export function authGateView(state: ActorState): AuthGateView {
  const mode = authGateMode(state);
  return {
    mode,
    renderChildren: mode === 'ready',
    loginUrl: state.status === 'unauthenticated' ? state.loginUrl : undefined,
  };
}
