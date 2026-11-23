import { getResource, postResource } from '@/services/api';
import { apiErrorStatus } from '@/utils/apiErrors';
import { actorStateFromErrorStatus, actorStateFromMe, type ActorState, type MeResponse } from '@/utils/actorState';
import {
  ACCESS_LOGOUT_BASE,
  LOGIN_REDIRECT_MARKER_KEY,
  loginUrlForLocation,
  resolveAppBase,
} from '@/utils/loginRedirect';
import { message } from '@/utils/messageApi';
import { setCsrfToken } from '@/utils/requestHeaders';

type Listener = (state: ActorState) => void;

function hasRedirectMarker(): boolean {
  try {
    return window.sessionStorage.getItem(LOGIN_REDIRECT_MARKER_KEY) !== null;
  } catch {
    return false;
  }
}

/** 写不进 sessionStorage 时无法防循环，返回 false 以放弃自动跳转。 */
function setRedirectMarker(): boolean {
  try {
    window.sessionStorage.setItem(LOGIN_REDIRECT_MARKER_KEY, String(Date.now()));
    return true;
  } catch {
    return false;
  }
}

function removeRedirectMarker() {
  try {
    window.sessionStorage.removeItem(LOGIN_REDIRECT_MARKER_KEY);
  } catch {
    // sessionStorage 不可用时没有标记可清。
  }
}

// 当前操作人只展示 GET /me 的结果：
//   - release：网关 OIDC 登录后注入的可信身份；
//   - dev：后端 jxccs-access 业务会话主体（展示姓名；同时下发写请求用的 CSRF token）；
//   - 未接 SDK 的本地（AUTH_REQUIRED=false）：后端固定开发操作人，界面标明不是真实登录；
//   - 401：未登录。前端不再回退任何 mock 身份，也不向请求写入身份头。
//     有登录入口的前缀下首次 401 自动跳转登录（release：oauth2-proxy；dev：/auth/login）；
//     带着防循环标记再次 401 时不再跳转，只展示「未登录」和登录链接。
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
      removeRedirectMarker();
    } catch (error) {
      this.state = actorStateFromErrorStatus(apiErrorStatus(error));
      if (this.state.status === 'unauthenticated' && this.redirectToLogin()) return;
    }
    this.loading = false;
    for (const listener of this.listeners) {
      listener(this.state);
    }
  }

  /** 返回 true 表示已发起跳转；否则把登录链接放进未登录状态供界面展示。 */
  private redirectToLogin(): boolean {
    if (typeof window === 'undefined') return false;
    const loginUrl = loginUrlForLocation(window.location);
    if (!loginUrl) return false;
    if (!hasRedirectMarker() && setRedirectMarker()) {
      window.location.assign(loginUrl);
      return true;
    }
    this.state = { status: 'unauthenticated', loginUrl };
    return false;
  }

  /**
   * 仅本地退出（G-HR-05）：POST /auth/logout 只销毁本应用业务会话，
   * 不调用 Casdoor/省平台的 end_session，不影响上游和其他应用。
   * 仅 dev 会话前缀（`/hr-certflow-dev`）或本地直连根路径（无网关前缀）提供；
   * release 网关前缀没有该端点，不做退出。
   * 成功后回到应用首页并展示「未登录」；失败时保持登录态并提示，返回 false。
   */
  async logout(): Promise<boolean> {
    if (this.state.status !== 'authenticated' || typeof window === 'undefined') return false;
    // 本地直连没有网关前缀，resolveAppBase 为 undefined，按空字符串直达根下 /auth/logout。
    const appBase = resolveAppBase(window.location.pathname) ?? '';
    if (appBase && appBase !== ACCESS_LOGOUT_BASE) return false;
    try {
      // axios 会给相对路径拼 baseURL（/api/v1），这里用绝对 URL 直达 `${appBase}/auth/logout`。
      await postResource(`${window.location.origin}${appBase}/auth/logout`);
    } catch {
      message.error('退出失败，请稍后重试');
      return false;
    }
    setCsrfToken(null);
    // 写防循环标记：回到首页后 401 不自动跳登录，让用户看到「未登录 + 登录」。
    setRedirectMarker();
    window.location.assign(`${appBase}/`);
    return true;
  }
}

export const actorProvider = new MeActorProvider();
