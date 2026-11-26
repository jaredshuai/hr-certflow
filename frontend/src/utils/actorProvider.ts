import { getResource, postResource } from '@/services/api';
import { apiErrorLoginUrl, apiErrorStatus, isAuthError } from '@/utils/apiErrors';
import { actorStateFromErrorStatus, actorStateFromMe, type ActorState, type MeResponse } from '@/utils/actorState';
import {
  clearRedirectMarker,
  hasAccessLogout,
  redirectToLoginOnce,
  resolveAppBase,
  setRedirectMarker,
  type RedirectEnvironment,
  type RedirectStorage,
} from '@/utils/loginRedirect';
import { message } from '@/utils/messageApi';
import { setCsrfToken } from '@/utils/requestHeaders';

type Listener = (state: ActorState) => void;

function browserStorage(): RedirectStorage | null {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

function redirectEnvironment(): RedirectEnvironment {
  return {
    location: window.location,
    storage: browserStorage(),
    assign: (url) => window.location.assign(url),
  };
}

// 当前操作人只展示 GET /me 的结果：
//   - 真实会话（dev/release 均由后端 jxccs-access 提供 OIDC 业务会话）：展示姓名，
//     同时下发写请求用的 CSRF token；
//   - 未接 SDK 的本地（AUTH_REQUIRED=false）：后端固定开发操作人，界面标明不是真实登录；
//   - 401：未登录。前端不再回退任何 mock 身份，也不向请求写入身份头。
//     有登录入口的前缀下首次 401 自动跳转登录（优先用 401 body 的 detail.loginUrl，
//     回退 `<前缀>/auth/login`）；带着防循环标记再次 401 时不再跳转，只展示
//     「未登录」和登录链接。
class MeActorProvider {
  private state: ActorState = { status: 'loading' };
  private loading = false;
  private listeners = new Set<Listener>();

  getState() {
    return this.state;
  }

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    this.ensureLoaded();
    return () => {
      this.listeners.delete(listener);
    };
  }

  private notify() {
    for (const listener of this.listeners) {
      listener(this.state);
    }
  }

  private ensureLoaded() {
    if (this.state.status !== 'loading' || this.loading) return;
    this.loading = true;
    void this.load();
  }

  private async load() {
    try {
      const me = await getResource<MeResponse>('/me');
      setCsrfToken(me?.csrf_token);
      this.state = actorStateFromMe(me);
      clearRedirectMarker(browserStorage());
    } catch (error) {
      this.loading = false;
      if (isAuthError(error)) {
        this.handleAuthError(error);
        return;
      }
      this.state = actorStateFromErrorStatus(apiErrorStatus(error));
      this.notify();
      return;
    }
    this.loading = false;
    this.notify();
  }

  /**
   * 401 / 会话失效的统一入口：切到「未登录」并触发登录跳转。
   *
   * 请求层（app.tsx 的 errorConfig.errorHandler）与 /me 的首包都走这里；
   * `redirectToLoginOnce` 的防重入标记保证并发的多个 401 只导航一次。
   * 返回 true 表示本次真的发起了跳转。
   */
  handleAuthError(error: unknown): boolean {
    if (typeof window === 'undefined') return false;
    const outcome = redirectToLoginOnce(redirectEnvironment(), apiErrorLoginUrl(error));
    this.loading = false;
    this.state = outcome.loginUrl
      ? { status: 'unauthenticated', loginUrl: outcome.loginUrl }
      : { status: 'unauthenticated' };
    this.notify();
    return outcome.redirected;
  }

  /**
   * 仅本地退出（G-HR-05）：POST /auth/logout 只销毁本应用业务会话，
   * 不调用 Casdoor/省平台的 end_session，不影响上游和其他应用。
   * dev 与 release 前缀都由后端 jxccs-access 提供该端点；本地直连根路径同样可用。
   * 成功后回到应用首页并展示「未登录」；失败时保持登录态并提示，返回 false。
   */
  async logout(): Promise<boolean> {
    if (this.state.status !== 'authenticated' || typeof window === 'undefined') return false;
    if (!hasAccessLogout(window.location.pathname)) return false;
    // 本地直连没有网关前缀，resolveAppBase 为 undefined，按空字符串直达根下 /auth/logout。
    const appBase = resolveAppBase(window.location.pathname) ?? '';
    try {
      // axios 会给相对路径拼 baseURL（/api/v1），这里用绝对 URL 直达 `${appBase}/auth/logout`。
      await postResource(`${window.location.origin}${appBase}/auth/logout`);
    } catch {
      message.error('退出失败，请稍后重试');
      return false;
    }
    setCsrfToken(null);
    // 写防循环标记：回到首页后 401 不自动跳登录，让用户看到「未登录 + 登录」。
    setRedirectMarker(browserStorage());
    window.location.assign(`${appBase}/`);
    return true;
  }
}

export const actorProvider = new MeActorProvider();
