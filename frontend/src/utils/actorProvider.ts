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

class MockActorProvider implements ActorProvider {
  getCurrent() {
    if (typeof window === 'undefined') return undefined;
    const name = window.localStorage.getItem('hr-certflow.operator')?.trim();
    return name ? { name, source: 'mock' as const } : undefined;
  }

  requiresManualInput() {
    return true;
  }

  setCurrent(name: string) {
    if (typeof window === 'undefined') return;
    const trimmed = name.trim();
    if (trimmed) {
      window.localStorage.setItem('hr-certflow.operator', trimmed);
    } else {
      window.localStorage.removeItem('hr-certflow.operator');
    }
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
