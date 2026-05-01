import { PageContainer, ProTable, type ProColumns } from '@ant-design/pro-components';
import { Button, Space, Tag } from 'antd';

import { listResource } from '@/services/api';
import type { ReminderTask } from '@/types/domain';

const statusColor: Record<string, string> = {
  PENDING: 'default',
  FIRST_SENT: 'blue',
  WAITING_FEEDBACK: 'gold',
  SECOND_SENT: 'orange',
  ESCALATED: 'red',
  RESOLVED: 'green',
  CLOSED: 'default',
};

const columns: ProColumns<ReminderTask>[] = [
  { title: '证书记录', dataIndex: 'employee_certificate_id', ellipsis: true },
  { title: '触发日期', dataIndex: 'trigger_date', valueType: 'date', width: 130 },
  { title: '反馈截止', dataIndex: 'due_date', valueType: 'date', width: 130 },
  {
    title: '状态',
    dataIndex: 'status',
    width: 150,
    render: (_, record) => <Tag color={statusColor[record.status]}>{record.status}</Tag>,
  },
  { title: '关闭原因', dataIndex: 'closed_reason', search: false },
  {
    title: 'HR 反馈',
    valueType: 'option',
    width: 180,
    render: () => (
      <Space>
        <Button size="small" type="link">
          已通知
        </Button>
        <Button size="small" type="link">
          已换证
        </Button>
      </Space>
    ),
  },
];

export default function RemindersPage() {
  return (
    <PageContainer title="提醒任务">
      <ProTable<ReminderTask>
        rowKey="id"
        columns={columns}
        request={async () => ({
          data: await listResource<ReminderTask>('/reminders/tasks'),
          success: true,
        })}
        toolbar={{ title: '到期提醒闭环' }}
        search={{ labelWidth: 88 }}
      />
    </PageContainer>
  );
}
