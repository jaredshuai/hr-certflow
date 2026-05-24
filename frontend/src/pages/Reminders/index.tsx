import {
  ModalForm,
  PageContainer,
  ProCard,
  ProFormDigit,
  ProFormSelect,
  ProFormSwitch,
  ProFormText,
  ProTable,
  type ActionType,
  type ProColumns,
} from '@ant-design/pro-components';
import { Alert, Button, Descriptions, Drawer, Empty, Input, Space, Timeline, Typography } from 'antd';
import { useMemo, useRef, useState } from 'react';

import { useLocation } from '@umijs/max';

import { createResource, getResource, listResource, postResource, updateResource } from '@/services/api';
import type {
  FeedbackStatus,
  ReminderDispatchPayload,
  ReminderDispatchResult,
  ReminderPolicy,
  ReminderTask,
  ReminderTaskScanPayload,
  ReminderTaskScanResult,
  ReminderTaskStatus,
  ReminderTaskTimeline,
} from '@/types/domain';
import {
  feedbackStatusLabel,
  reminderEventTypeLabel,
  reminderStatusLabel,
  reminderStatusValueEnum,
} from '@/utils/displayLabels';
import { emptyTableText } from '@/utils/emptyStates';
import { certificateTypeSelectRequest } from '@/utils/formOptions';
import { message } from '@/utils/messageApi';
import { getCurrentOperator } from '@/utils/operatorContext';

const feedbackActions: Array<{ label: string; status: FeedbackStatus; content: string; danger?: boolean }> = [
  { label: '已通知', status: 'NOTIFIED_EMPLOYEE', content: '人力已通知员工' },
  { label: '办理中', status: 'PROCESSING', content: '员工证书正在办理' },
  { label: '已换证', status: 'RENEWED', content: '员工已完成换证' },
  { label: '无需处理', status: 'NO_ACTION_REQUIRED', content: '人力确认无需处理' },
  { label: '员工离职', status: 'EMPLOYEE_LEFT', content: '员工已离职，关闭提醒' },
  { label: '忽略', status: 'IGNORED', content: '人力忽略本次提醒', danger: true },
];

const reminderChannelOptions = [
  { label: '邮件', value: 'email' },
  { label: '企业微信', value: 'wecom' },
  { label: '钉钉', value: 'dingtalk' },
  { label: '飞书', value: 'feishu' },
];

type ReminderPolicyFormValues = {
  certificate_type_id?: string;
  name: string;
  days_before_expiry_text: string;
  second_reminder_after_days: number;
  escalation_after_days: number;
  channels: string[];
  enabled: boolean;
};

function parseDaysBeforeExpiry(value: string): number[] {
  const days = value
    .split(/[,\s，]+/)
    .map((item) => item.trim())
    .filter(Boolean)
    .map((item) => Number(item));
  if (days.length === 0 || days.some((item) => !Number.isInteger(item) || item < 0)) {
    throw new Error('提前提醒天数必须是非负整数，可用逗号分隔');
  }
  return [...new Set(days)].sort((left, right) => right - left);
}

export default function RemindersPage() {
  const actionRef = useRef<ActionType>();
  const policyActionRef = useRef<ActionType>();
  const location = useLocation();
  const [submittingId, setSubmittingId] = useState<string>();
  const [scanning, setScanning] = useState(false);
  const [feedbackActor, setFeedbackActor] = useState('');
  const [dispatchOperator, setDispatchOperator] = useState('');
  const [loadError, setLoadError] = useState<string>();
  const [policyLoadError, setPolicyLoadError] = useState<string>();
  const [policyOpen, setPolicyOpen] = useState(false);
  const [currentPolicy, setCurrentPolicy] = useState<ReminderPolicy>();
  const [timelineOpen, setTimelineOpen] = useState(false);
  const [timelineLoading, setTimelineLoading] = useState(false);
  const [currentTimeline, setCurrentTimeline] = useState<ReminderTaskTimeline>();

  const urlStatuses = useMemo(() => {
    const params = new URLSearchParams(location.search);
    const statuses = params.getAll('status').flatMap((value) => {
      if (value === 'open') {
        return ['PENDING', 'FIRST_SENT', 'WAITING_FEEDBACK', 'SECOND_SENT', 'ESCALATED'];
      }
      return value in reminderStatusValueEnum ? [value] : [];
    });
    return new Set(statuses as ReminderTaskStatus[]);
  }, [location.search]);

  function openCreatePolicy() {
    setCurrentPolicy(undefined);
    setPolicyOpen(true);
  }

  function openEditPolicy(record: ReminderPolicy) {
    setCurrentPolicy(record);
    setPolicyOpen(true);
  }

  async function handlePolicyFinish(values: ReminderPolicyFormValues): Promise<boolean> {
    let daysBeforeExpiry: number[];
    try {
      daysBeforeExpiry = parseDaysBeforeExpiry(values.days_before_expiry_text);
    } catch (error) {
      message.error(error instanceof Error ? error.message : '提前提醒天数格式不正确');
      return false;
    }

    const payload = {
      certificate_type_id: values.certificate_type_id || null,
      name: values.name,
      days_before_expiry: daysBeforeExpiry,
      second_reminder_after_days: values.second_reminder_after_days,
      escalation_after_days: values.escalation_after_days,
      channels: values.channels,
      enabled: values.enabled,
    };

    try {
      if (currentPolicy) {
        await updateResource<ReminderPolicy, typeof payload>(`/reminders/policies/${currentPolicy.id}`, payload);
        message.success('提醒策略已更新');
      } else {
        await createResource<ReminderPolicy, typeof payload>('/reminders/policies', payload);
        message.success('提醒策略已创建');
      }
      policyActionRef.current?.reload();
      return true;
    } catch (error) {
      message.error(error instanceof Error ? error.message : '提醒策略保存失败');
      return false;
    }
  }

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

  async function dispatchReminder(record: ReminderTask, simulate: boolean) {
    const operator = dispatchOperator.trim() || feedbackActor.trim();
    if (!operator) {
      message.warning('请先填写操作人');
      return;
    }

    setSubmittingId(`${record.id}:dispatch:${simulate ? 'simulate' : 'send'}`);
    try {
      const result = await postResource<ReminderDispatchResult, ReminderDispatchPayload>(
        `/reminders/tasks/${record.id}/dispatch`,
        {
          operator,
          simulate,
        },
      );
      message.success(
        `${simulate ? '模拟提醒' : '提醒发送'}已记录：${result.event_type}，${result.results.length} 个渠道`,
      );
      actionRef.current?.reload();
    } catch (error) {
      message.error(error instanceof Error ? error.message : '提醒派发失败');
    } finally {
      setSubmittingId(undefined);
    }
  }

  async function scanReminderTasks() {
    const operator = dispatchOperator.trim() || feedbackActor.trim() || getCurrentOperator();
    if (!operator) {
      message.warning('请先填写操作人，或在右上角设置当前操作人');
      return;
    }

    setScanning(true);
    try {
      const result = await postResource<ReminderTaskScanResult, ReminderTaskScanPayload>('/reminders/tasks/scan', {
        operator,
      });
      message.success(`已扫描到期证书，新增 ${result.created} 条提醒任务`);
      actionRef.current?.reload();
    } catch (error) {
      message.error(error instanceof Error ? error.message : '提醒任务扫描失败');
    } finally {
      setScanning(false);
    }
  }

  async function openTimeline(record: ReminderTask) {
    setTimelineOpen(true);
    setTimelineLoading(true);
    setCurrentTimeline(undefined);
    try {
      const data = await getResource<ReminderTaskTimeline>(`/reminders/tasks/${record.id}/timeline`);
      setCurrentTimeline(data);
    } catch (error) {
      message.error(error instanceof Error ? error.message : '提醒详情加载失败');
    } finally {
      setTimelineLoading(false);
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
      title: '提醒与反馈',
      valueType: 'option',
      width: 540,
      render: (_, record) => (
        <Space wrap>
          <Button
            size="small"
            type="link"
            loading={submittingId === `${record.id}:dispatch:simulate`}
            onClick={() => void dispatchReminder(record, true)}
          >
            模拟提醒
          </Button>
          <Button
            size="small"
            type="link"
            loading={submittingId === `${record.id}:dispatch:send`}
            onClick={() => void dispatchReminder(record, false)}
          >
            发送提醒
          </Button>
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
          <Button size="small" type="link" onClick={() => void openTimeline(record)}>
            详情
          </Button>
        </Space>
      ),
    },
  ];

  const policyColumns: ProColumns<ReminderPolicy>[] = [
    { title: '策略名称', dataIndex: 'name' },
    {
      title: '适用证书类型',
      dataIndex: 'certificate_type_name',
      search: false,
      renderText: (_, record) => record.certificate_type_name || '全部证书类型',
    },
    {
      title: '提前提醒(天)',
      dataIndex: 'days_before_expiry',
      search: false,
      renderText: (value: number[]) => value.join('、'),
    },
    {
      title: '二次间隔(天)',
      dataIndex: 'second_reminder_after_days',
      valueType: 'digit',
      search: false,
      width: 120,
    },
    {
      title: '升级间隔(天)',
      dataIndex: 'escalation_after_days',
      valueType: 'digit',
      search: false,
      width: 120,
    },
    {
      title: '渠道',
      dataIndex: 'channels',
      search: false,
      renderText: (channels: string[]) => channels.join('、'),
    },
    {
      title: '启用',
      dataIndex: 'enabled',
      width: 90,
      valueType: 'select',
      valueEnum: {
        true: { text: '启用', status: 'Success' },
        false: { text: '停用', status: 'Default' },
      },
      renderText: (value: boolean) => String(value),
    },
    {
      title: '操作',
      valueType: 'option',
      width: 90,
      render: (_, record) => (
        <Button type="link" size="small" onClick={() => openEditPolicy(record)}>
          编辑
        </Button>
      ),
    },
  ];

  return (
    <PageContainer title="提醒任务">
      {policyLoadError ? (
        <Alert
          type="error"
          showIcon
          title="提醒策略加载失败"
          description={policyLoadError}
          style={{ marginBottom: 16 }}
          closable={{ onClose: () => setPolicyLoadError(undefined) }}
        />
      ) : null}
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
      <ProCard title="提醒策略" bordered style={{ marginBottom: 16 }}>
        <ProTable<ReminderPolicy>
          actionRef={policyActionRef}
          rowKey="id"
          columns={policyColumns}
          request={async () => {
            try {
              const data = await listResource<ReminderPolicy>('/reminders/policies');
              setPolicyLoadError(undefined);
              return { data, success: true };
            } catch (error) {
              const description = error instanceof Error ? error.message : '提醒策略加载失败';
              setPolicyLoadError(description);
              message.error(description);
              return { data: [], success: false };
            }
          }}
          locale={{ emptyText: emptyTableText('暂无提醒策略，请先创建默认策略') }}
          pagination={false}
          search={false}
          toolbar={{
            title: '提醒策略维护',
            actions: [
            <Button key="create-policy" type="primary" onClick={openCreatePolicy}>
              新增策略
            </Button>,
            ],
          }}
        />
      </ProCard>
      <ProTable<ReminderTask>
        actionRef={actionRef}
        rowKey="id"
        columns={columns}
        request={async () => {
          try {
            const data = await listResource<ReminderTask>('/reminders/tasks');
            const filteredData =
              urlStatuses.size > 0 ? data.filter((task) => urlStatuses.has(task.status)) : data;
            setLoadError(undefined);
            return { data: filteredData, success: true };
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
            <Space key="dispatch-operator">
              <Typography.Text>操作人</Typography.Text>
              <Input
                aria-label="操作人"
                value={dispatchOperator}
                onChange={(event) => setDispatchOperator(event.target.value)}
                style={{ width: 120 }}
              />
            </Space>,
            <Button key="scan" loading={scanning} onClick={scanReminderTasks}>
              扫描生成任务
            </Button>,
          ],
        }}
        search={{ labelWidth: 88 }}
      />
      <Drawer
        title="提醒任务详情"
        open={timelineOpen}
        onClose={() => setTimelineOpen(false)}
        width={760}
        loading={timelineLoading}
      >
        {currentTimeline ? (
          <Space direction="vertical" size={16} style={{ width: '100%' }}>
            <ProCard title="任务概要" bordered>
              <Descriptions column={2} size="small">
                <Descriptions.Item label="任务状态">
                  {reminderStatusLabel(currentTimeline.task.status)}
                </Descriptions.Item>
                <Descriptions.Item label="证书记录">
                  {currentTimeline.task.employee_certificate_id}
                </Descriptions.Item>
                <Descriptions.Item label="触发日期">{currentTimeline.task.trigger_date}</Descriptions.Item>
                <Descriptions.Item label="反馈截止">
                  {currentTimeline.task.due_date || '-'}
                </Descriptions.Item>
                <Descriptions.Item label="最近事件">
                  {currentTimeline.task.last_event_at || '-'}
                </Descriptions.Item>
                <Descriptions.Item label="关闭原因">
                  {currentTimeline.task.closed_reason || '-'}
                </Descriptions.Item>
              </Descriptions>
            </ProCard>

            <ProCard title={`派发与系统事件（${currentTimeline.events.length}）`} bordered>
              {currentTimeline.events.length > 0 ? (
                <Timeline
                  items={currentTimeline.events.map((event) => ({
                    color: event.error ? 'red' : event.sent_at ? 'green' : 'gray',
                    children: (
                      <Space direction="vertical" size={4}>
                        <Typography.Text strong>
                          {reminderEventTypeLabel(event.event_type)} / {event.channel || '-'} /{' '}
                          {event.created_at}
                        </Typography.Text>
                        <Typography.Text type={event.error ? 'danger' : undefined}>
                          {event.error || `已记录：${event.sent_at || '未发送'}`}
                        </Typography.Text>
                        <Typography.Text type="secondary">
                          接收方：{event.recipient || '-'} / Provider ID：
                          {event.provider_message_id || '-'}
                        </Typography.Text>
                        {event.payload ? (
                          <Typography.Paragraph copyable style={{ whiteSpace: 'pre-wrap', marginBottom: 0 }}>
                            {JSON.stringify(event.payload, null, 2)}
                          </Typography.Paragraph>
                        ) : null}
                      </Space>
                    ),
                  }))}
                />
              ) : (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无派发事件" />
              )}
            </ProCard>

            <ProCard title={`反馈记录（${currentTimeline.feedback_items.length}）`} bordered>
              {currentTimeline.feedback_items.length > 0 ? (
                <Timeline
                  items={currentTimeline.feedback_items.map((feedback) => ({
                    color: feedback.status === 'RENEWED' ? 'green' : 'blue',
                    children: (
                      <Space direction="vertical" size={4}>
                        <Typography.Text strong>
                          {feedbackStatusLabel(feedback.status)} / {feedback.created_by} /{' '}
                          {feedback.created_at}
                        </Typography.Text>
                        <Typography.Text>{feedback.content || '-'}</Typography.Text>
                      </Space>
                    ),
                  }))}
                />
              ) : (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无反馈记录" />
              )}
            </ProCard>
          </Space>
        ) : (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="请选择提醒任务查看详情" />
        )}
      </Drawer>
      <ModalForm<ReminderPolicyFormValues>
        key={currentPolicy?.id ?? 'create'}
        title={currentPolicy ? '编辑提醒策略' : '新增提醒策略'}
        open={policyOpen}
        onOpenChange={setPolicyOpen}
        modalProps={{ destroyOnHidden: true, mask: { closable: false } }}
        layout="horizontal"
        labelCol={{ span: 7 }}
        width={680}
        initialValues={
          currentPolicy
            ? {
                certificate_type_id: currentPolicy.certificate_type_id || undefined,
                name: currentPolicy.name,
                days_before_expiry_text: currentPolicy.days_before_expiry.join(','),
                second_reminder_after_days: currentPolicy.second_reminder_after_days,
                escalation_after_days: currentPolicy.escalation_after_days,
                channels: currentPolicy.channels,
                enabled: currentPolicy.enabled,
              }
            : {
                days_before_expiry_text: '60,30,7',
                second_reminder_after_days: 7,
                escalation_after_days: 5,
                channels: ['email'],
                enabled: true,
              }
        }
        onFinish={handlePolicyFinish}
      >
        <ProFormText name="name" label="策略名称" rules={[{ required: true, message: '请输入策略名称' }]} />
        <ProFormSelect
          name="certificate_type_id"
          label="适用证书类型"
          request={certificateTypeSelectRequest}
          placeholder="不选择则适用于全部证书类型"
          allowClear
          showSearch
        />
        <ProFormText
          name="days_before_expiry_text"
          label="提前提醒天数"
          extra="多个天数用逗号分隔，例如 60,30,7"
          rules={[{ required: true, message: '请输入提前提醒天数' }]}
        />
        <ProFormDigit
          name="second_reminder_after_days"
          label="二次提醒间隔"
          min={1}
          rules={[{ required: true, message: '请输入二次提醒间隔' }]}
        />
        <ProFormDigit
          name="escalation_after_days"
          label="升级提醒间隔"
          min={1}
          rules={[{ required: true, message: '请输入升级提醒间隔' }]}
        />
        <ProFormSelect
          name="channels"
          label="提醒渠道"
          mode="multiple"
          options={reminderChannelOptions}
          rules={[{ required: true, message: '请选择提醒渠道' }]}
        />
        <ProFormSwitch name="enabled" label="启用策略" />
      </ModalForm>
    </PageContainer>
  );
}
