import { PageContainer, ProTable, type ActionType, type ProColumns } from '@ant-design/pro-components';
import { Alert, Button, Input, Space, Typography } from 'antd';
import { useRef, useState } from 'react';

import { listResource, postResource } from '@/services/api';
import type { FeedbackStatus, ReminderTask } from '@/types/domain';
import { reminderStatusValueEnum } from '@/utils/displayLabels';
import { emptyTableText } from '@/utils/emptyStates';
import { message } from '@/utils/messageApi';

const feedbackActions: Array<{ label: string; status: FeedbackStatus; content: string; danger?: boolean }> = [
  { label: '已通知', status: 'NOTIFIED_EMPLOYEE', content: '人力已通知员工' },
  { label: '办理中', status: 'PROCESSING', content: '员工证书正在办理' },
  { label: '已换证', status: 'RENEWED', content: '员工已完成换证' },
  { label: '无需处理', status: 'NO_ACTION_REQUIRED', content: '人力确认无需处理' },
  { label: '员工离职', status: 'EMPLOYEE_LEFT', content: '员工已离职，关闭提醒' },
  { label: '忽略', status: 'IGNORED', content: '人力忽略本次提醒', danger: true },
];

export default function RemindersPage() {
  const actionRef = useRef<ActionType>();
  const [submittingId, setSubmittingId] = useState<string>();
  const [feedbackActor, setFeedbackActor] = useState('');
  const [loadError, setLoadError] = useState<string>();

  async function submitFeedback(record: ReminderTask, status: FeedbackStatus, content: string) {
    const actor = feedbackActor.trim();
    if (!actor) {
      message.warning('请先填写反馈人');
      return;
    }

    setSubmittingId(`${record.id}:${status}`);
    try {
      await postResource(`/reminders/tasks/${record.id}/feedback`, {
        status,
        content,
        created_by: actor,
      });
      message.success('人力反馈已记录');
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
      valueType: 'select',
      valueEnum: reminderStatusValueEnum,
    },
    { title: '关闭原因', dataIndex: 'closed_reason', search: false },
    {
      title: '人力反馈',
      valueType: 'option',
      width: 420,
      render: (_, record) => (
        <Space wrap>
          {feedbackActions.map((action) => (
            <Button
              key={action.status}
              size="small"
              type="link"
              danger={action.danger}
              loading={submittingId === `${record.id}:${action.status}`}
              onClick={() => void submitFeedback(record, action.status, action.content)}
            >
              {action.label}
            </Button>
          ))}
        </Space>
      ),
    },
  ];

  return (
    <PageContainer title="提醒任务">
      {loadError ? (
        <Alert
          type="error"
          showIcon
          title="提醒任务加载失败"
          description={loadError}
          style={{ marginBottom: 16 }}
          closable={{ onClose: () => setLoadError(undefined) }}
        />
      ) : null}
      <ProTable<ReminderTask>
        actionRef={actionRef}
        rowKey="id"
        columns={columns}
        request={async () => {
          try {
            const data = await listResource<ReminderTask>('/reminders/tasks');
            setLoadError(undefined);
            return { data, success: true };
          } catch (error) {
            const description = error instanceof Error ? error.message : '提醒任务加载失败';
            setLoadError(description);
            message.error(description);
            return { data: [], success: false };
          }
        }}
        locale={{ emptyText: emptyTableText('暂无提醒任务，系统会在证书临期或过期时生成') }}
        toolbar={{
          title: '到期提醒闭环',
          actions: [
            <Space key="feedback-actor">
              <Typography.Text>反馈人</Typography.Text>
              <Input
                aria-label="反馈人"
                value={feedbackActor}
                onChange={(event) => setFeedbackActor(event.target.value)}
                style={{ width: 120 }}
              />
            </Space>,
          ],
        }}
        search={{ labelWidth: 88 }}
      />
    </PageContainer>
  );
}
