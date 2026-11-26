import { LogoutOutlined, UserOutlined } from '@ant-design/icons';
import { Button, Space, Tag, Tooltip } from 'antd';
import { useEffect, useState } from 'react';

import { actorProvider } from '@/utils/actorProvider';
import type { ActorState } from '@/utils/actorState';
import { hasAccessLogout } from '@/utils/loginRedirect';

/** 右上角当前操作人指示器，只展示 GET /me 的结果。 */
export function CurrentOperator() {
  const [state, setState] = useState<ActorState>(() => actorProvider.getState());

  useEffect(() => actorProvider.subscribe(setState), []);

  // 「退出」只在挂了本应用 /auth/logout 的前缀下提供：/hr-certflow（release）与
  // /hr-certflow-dev（dev），以及本地直连根路径；已退役的 /hr-certflow-release 不提供。
  const canLogout = typeof window !== 'undefined' && hasAccessLogout(window.location.pathname);

  switch (state.status) {
    case 'loading':
      return null;
    case 'authenticated':
      return (
        <Space size={4}>
          <Tag icon={<UserOutlined />} color="blue">
            {state.name}
          </Tag>
          {canLogout ? (
            <Button size="small" type="text" icon={<LogoutOutlined />} onClick={() => void actorProvider.logout()}>
              退出
            </Button>
          ) : null}
        </Space>
      );
    case 'dev-operator':
      return (
        <Tooltip title="开发环境未接入登录，所有操作都记在这个固定开发操作人名下" trigger={['hover', 'focus']}>
          <Tag icon={<UserOutlined />} color="orange" tabIndex={0}>
            开发环境：{state.name}
          </Tag>
        </Tooltip>
      );
    case 'unauthenticated':
      // 自动 SSO 跳转期间保持安静，避免右上角再闪一下「未登录」。
      if (state.redirecting) return null;
      return (
        <>
          <Tag color="red">未登录</Tag>
          {state.loginUrl ? <a href={state.loginUrl}>登录</a> : null}
        </>
      );
    case 'error':
      return <Tag color="default">操作人加载失败</Tag>;
  }
}
