export interface HrActor {
  name: string;
  account?: string;          // Casdoor 账号 ID, Mock 期空
  source: 'mock' | 'casdoor';
}

export interface ActorProvider {
  getCurrent(): HrActor | undefined;
  requiresManualInput(): boolean;
  setCurrent?(name: string): void;
}

const MOCK_ACTOR: HrActor = {
  name: 'HR 管理员',
  source: 'mock',
};

// Mock 期模拟 Casdoor 已登录自动注入:
// 固定操作人,不暴露手输框。接 Casdoor 后替换为 CasdoorActorProvider。
class MockActorProvider implements ActorProvider {
  getCurrent() {
    return MOCK_ACTOR;
  }

  requiresManualInput() {
    return false;
  }
}

// 占位: Casdoor 接入时实现并切换
class CasdoorActorProvider implements ActorProvider {
  getCurrent(): undefined {
    return undefined; // 未接入, 返回 undefined
  }

  requiresManualInput() {
    return false;
  }
}

const USE_CASDOOR = process.env.ACTOR_PROVIDER === 'casdoor';
export const actorProvider: ActorProvider = USE_CASDOOR
  ? new CasdoorActorProvider()
  : new MockActorProvider();
