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
import { Alert, Button, Descriptions, Drawer, Empty, Space, Tag, Timeline, Typography } from 'antd';
import { useMemo, useRef, useState } from 'react';

import { useLocation } from '@umijs/max';

import { createResource, getResource, listResource, pageResource, postResource, updateResource } from '@/services/api';
import type {
  FeedbackStatus,
  ReminderEvent,
  ReminderEventType,
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
  auditActionLabel,
  auditResourceTypeLabel,
  feedbackStatusLabel,
  reminderChannelLabel,
  reminderChannelOptions,
  reminderEventTypeLabel,
  reminderStatusLabel,
  reminderStatusValueEnum,
} from '@/utils/displayLabels';
import { downloadCsv } from '@/utils/download';
import { emptyTableText } from '@/utils/emptyStates';
import { certificateTypeSelectRequest } from '@/utils/formOptions';
import { message } from '@/utils/messageApi';
import { actorProvider } from '@/utils/actorProvider';
import { parseDaysBeforeExpiryText } from '@/utils/reminderPolicyForm';

const feedbackActions: Array<{ label: string; status: FeedbackStatus; content: string; danger?: boolean }> = [
  { label: '已通知', status: 'NOTIFIED_EMPLOYEE', content: '人力已通知员工' },
  { label: '办理中', status: 'PROCESSING', content: '员工证书正在办理' },
  { label: '已换证', status: 'RENEWED', content: '员工已完成换证' },
  { label: '无需处理', status: 'NO_ACTION_REQUIRED', content: '人力确认无需处理' },
  { label: '员工离职', status: 'EMPLOYEE_LEFT', content: '员工已离职，关闭提醒' },
  { label: '忽略', status: 'IGNORED', content: '人力忽略本次提醒', danger: true },
];

const dispatchEventTypes: ReminderEventType[] = ['FIRST_REMINDER', 'SECOND_REMINDER', 'ESCALATION'];

type ChannelDispatchStatus = {
  channel: string;
  status: 'success' | 'failed' | 'pending';
  attempts: number;
  latestAt: string;
  eventType: ReminderEventType;
  eventDate: string;
  error?: string;
};

type ChannelDispatchSummary = {
  eventType: ReminderEventType;
  eventDate: string;
  statuses: ChannelDispatchStatus[];
  retryChannels: string[];
  requestChannels: string[];
};

type ReminderPolicyFormValues = {
  certificate_type_id?: string;
  name: string;
  days_before_expiry_text: string;
  second_reminder_after_days: number;
  escalation_after_days: number;
  channels: string[];
  enabled: boolean;
};

function cleanSearchParams(params: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(params).filter(([, value]) => {
      if (Array.isArray(value)) return value.length > 0;
      return value !== undefined && value !== null && value !== '';
    }),
  );
}

function reminderFiltersFromSearch(search: string): Record<string, unknown> {
  const params = new URLSearchParams(search);
  const statusGroup = params.get('status_group');
  if (statusGroup) return { status_group: statusGroup };

  const rawStatuses = params.getAll('status');
  if (rawStatuses.includes('open')) return { status_group: 'open' };

  const statuses = rawStatuses.filter((value): value is ReminderTaskStatus => value in reminderStatusValueEnum);
  if (statuses.length === 2 && statuses.includes('SECOND_SENT') && statuses.includes('ESCALATED')) {
    return { status_group: 'attention' };
  }
  if (statuses.length === 1) return { status: statuses[0] };
  if (statuses.length > 1) return { status: statuses };
  return {};
}

function isDispatchEvent(event: ReminderEvent): event is ReminderEvent & { channel: string } {
  return dispatchEventTypes.includes(event.event_type) && Boolean(event.channel);
}

function isSuccessfulDispatchEvent(event: ReminderEvent): boolean {
  const payloadStatus = event.payload?.status;
  return Boolean(event.sent_at && !event.error && (payloadStatus === undefined || payloadStatus === 'sent'));
}

function buildChannelDispatchSummary(timeline?: ReminderTaskTimeline): ChannelDispatchSummary | undefined {
  const dispatchEvents = (timeline?.events || [])
    .filter(isDispatchEvent)
    .sort((left, right) => right.created_at.localeCompare(left.created_at));

  if (dispatchEvents.length === 0) return undefined;

  const latestEvent = dispatchEvents[0];
  const currentWindowEvents = dispatchEvents.filter(
    (event) => event.event_type === latestEvent.event_type && event.event_date === latestEvent.event_date,
  );
  const eventsByChannel = new Map<string, ReminderEvent[]>();

  currentWindowEvents.forEach((event) => {
    const channelEvents = eventsByChannel.get(event.channel) || [];
    channelEvents.push(event);
    eventsByChannel.set(event.channel, channelEvents);
  });

  const statuses = Array.from(eventsByChannel.entries())
    .map(([channel, channelEvents]) => {
      const sortedEvents = [...channelEvents].sort((left, right) => right.created_at.localeCompare(left.created_at));
      const latestChannelEvent = sortedEvents[0];
      const hasSuccess = sortedEvents.some(isSuccessfulDispatchEvent);
      const status: ChannelDispatchStatus['status'] = hasSuccess
        ? 'success'
        : latestChannelEvent.error
          ? 'failed'
          : 'pending';

      return {
        channel,
        status,
        attempts: sortedEvents.length,
        latestAt: latestChannelEvent.created_at,
        eventType: latestEvent.event_type,
        eventDate: latestEvent.event_date,
        error: latestChannelEvent.error,
      };
    })
    .sort((left, right) => reminderChannelLabel(left.channel).localeCompare(reminderChannelLabel(right.channel)));

  return {
    eventType: latestEvent.event_type,
    eventDate: latestEvent.event_date,
    statuses,
    retryChannels: statuses.filter((item) => item.status !== 'success').map((item) => item.channel),
    // 后端用同一轮全部渠道判断幂等窗口；已成功渠道会自动跳过，只补发未成功渠道。
    requestChannels: statuses.map((item) => item.channel),
  };
}

function channelDispatchSubmitId(recordId: string, simulate: boolean, channels?: string[]): string {
  const channelKey = channels && channels.length > 0 ? [...channels].sort().join('|') : 'all';
  return `${recordId}:dispatch:${simulate ? 'simulate' : 'send'}:${channelKey}`;
}

function channelStatusTag(status: ChannelDispatchStatus['status']): { color: string; text: string } {
  if (status === 'success') return { color: 'success', text: '已成功' };
  if (status === 'failed') return { color: 'error', text: '失败' };
  return { color: 'warning', text: '未确认' };
}

export default function RemindersPage() {
  const actionRef = useRef<ActionType>();
  const policyActionRef = useRef<ActionType>();
  const lastSearchParamsRef = useRef<Record<string, unknown>>({});
  const location = useLocation();
  const [submittingId, setSubmittingId] = useState<string>();
  const [scanning, setScanning] = useState(false);
  const [loadError, setLoadError] = useState<string>();
  const [policyLoadError, setPolicyLoadError] = useState<string>();
  const [policyOpen, setPolicyOpen] = useState(false);
  const [currentPolicy, setCurrentPolicy] = useState<ReminderPolicy>();
  const [timelineOpen, setTimelineOpen] = useState(false);
  const [timelineLoading, setTimelineLoading] = useState(false);
  const [currentTimeline, setCurrentTimeline] = useState<ReminderTaskTimeline>();

  const urlFilters = useMemo(() => reminderFiltersFromSearch(location.search), [location.search]);

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
      daysBeforeExpiry = parseDaysBeforeExpiryText(values.days_before_expiry_text);
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
    const actor = actorProvider.getCurrent();
    if (!actor) {
      message.warning('请先在右上角设置当前操作人');
      return;
    }

    setSubmittingId(`${record.id}:${status}`);
    try {
      await postResource(`/reminders/tasks/${record.id}/feedback`, {
        status,
        content,
        created_by: actor.name,
      });
      message.success('人力反馈已记录');
      actionRef.current?.reload();
    } catch (error) {
      message.error(error instanceof Error ? error.message : '反馈提交失败');
    } finally {
      setSubmittingId(undefined);
    }
  }

  async function loadTimeline(reminderTaskId: string, reset: boolean) {
    setTimelineLoading(true);
    if (reset) setCurrentTimeline(undefined);
    try {
      const data = await getResource<ReminderTaskTimeline>(`/reminders/tasks/${reminderTaskId}/timeline`);
      setCurrentTimeline(data);
    } catch (error) {
      message.error(error instanceof Error ? error.message : '提醒详情加载失败');
    } finally {
      setTimelineLoading(false);
    }
  }

  async function dispatchReminder(record: ReminderTask, simulate: boolean, channels?: string[]) {
    const operator = actorProvider.getCurrent()?.name;
    if (!operator) {
      message.warning('请先在右上角设置当前操作人');
      return;
    }

    const normalizedChannels = channels?.filter(Boolean);
    setSubmittingId(channelDispatchSubmitId(record.id, simulate, normalizedChannels));
    try {
      const payload: ReminderDispatchPayload = { operator, simulate };
      if (normalizedChannels && normalizedChannels.length > 0) payload.channels = normalizedChannels;

      const result = await postResource<ReminderDispatchResult, ReminderDispatchPayload>(
        `/reminders/tasks/${record.id}/dispatch`,
        payload,
      );
      message.success(
        `${simulate ? '模拟提醒' : '提醒发送'}已记录：${result.event_type}，${result.results.length} 个渠道`,
      );
      actionRef.current?.reload();
      if (timelineOpen && currentTimeline?.task.id === record.id) {
        await loadTimeline(record.id, false);
      }
    } catch (error) {
      message.error(error instanceof Error ? error.message : '提醒派发失败');
    } finally {
      setSubmittingId(undefined);
    }
  }

  async function scanReminderTasks() {
    const operator = actorProvider.getCurrent()?.name;
    if (!operator) {
      message.warning('请先在右上角设置当前操作人');
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

  async function exportReminderTasks() {
    try {
      await downloadCsv('/reminders/tasks/export.csv', lastSearchParamsRef.current, 'reminder-tasks.csv');
      message.success('提醒任务已开始导出');
    } catch (error) {
      message.error(error instanceof Error ? error.message : '提醒任务导出失败');
    }
  }

  async function openTimeline(record: ReminderTask) {
    setTimelineOpen(true);
    await loadTimeline(record.id, true);
  }

  const columns: ProColumns<ReminderTask>[] = [
    {
      title: '关键字',
      dataIndex: 'keyword',
      hideInTable: true,
      fieldProps: { placeholder: '员工、工号、证书编号、证书类型' },
    },
    {
      title: '员工',
      dataIndex: 'employee_name',
      width: 180,
      search: false,
      renderText: (_, record) =>
        record.employee_name
          ? `${record.employee_name}${record.employee_no ? `（${record.employee_no}）` : ''}`
          : record.holder_name || '-',
    },
    {
      title: '证书类型',
      dataIndex: 'certificate_type_name',
      width: 180,
      search: false,
      renderText: (value) => value || '-',
    },
    {
      title: '证书编号',
      dataIndex: 'certificate_no',
      width: 160,
      search: false,
      ellipsis: true,
      renderText: (value) => value || '-',
    },
    {
      title: '证书类型筛选',
      dataIndex: 'certificate_type_id',
      hideInTable: true,
      valueType: 'select',
      request: certificateTypeSelectRequest,
      fieldProps: { showSearch: true },
    },
    { title: '到期日期', dataIndex: 'valid_to', valueType: 'date', width: 130, search: false },
    { title: '发起日期', dataIndex: 'trigger_date', valueType: 'date', width: 130 },
    {
      title: '发起日期区间',
      dataIndex: 'trigger_date_range',
      valueType: 'dateRange',
      hideInTable: true,
      search: {
        transform: (value) => ({
          trigger_date_from: value?.[0],
          trigger_date_to: value?.[1],
        }),
      },
    },
    { title: '反馈截止', dataIndex: 'due_date', valueType: 'date', width: 130 },
    {
      title: '反馈截止区间',
      dataIndex: 'due_date_range',
      valueType: 'dateRange',
      hideInTable: true,
      search: {
        transform: (value) => ({
          due_date_from: value?.[0],
          due_date_to: value?.[1],
        }),
      },
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 150,
      valueType: 'select',
      valueEnum: reminderStatusValueEnum,
    },
    { title: '提醒策略', dataIndex: 'policy_name', search: false, renderText: (value) => value || '-' },
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
            loading={submittingId === channelDispatchSubmitId(record.id, true)}
            onClick={() => void dispatchReminder(record, true)}
          >
            模拟提醒
          </Button>
          <Button
            size="small"
            type="link"
            loading={submittingId === channelDispatchSubmitId(record.id, false)}
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

  const channelDispatchSummary = useMemo(
    () => buildChannelDispatchSummary(currentTimeline),
    [currentTimeline],
  );
  const timelineAuditLogs = currentTimeline?.audit_logs || [];

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
      <ProCard title="提醒策略" style={{ marginBottom: 16 }}>
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
        params={urlFilters}
        request={async (params) => {
          try {
            const { current, pageSize, trigger_date_range, due_date_range, ...searchParams } = params;
            void trigger_date_range;
            void due_date_range;
            const nextSearchParams = cleanSearchParams(searchParams);
            lastSearchParamsRef.current = nextSearchParams;
            const result = await pageResource<ReminderTask>('/reminders/tasks/page', {
              ...nextSearchParams,
              current,
              page_size: pageSize,
            });
            setLoadError(undefined);
            return { data: result.data, total: result.total, success: true };
          } catch (error) {
            const description = error instanceof Error ? error.message : '提醒任务加载失败';
            setLoadError(description);
            message.error(description);
            return { data: [], success: false };
          }
        }}
        locale={{ emptyText: emptyTableText('暂无提醒任务，系统会在证书临期或过期时生成') }}
        toolbar={{
          title: '到期提醒总览',
          actions: [
            <Button key="scan" loading={scanning} onClick={scanReminderTasks}>
              扫描生成任务
            </Button>,
            <Button key="export" onClick={exportReminderTasks}>
              导出当前筛选
            </Button>,
          ],
        }}
        pagination={{ defaultPageSize: 20, showSizeChanger: true }}
        search={{ labelWidth: 104 }}
      />
      <Drawer
        title="提醒任务详情"
        open={timelineOpen}
        onClose={() => setTimelineOpen(false)}
        size={760}
        loading={timelineLoading}
      >
        {currentTimeline ? (
          <Space orientation="vertical" size={16} style={{ width: '100%' }}>
            <ProCard title="任务概要">
              <Descriptions column={2} size="small">
                <Descriptions.Item label="任务状态">
                  {reminderStatusLabel(currentTimeline.task.status)}
                </Descriptions.Item>
                <Descriptions.Item label="证书记录">
                  {currentTimeline.task.employee_certificate_id}
                </Descriptions.Item>
                <Descriptions.Item label="员工">
                  {currentTimeline.task.employee_name
                    ? `${currentTimeline.task.employee_name}${
                        currentTimeline.task.employee_no ? `（${currentTimeline.task.employee_no}）` : ''
                      }`
                    : '-'}
                </Descriptions.Item>
                <Descriptions.Item label="证书类型">
                  {currentTimeline.task.certificate_type_name || '-'}
                </Descriptions.Item>
                <Descriptions.Item label="证书编号">
                  {currentTimeline.task.certificate_no || '-'}
                </Descriptions.Item>
                <Descriptions.Item label="发起日期">{currentTimeline.task.trigger_date}</Descriptions.Item>
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

            <ProCard title="渠道派发状态">
              {channelDispatchSummary ? (
                <Space orientation="vertical" size={12} style={{ width: '100%' }}>
                  <Alert
                    type={channelDispatchSummary.retryChannels.length > 0 ? 'warning' : 'success'}
                    showIcon
                    title={`当前事件：${reminderEventTypeLabel(channelDispatchSummary.eventType)} / ${channelDispatchSummary.eventDate}`}
                    description={
                      channelDispatchSummary.retryChannels.length > 0
                        ? `未成功渠道：${channelDispatchSummary.retryChannels
                            .map(reminderChannelLabel)
                            .join('、')}。重试会带上本轮全部渠道，后端会自动跳过已成功渠道。`
                        : '本轮所有已记录渠道均已成功。'
                    }
                  />
                  <Space wrap>
                    {channelDispatchSummary.statuses.map((item) => {
                      const tag = channelStatusTag(item.status);
                      return (
                        <Tag key={item.channel} color={tag.color}>
                          {reminderChannelLabel(item.channel)}：{tag.text}，尝试 {item.attempts} 次
                          {item.error ? `，${item.error}` : ''}
                        </Tag>
                      );
                    })}
                  </Space>
                  {channelDispatchSummary.retryChannels.length > 0 ? (
                    <Space wrap>
                      <Button
                        loading={
                          submittingId ===
                          channelDispatchSubmitId(
                            currentTimeline.task.id,
                            true,
                            channelDispatchSummary.requestChannels,
                          )
                        }
                        onClick={() =>
                          void dispatchReminder(
                            currentTimeline.task,
                            true,
                            channelDispatchSummary.requestChannels,
                          )
                        }
                      >
                        模拟重试未成功渠道
                      </Button>
                      <Button
                        type="primary"
                        danger
                        loading={
                          submittingId ===
                          channelDispatchSubmitId(
                            currentTimeline.task.id,
                            false,
                            channelDispatchSummary.requestChannels,
                          )
                        }
                        onClick={() =>
                          void dispatchReminder(
                            currentTimeline.task,
                            false,
                            channelDispatchSummary.requestChannels,
                          )
                        }
                      >
                        重试未成功渠道
                      </Button>
                    </Space>
                  ) : null}
                </Space>
              ) : (
                <Alert type="info" showIcon title="尚无派发事件" description="发送或模拟提醒后，这里会显示各渠道状态。" />
              )}
            </ProCard>

            <ProCard title={`派发与系统事件（${currentTimeline.events.length}）`}>
              {currentTimeline.events.length > 0 ? (
                <Timeline
                  items={currentTimeline.events.map((event) => ({
                    color: event.error ? 'red' : event.sent_at ? 'green' : 'gray',
                    content: (
                      <Space orientation="vertical" size={4}>
                        <Typography.Text strong>
                          {reminderEventTypeLabel(event.event_type)} / {event.channel || '-'} /{' '}
                          {event.created_at}
                        </Typography.Text>
                        <Typography.Text type="secondary">
                          事件日期：{event.event_date || '-'}
                        </Typography.Text>
                        <Typography.Text type={event.error ? 'danger' : undefined}>
                          {event.error || `已记录：${event.sent_at || '未发送'}`}
                        </Typography.Text>
                        <Typography.Text type="secondary">
                          接收方：{event.recipient || '-'} / 发送回执：
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

            <ProCard title={`反馈记录（${currentTimeline.feedback_items.length}）`}>
              {currentTimeline.feedback_items.length > 0 ? (
                <Timeline
                  items={currentTimeline.feedback_items.map((feedback) => ({
                    color: feedback.status === 'RENEWED' ? 'green' : 'blue',
                    content: (
                      <Space orientation="vertical" size={4}>
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

            <ProCard title={`关联审计记录（${timelineAuditLogs.length}）`}>
              {timelineAuditLogs.length > 0 ? (
                <Timeline
                  items={timelineAuditLogs.map((log) => ({
                    color: log.resource_type === 'reminder_task' ? 'blue' : 'gray',
                    content: (
                      <Space orientation="vertical" size={4}>
                        <Typography.Text strong>
                          {auditActionLabel(log.action)} / {auditResourceTypeLabel(log.resource_type)}
                        </Typography.Text>
                        <Typography.Text type="secondary">
                          {log.created_at} / 操作人：{log.actor_name || '未知'} / 请求：{log.request_id || '-'}
                        </Typography.Text>
                        <Typography.Text type="secondary">
                          资源：{log.resource_id || '-'} / IP：{log.ip_address || '-'}
                        </Typography.Text>
                      </Space>
                    ),
                  }))}
                />
              ) : (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无关联审计记录" />
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
