// 本文件只依赖类型，便于 tests/ 下用 node --test 直接运行。
//
// 鉴权闸门的唯一判定：只有确认了操作人（真实会话或 dev 固定操作人）才允许挂载
// 业务页面。未确认时不挂载 children，业务页面就不会在 /me 返回前发出首包请求，
// 也不会把 401 渲染成「数据加载失败」。

import type { ActorState } from './actorState';

export type AuthGateMode = 'loading' | 'redirecting' | 'unauthenticated' | 'error' | 'ready';

export function authGateMode(state: ActorState): AuthGateMode {
  switch (state.status) {
    case 'loading':
      return 'loading';
    case 'authenticated':
    case 'dev-operator':
      return 'ready';
    case 'unauthenticated':
      // 自动 SSO 跳转期间（redirecting）与首包 /me 查询同属「等待中」，
      // 不能展示「登录已失效」。
      return state.redirecting === true ? 'redirecting' : 'unauthenticated';
    case 'error':
      return 'error';
  }
}

/**
 * `AuthGate` 实际渲染所依据的屏幕描述。业务页面是否挂载、看到什么文案只有这里
 * 一个出口；单测直接调用它，避免另写一份判定而在组件回归时仍然全绿。
 */
export type AuthGateScreen =
  | { kind: 'content' }
  | { kind: 'spinner'; text: string }
  | { kind: 'manual-login'; title: string; description: string; loginUrl?: string }
  | { kind: 'error'; title: string; description: string };

export function authGateScreen(state: ActorState): AuthGateScreen {
  switch (authGateMode(state)) {
    case 'ready':
      return { kind: 'content' };
    case 'loading':
      return { kind: 'spinner', text: '正在确认登录状态…' };
    case 'redirecting':
      return { kind: 'spinner', text: '正在跳转登录…' };
    case 'unauthenticated': {
      const loginUrl = state.status === 'unauthenticated' ? state.loginUrl : undefined;
      return {
        kind: 'manual-login',
        title: '登录已失效，请重新登录',
        description: loginUrl ? '请重新登录后继续使用。' : '当前环境未配置登录入口，请联系管理员。',
        ...(loginUrl ? { loginUrl } : {}),
      };
    }
    case 'error':
      return {
        kind: 'error',
        title: '登录状态加载失败',
        description: '请检查网络后重试；若持续失败，请联系管理员。',
      };
  }
}
