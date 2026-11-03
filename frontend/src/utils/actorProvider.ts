import { getResource } from '@/services/api';
import { apiErrorStatus } from '@/utils/apiErrors';
import { actorStateFromErrorStatus, actorStateFromMe, type ActorState, type MeResponse } from '@/utils/actorState';

type Listener = (state: ActorState) => void;

// 当前操作人只展示 GET /me 的结果：
//   - release：网关 OIDC 登录后注入的可信身份；
//   - dev（AUTH_REQUIRED=false）：后端固定开发操作人，界面标明不是真实登录；
//   - 401：未登录。前端不再回退任何 mock 身份，也不向请求写入身份头。
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
    } catch (error) {
      this.state = actorStateFromErrorStatus(apiErrorStatus(error));
    }
    this.loading = false;
    for (const listener of this.listeners) {
      listener(this.state);
    }
  }
}

export const actorProvider = new MeActorProvider();
