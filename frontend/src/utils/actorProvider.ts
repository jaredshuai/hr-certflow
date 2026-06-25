import { getResource } from '@/services/api';

export interface HrActor {
  name: string;
  account?: string; // Casdoor 账号 ID, Mock 期空
  source: 'mock' | 'casdoor';
}

export interface MeResponse {
  name: string | null;
  source: string | null;
  authenticated: boolean;
}

/** 订阅当前操作人变化的回调,供 React 组件做异步感知。 */
type Listener = (actor: HrActor | undefined) => void;

export interface ActorProvider {
  getCurrent(): HrActor | undefined;
  requiresManualInput(): boolean;
  setCurrent?(name: string): void;
  /** 订阅操作人变化(casdoor 模式异步加载完成时触发)。返回取消订阅函数。 */
  subscribe?(listener: Listener): () => void;
}

// 运行时自适应 actor provider(同镜像 dev/release 共用)。
//
// 为什么不再用构建期 process.env.ACTOR_PROVIDER:
//   dev/release 推同一个镜像 tag,构建期变量无法区分环境。
//   改为运行时探测后端 GET /me:
//   - release(网关 OIDC 已登录):/me 返回 authenticated=true + 真实姓名
//     → 展示 Casdoor 注入的可信身份。
//   - dev(无网关,或后端 auth_required=false 且无人注入 X-HR-Actor):
//     /me 返回 authenticated=false(或 401)→ 回退到 mock「HR 管理员」。
//   这样无需任何环境开关,镜像行为随部署拓扑自动正确。
//
// mock 兜底也用于本地开发,保证右上角始终有操作人展示。
const MOCK_ACTOR: HrActor = {
  name: 'HR 管理员',
  source: 'mock',
};

class RuntimeActorProvider implements ActorProvider {
  // 初始给 mock,保证 mock/dev 场景首屏即有展示;release 探测完成后覆盖。
  private cached: HrActor | undefined = MOCK_ACTOR;
  private loaded = false;
  private loading = false;
  private listeners = new Set<Listener>();

  getCurrent() {
    return this.cached;
  }

  requiresManualInput() {
    return false;
  }

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    this.ensureLoaded();
    return () => {
      this.listeners.delete(listener);
    };
  }

  private ensureLoaded() {
    if (this.loaded || this.loading) return;
    this.loading = true;
    void this.load();
  }

  private async load() {
    try {
      const me = await getResource<MeResponse>('/me');
      if (me.authenticated && me.name) {
        // release:网关已注入可信身份,覆盖 mock。
        this.cached = { name: me.name, source: 'casdoor' };
      } else {
        // dev/未认证:保持 mock 兜底。
        this.cached = MOCK_ACTOR;
      }
    } catch {
      // /me 401(AUTH_REQUIRED=true 且网关未登录)或网络错误 → mock 兜底。
      this.cached = MOCK_ACTOR;
    }
    this.loaded = true;
    this.loading = false;
    this.emit();
  }

  private emit() {
    for (const listener of this.listeners) {
      listener(this.cached);
    }
  }
}

export const actorProvider: ActorProvider = new RuntimeActorProvider();
