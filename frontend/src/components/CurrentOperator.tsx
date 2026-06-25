import { UserOutlined } from '@ant-design/icons';
import { Tag } from 'antd';
import { useEffect, useState } from 'react';

import { actorProvider, type HrActor } from '@/utils/actorProvider';

/** 右上角当前操作人指示器。

 * - mock 模式:同步返回固定操作人,首屏即显示。
 * - casdoor 模式:网关 OIDC 注入身份,前端通过 /me 异步读取,
 *   加载完成后再显示;未登录时不显示。
 */
export function CurrentOperator() {
  const [actor, setActor] = useState<HrActor | undefined>(() => actorProvider.getCurrent());

  useEffect(() => {
    if (!actorProvider.subscribe) return;
    return actorProvider.subscribe(setActor);
  }, []);

  if (!actor) return null;

  return (
    <Tag icon={<UserOutlined />} color="blue">
      {actor.name}
    </Tag>
  );
}
