import { Button, Spin, Typography } from 'antd';
import { useEffect, useState, type ReactNode } from 'react';

import { actorProvider } from '@/utils/actorProvider';
import type { ActorState } from '@/utils/actorState';
import { authGateScreen } from '@/utils/authGate';

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
 * 401 且会自动跳登录时保持同一套平滑加载态（redirecting），整个静默 SSO 往返期间
 * 只有一个转圈，既不闪「数据加载失败」红框，也不闪「登录已失效」标题。
 * 只有无法自动跳转（例如刚主动退出命中防循环标记、或当前前缀没有登录入口）才
 * 展示手动登录兜底。只有确认操作人后才渲染业务页面。
 *
 * 路由表里没有需要免鉴权的 SPA 页面：登录与回调是后端 `/auth/*` 的整页跳转，
 * 不经过这里；`NotFound` 也走同一闸门，不影响功能。
 */
export function AuthGate({ children }: AuthGateProps) {
  const [state, setState] = useState<ActorState>(() => actorProvider.getState());

  useEffect(() => actorProvider.subscribe(setState), []);

  const screen = authGateScreen(state);

  if (screen.kind === 'content') {
    return <>{children}</>;
  }

  if (screen.kind === 'spinner') {
    return (
      <div style={frameStyle} role="status">
        <Spin size="large" />
        <Typography.Text type="secondary">{screen.text}</Typography.Text>
      </div>
    );
  }

  if (screen.kind === 'manual-login') {
    return (
      <div style={frameStyle} role="status">
        <Typography.Title level={4} style={{ margin: 0 }}>
          {screen.title}
        </Typography.Title>
        <Typography.Text type="secondary">{screen.description}</Typography.Text>
        {screen.loginUrl ? (
          <Button type="primary" href={screen.loginUrl}>
            前往登录
          </Button>
        ) : null}
      </div>
    );
  }

  return (
    <div style={frameStyle} role="alert">
      <Typography.Title level={4} style={{ margin: 0 }}>
        {screen.title}
      </Typography.Title>
      <Typography.Text type="secondary">{screen.description}</Typography.Text>
      <Button type="primary" onClick={() => window.location.reload()}>
        重新加载
      </Button>
    </div>
  );
}
