import { PageContainer, ProTable, type ProColumns } from '@ant-design/pro-components';
import { Button, Space, Tag } from 'antd';

import { listResource } from '@/services/api';
import type { ReviewTask } from '@/types/domain';

const columns: ProColumns<ReviewTask>[] = [
  { title: '文档 ID', dataIndex: 'document_id', ellipsis: true },
  { title: '复核备注', dataIndex: 'notes', ellipsis: true, renderText: (value) => value || '-' },
  {
    title: '状态',
    dataIndex: 'status',
    width: 130,
    render: (_, record) => <Tag color={record.status === 'PENDING' ? 'blue' : 'gold'}>{record.status}</Tag>,
  },
  { title: '创建时间', dataIndex: 'created_at', valueType: 'dateTime', width: 180 },
  {
    title: '操作',
    valueType: 'option',
    width: 160,
    render: () => (
      <Space>
        <Button size="small" type="link">
          复核
        </Button>
        <Button size="small" type="link">
          驳回
        </Button>
      </Space>
    ),
  },
];

export default function ReviewQueuePage() {
  return (
    <PageContainer title="待复核队列">
      <ProTable<ReviewTask>
        rowKey="id"
        columns={columns}
        search={false}
        request={async () => ({
          data: await listResource<ReviewTask>('/reviews'),
          success: true,
        })}
        toolbar={{ title: 'AI 识别后等待 HR 确认的证书' }}
      />
    </PageContainer>
  );
}
