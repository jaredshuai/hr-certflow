import { UserOutlined } from '@ant-design/icons';
import { Input, Space, Typography } from 'antd';
import { useEffect, useState } from 'react';

import { getCurrentOperator, setCurrentOperator } from '@/utils/operatorContext';

export function CurrentOperator() {
  const [operator, setOperator] = useState('');

  useEffect(() => {
    setOperator(getCurrentOperator() || '');
  }, []);

  return (
    <Space>
      <Typography.Text>当前操作人</Typography.Text>
      <Input
        aria-label="当前操作人"
        prefix={<UserOutlined />}
        allowClear
        placeholder="用于审计追踪"
        value={operator}
        onChange={(event) => {
          const nextValue = event.target.value;
          setOperator(nextValue);
          setCurrentOperator(nextValue);
        }}
        style={{ width: 180 }}
      />
    </Space>
  );
}
