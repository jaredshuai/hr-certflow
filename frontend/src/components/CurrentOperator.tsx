import { UserOutlined } from '@ant-design/icons';
import { Tag, Tooltip } from 'antd';
import { useEffect, useState } from 'react';

import { actorProvider } from '@/utils/actorProvider';
import type { ActorState } from '@/utils/actorState';

/** 右上角当前操作人指示器，只展示 GET /me 的结果。 */
export function CurrentOperator() {
  const [state, setState] = useState<ActorState>(() => actorProvider.getState());

  useEffect(() => actorProvider.subscribe(setState), []);

  switch (state.status) {
    case 'loading':
      return null;
    case 'authenticated':
      return (
        <Tag icon={<UserOutlined />} color="blue">
          {state.name}
        </Tag>
      );
    case 'dev-operator':
      return (
        <Tooltip title="开发环境未接入登录，所有操作都记在这个固定开发操作人名下">
          <Tag icon={<UserOutlined />} color="orange">
            开发环境：{state.name}
          </Tag>
        </Tooltip>
      );
    case 'unauthenticated':
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
