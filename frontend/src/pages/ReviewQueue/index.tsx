import { PageContainer, ProTable, type ProColumns } from '@ant-design/pro-components';
import { Button, Space, Tag } from 'antd';

interface ReviewRow {
  id: string;
  document: string;
  reason: string;
  status: 'PENDING' | 'NEEDS_INFO';
  created_at: string;
}

const columns: ProColumns<ReviewRow>[] = [
  { title: '文件', dataIndex: 'document' },
  { title: '复核原因', dataIndex: 'reason' },
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
      <ProTable<ReviewRow>
        rowKey="id"
        columns={columns}
        search={false}
        request={async () => ({
          data: [
            {
              id: 'sample-1',
              document: '安全生产资格证-张三.pdf',
              reason: '姓名匹配失败 / 低可信结果',
              status: 'PENDING',
              created_at: new Date().toISOString(),
            },
          ],
          success: true,
        })}
        toolbar={{ title: 'AI 识别后等待 HR 确认的证书' }}
      />
    </PageContainer>
  );
}
