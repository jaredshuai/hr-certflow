import { UserOutlined } from '@ant-design/icons';
import { Tag } from 'antd';

import { actorProvider } from '@/utils/actorProvider';

/** 右上角当前操作人指示器 */
export function CurrentOperator() {
  const actor = actorProvider.getCurrent();
  if (!actor) return null;

  return (
    <Tag icon={<UserOutlined />} color="blue">
      {actor.name}
    </Tag>
  );
}