import { Button, Spin, Typography } from 'antd';
import { useEffect, useState, type ReactNode } from 'react';

import { actorProvider } from '@/utils/actorProvider';
import type { ActorState } from '@/utils/actorState';
import { authGateLoginUrl, authGateMode } from '@/utils/authGate';

interface AuthGateProps {
  children: ReactNode;
}

const frameStyle = {
  alignItems: 'center',
  display: 'flex',
  flexDirection: 'column',
  gap: 12,
  justifyContent: 'center',
  minHeight: '60vh',
  padding: 24,
  textAlign: 'center',
} as const;

/**
 * 全局鉴权闸门：`app.tsx` 的 `layout.childrenRender` 把每个业务页面包在里面。
 *
 * `/me` 未返回前（loading）不挂载 children，工作台等页面不会抢跑发出首包请求；
 * 401 时切到「登录已失效，请重新登录」占位态，业务页面被卸载，既不会把 401 画成
 * 「数据加载失败」红框，也不会把统计卡片清成 0。只有确认操作人后才渲染业务页面。
 *
 * 路由表里没有需要免鉴权的 SPA 页面：登录与回调是后端 `/auth/*` 的整页跳转，
 * 不经过这里；`NotFound` 也走同一闸门，不影响功能。
 */
export function AuthGate({ children }: AuthGateProps) {
  const [state, setState] = useState<ActorState>(() => actorProvider.getState());

  useEffect(() => actorProvider.subscribe(setState), []);

  const mode = authGateMode(state);
  if (mode === 'ready') {
    return <>{children}</>;
  }

  const loginUrl = authGateLoginUrl(state);

  if (mode === 'loading') {
    return (
      <div style={frameStyle} role="status">
        <Spin size="large" />
        <Typography.Text type="secondary">正在确认登录状态…</Typography.Text>
      </div>
    );
  }

  if (mode === 'unauthenticated') {
    return (
      <div style={frameStyle} role="status">
        <Typography.Title level={4} style={{ margin: 0 }}>
          登录已失效，请重新登录
        </Typography.Title>
        <Typography.Text type="secondary">
          {loginUrl ? '请重新登录后继续使用。' : '当前环境未配置登录入口，请联系管理员。'}
        </Typography.Text>
        {loginUrl ? (
          <Button type="primary" href={loginUrl}>
            前往登录
          </Button>
        ) : null}
      </div>
    );
  }

  return (
    <div style={frameStyle} role="alert">
      <Typography.Title level={4} style={{ margin: 0 }}>
        登录状态加载失败
      </Typography.Title>
      <Typography.Text type="secondary">请检查网络后重试；若持续失败，请联系管理员。</Typography.Text>
      <Button type="primary" onClick={() => window.location.reload()}>
        重新加载
      </Button>
    </div>
  );
}
