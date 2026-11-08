import { getResource } from '@/services/api';
import { apiErrorStatus } from '@/utils/apiErrors';
import { actorStateFromErrorStatus, actorStateFromMe, type ActorState, type MeResponse } from '@/utils/actorState';
import { LOGIN_REDIRECT_MARKER_KEY, loginUrlForLocation } from '@/utils/loginRedirect';

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
//   - dev（AUTH_REQUIRED=false）：后端固定开发操作人，界面标明不是真实登录；
//   - 401：未登录。前端不再回退任何 mock 身份，也不向请求写入身份头。
//     网关前缀下首次 401 自动跳转 oauth2-proxy 登录入口；带着防循环标记再次 401
//     时不再跳转，只展示「未登录」和登录链接。
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
      this.state = actorStateFromMe(await getResource<MeResponse>('/me'));
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
}

export const actorProvider = new MeActorProvider();
