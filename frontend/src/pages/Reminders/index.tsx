import { PageContainer, ProTable, type ActionType, type ProColumns } from '@ant-design/pro-components';
import { Button, Space, Tag, message } from 'antd';
import { useRef, useState } from 'react';

import { listResource, postResource } from '@/services/api';
import type { FeedbackStatus, ReminderTask } from '@/types/domain';

const statusColor: Record<string, string> = {
  PENDING: 'default',
  FIRST_SENT: 'blue',
  WAITING_FEEDBACK: 'gold',
  SECOND_SENT: 'orange',
  ESCALATED: 'red',
  RESOLVED: 'green',
  CLOSED: 'default',
};

export default function RemindersPage() {
  const actionRef = useRef<ActionType>();
  const [submittingId, setSubmittingId] = useState<string>();

  async function submitFeedback(record: ReminderTask, status: FeedbackStatus, content: string) {
    setSubmittingId(`${record.id}:${status}`);
    try {
      await postResource(`/reminders/tasks/${record.id}/feedback`, {
        status,
        content,
        created_by: 'hr',
      });
      message.success('HR 反馈已记录');
      actionRef.current?.reload();
    } catch (error) {
      message.error(error instanceof Error ? error.message : '反馈提交失败');
    } finally {
      setSubmittingId(undefined);
    }
  }

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
      width: 220,
      render: (_, record) => (
        <Space>
          <Button
            size="small"
            type="link"
            loading={submittingId === `${record.id}:NOTIFIED_EMPLOYEE`}
            onClick={() => void submitFeedback(record, 'NOTIFIED_EMPLOYEE', 'HR 已通知员工')}
          >
            已通知
          </Button>
          <Button
            size="small"
            type="link"
            loading={submittingId === `${record.id}:RENEWED`}
            onClick={() => void submitFeedback(record, 'RENEWED', '员工已完成换证')}
          >
            已换证
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <PageContainer title="提醒任务">
      <ProTable<ReminderTask>
        actionRef={actionRef}
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
