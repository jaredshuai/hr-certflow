import { AlertOutlined, AuditOutlined, CheckCircleOutlined, FieldTimeOutlined } from '@ant-design/icons';
import { Column, Pie } from '@ant-design/charts';
import { PageContainer, ProCard, ProTable, StatisticCard } from '@ant-design/pro-components';
import { Alert, Button, Descriptions, Drawer, Empty, Space, Steps, Timeline, Typography } from 'antd';
import { useEffect, useMemo, useState } from 'react';

import { history, request } from '@umijs/max';

import { getResource } from '@/services/api';
import type {
  DashboardChartRow,
  DashboardMissingRequiredItem,
  DashboardRiskRow,
  DashboardRiskTrace,
  DashboardSummary,
} from '@/types/domain';
import {
  auditActionLabel,
  auditResourceTypeLabel,
  certificateStatusLabel,
  documentStatusLabel,
  reminderStatusLabel,
  reviewStatusLabel,
} from '@/utils/displayLabels';
import { emptyTableText } from '@/utils/emptyStates';
import { useChartHeight } from '@/utils/useChartHeight';
import { message } from '@/utils/messageApi';

const emptyDashboardSummary: DashboardSummary = {
  expiring_count: 0,
  expired_count: 0,
  pending_review_count: 0,
  coverage: 0,
  certificate_status_rows: [],
  workload_rows: [],
  pipeline_steps: [],
  risk_rows: [],
};

interface ChartClickEvent {
  type?: string;
  data?: {
    data?: Partial<DashboardChartRow>;
    datum?: Partial<DashboardChartRow>;
  };
}

function chartTargetPath(event: unknown): string | undefined {
  const chartEvent = event as ChartClickEvent;
  const datum = chartEvent.data?.data ?? chartEvent.data?.datum;
  return typeof datum?.target_path === 'string' ? datum.target_path : undefined;
}

export default function DashboardPage() {
  const chartHeight = useChartHeight();
  const [summary, setSummary] = useState<DashboardSummary>(emptyDashboardSummary);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string>();
  const [riskTraceOpen, setRiskTraceOpen] = useState(false);
  const [riskTraceLoading, setRiskTraceLoading] = useState(false);
  const [currentRiskTrace, setCurrentRiskTrace] = useState<DashboardRiskTrace>();

  useEffect(() => {
    let cancelled = false;

    async function loadDashboardData() {
      setLoading(true);
      setLoadError(undefined);
      try {
        const response = await request<DashboardSummary>('/dashboard/summary');

        if (!cancelled) {
          setSummary(response);
        }
      } catch (error) {
        if (!cancelled) {
          setSummary(emptyDashboardSummary);
          setLoadError(error instanceof Error ? error.message : '工作台数据加载失败');
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void loadDashboardData();

    return () => {
      cancelled = true;
    };
  }, []);

  const metrics = useMemo(() => {
    return {
      expiringCount: summary.expiring_count,
      expiredCount: summary.expired_count,
      pendingReviewCount: summary.pending_review_count,
      coverage: summary.coverage,
      riskRows: summary.risk_rows,
      certificateStatusRows: summary.certificate_status_rows,
      workloadRows: summary.workload_rows,
      pipelineSteps: summary.pipeline_steps,
    };
  }, [summary]);

  function navigateTo(targetPath: string) {
    history.push(targetPath);
  }

  function handleChartEvent(event: unknown) {
    const chartEvent = event as ChartClickEvent;
    if (chartEvent.type !== 'element:click') return;
    const targetPath = chartTargetPath(chartEvent);
    if (targetPath) navigateTo(targetPath);
  }

  async function openRiskTrace(record: DashboardRiskRow) {
    setRiskTraceOpen(true);
    setRiskTraceLoading(true);
    setCurrentRiskTrace(undefined);
    try {
      const trace = await getResource<DashboardRiskTrace>(`/dashboard/risk-items/${record.id}/trace`);
      setCurrentRiskTrace(trace);
    } catch (error) {
      message.error(error instanceof Error ? error.message : '风险项追溯加载失败');
    } finally {
      setRiskTraceLoading(false);
    }
  }

  return (
    <PageContainer title="工作台">
      {loadError ? <Alert title="工作台数据加载失败" description={loadError} type="error" showIcon style={{ marginBottom: 16 }} /> : null}

      <StatisticCard.Group direction="row">
        <StatisticCard
          loading={loading}
          onClick={() => navigateTo('/certificates?status=EXPIRING')}
          style={{ cursor: 'pointer' }}
          statistic={{
            title: '即将到期',
            value: metrics.expiringCount,
            icon: <FieldTimeOutlined />,
          }}
        />
        <StatisticCard
          loading={loading}
          onClick={() => navigateTo('/certificates?status=EXPIRED')}
          style={{ cursor: 'pointer' }}
          statistic={{
            title: '已过期',
            value: metrics.expiredCount,
            status: 'error',
            icon: <AlertOutlined />,
          }}
        />
        <StatisticCard
          loading={loading}
          onClick={() => navigateTo('/review-queue')}
          style={{ cursor: 'pointer' }}
          statistic={{
            title: '待复核',
            value: metrics.pendingReviewCount,
            icon: <AuditOutlined />,
          }}
        />
        <StatisticCard
          loading={loading}
          onClick={() => navigateTo('/reports')}
          style={{ cursor: 'pointer' }}
          statistic={{
            title: '覆盖率',
            value: metrics.coverage,
            suffix: '%',
            status: 'success',
            icon: <CheckCircleOutlined />,
          }}
        />
      </StatisticCard.Group>

      <div
        style={{
          display: 'grid',
          gap: 16,
          gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
          marginTop: 16,
        }}
      >
        <ProCard title="持证状态分布" loading={loading}>
          {metrics.certificateStatusRows.length > 0 ? (
            <Pie
              data={metrics.certificateStatusRows}
              angleField="count"
              colorField="category"
              height={chartHeight}
              innerRadius={0.62}
              legend={{ color: { position: 'bottom' } }}
              label={{ text: 'count', position: 'outside' }}
              tooltip={{
                title: 'category',
                items: [{ field: 'count', name: '数量' }],
              }}
              onEvent={(_, event) => handleChartEvent(event)}
            />
          ) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无持证状态数据" />
          )}
        </ProCard>

        <ProCard title="待办任务分布" loading={loading}>
          {metrics.workloadRows.length > 0 ? (
            <Column
              data={metrics.workloadRows}
              xField="category"
              yField="count"
              height={chartHeight}
              colorField="category"
              axis={{ y: { title: '数量' } }}
              label={{ text: 'count', position: 'top' }}
              tooltip={{
                title: 'category',
                items: [{ field: 'count', name: '数量' }],
              }}
              onEvent={(_, event) => handleChartEvent(event)}
            />
          ) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无待办任务数据" />
          )}
        </ProCard>
      </div>

      <ProCard style={{ marginTop: 16 }} title="证书处理进度" loading={loading}>
        {metrics.pipelineSteps.some((step) => step.count > 0) ? (
          <>
            <Typography.Paragraph type="secondary" style={{ marginBottom: 16 }}>
              按处理阶段统计：上传和识别来自证书文件，复核来自复核任务，入库来自正式持证记录，提醒来自提醒任务。
            </Typography.Paragraph>
            <Steps
              current={-1}
              items={metrics.pipelineSteps.map((step) => ({
                title: step.title,
                description: (
                  <Space orientation="vertical" size={4}>
                    <span>{step.description}</span>
                    <Button type="link" size="small" style={{ padding: 0 }} onClick={() => navigateTo(step.target_path)}>
                      查看明细
                    </Button>
                  </Space>
                ),
              }))}
            />
          </>
        ) : (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无处理进度数据" />
        )}
      </ProCard>

      <ProCard style={{ marginTop: 16 }} title="风险台账">
        <ProTable<DashboardRiskRow>
          rowKey="id"
          search={false}
          options={false}
          pagination={false}
          loading={loading}
          dataSource={metrics.riskRows}
          locale={{ emptyText: emptyTableText('暂无风险项') }}
          columns={[
            { title: '指标', dataIndex: 'metric' },
            { title: '数量', dataIndex: 'count', valueType: 'digit' },
            {
              title: '状态',
              dataIndex: 'status',
              valueEnum: {
                需跟进: { text: '需跟进', status: 'Error' },
                处理中: { text: '处理中', status: 'Processing' },
                升级前: { text: '升级前', status: 'Warning' },
              },
            },
            {
              title: '追溯',
              valueType: 'option',
              width: 170,
              render: (_, record) => (
                <Space>
                  <Button type="link" size="small" onClick={() => openRiskTrace(record)}>
                    追溯
                  </Button>
                  <Button type="link" size="small" onClick={() => navigateTo(record.target_path)}>
                    明细
                  </Button>
                </Space>
              ),
            },
          ]}
        />
      </ProCard>

      <Drawer
        title="风险项追溯"
        open={riskTraceOpen}
        onClose={() => setRiskTraceOpen(false)}
        size={840}
        loading={riskTraceLoading}
      >
        {currentRiskTrace ? (
          <Space orientation="vertical" size={16} style={{ width: '100%' }}>
            <ProCard title="风险摘要">
              <Descriptions column={2} size="small">
                <Descriptions.Item label="指标">{currentRiskTrace.risk.metric}</Descriptions.Item>
                <Descriptions.Item label="数量">{currentRiskTrace.risk.count}</Descriptions.Item>
                <Descriptions.Item label="状态">{currentRiskTrace.risk.status}</Descriptions.Item>
                <Descriptions.Item label="完整列表">
                  <Button type="link" size="small" onClick={() => navigateTo(currentRiskTrace.risk.target_path)}>
                    打开筛选结果
                  </Button>
                </Descriptions.Item>
              </Descriptions>
            </ProCard>

            <ProCard title={`缺失必备证书（${currentRiskTrace.missing_required_items.length}）`}>
              {currentRiskTrace.missing_required_items.length > 0 ? (
                <ProTable<DashboardMissingRequiredItem>
                  rowKey={(record) => `${record.employee_id}-${record.certificate_type_id}`}
                  search={false}
                  options={false}
                  pagination={{ pageSize: 10, hideOnSinglePage: true }}
                  dataSource={currentRiskTrace.missing_required_items}
                  columns={[
                    { title: '工号', dataIndex: 'employee_no', width: 100 },
                    { title: '姓名', dataIndex: 'employee_name', width: 100 },
                    { title: '部门', dataIndex: 'department', width: 120 },
                    {
                      title: '缺失证书',
                      dataIndex: 'certificate_type_name',
                      renderText: (_, record) => `${record.certificate_type_name}（${record.certificate_type_code}）`,
                    },
                    {
                      title: '操作',
                      valueType: 'option',
                      width: 100,
                      render: (_, record) => (
                        <Button type="link" size="small" onClick={() => navigateTo(record.target_path)}>
                          查看员工
                        </Button>
                      ),
                    },
                  ]}
                />
              ) : (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无缺失必备证书明细" />
              )}
            </ProCard>

            <ProCard title={`关联证书（${currentRiskTrace.certificates.length}）`}>
              {currentRiskTrace.certificates.length > 0 ? (
                <Timeline
                  items={currentRiskTrace.certificates.map((certificate) => ({
                    color: certificate.status === 'EXPIRED' ? 'red' : 'blue',
                    content: (
                      <Space orientation="vertical" size={4}>
                        <Typography.Text strong>
                          {certificate.holder_name} / {certificate.certificate_no || '-'} /{' '}
                          {certificateStatusLabel(certificate.status)}
                        </Typography.Text>
                        <Typography.Text type="secondary">
                          到期：{certificate.valid_to || '-'} / 确认：{certificate.confirmed_by || '-'}
                        </Typography.Text>
                      </Space>
                    ),
                  }))}
                />
              ) : (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无关联证书" />
              )}
            </ProCard>

            <ProCard title={`关联文件（${currentRiskTrace.documents.length}）`}>
              {currentRiskTrace.documents.length > 0 ? (
                <Timeline
                  items={currentRiskTrace.documents.map((document) => ({
                    color: document.status === 'FAILED' ? 'red' : 'blue',
                    content: (
                      <Space orientation="vertical" size={4}>
                        <Typography.Text strong>
                          {document.original_filename} / {documentStatusLabel(document.status)}
                        </Typography.Text>
                        <Typography.Text type="secondary">
                          SHA256：{document.sha256 || '-'} / 失败原因：{document.failure_reason || '-'}
                        </Typography.Text>
                      </Space>
                    ),
                  }))}
                />
              ) : (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无关联文件" />
              )}
            </ProCard>

            <ProCard title={`复核任务（${currentRiskTrace.review_tasks.length}）`}>
              {currentRiskTrace.review_tasks.length > 0 ? (
                <Timeline
                  items={currentRiskTrace.review_tasks.map((task) => ({
                    color: task.status === 'NEEDS_INFO' ? 'orange' : 'blue',
                    content: (
                      <Space orientation="vertical" size={4}>
                        <Typography.Text strong>
                          {reviewStatusLabel(task.status)} / {task.document_original_filename || task.document_id}
                        </Typography.Text>
                        <Typography.Text type="secondary">
                          更新：{task.updated_at} / 复核人：{task.reviewed_by || '-'}
                        </Typography.Text>
                      </Space>
                    ),
                  }))}
                />
              ) : (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无关联复核任务" />
              )}
            </ProCard>

            <ProCard title={`提醒任务（${currentRiskTrace.reminder_tasks.length}）`}>
              {currentRiskTrace.reminder_tasks.length > 0 ? (
                <Timeline
                  items={currentRiskTrace.reminder_tasks.map((task) => ({
                    color: task.status === 'ESCALATED' ? 'red' : 'orange',
                    content: (
                      <Space orientation="vertical" size={4}>
                        <Typography.Text strong>{reminderStatusLabel(task.status)}</Typography.Text>
                        <Typography.Text type="secondary">
                          发起：{task.trigger_date} / 截止：{task.due_date || '-'} / 关闭原因：
                          {task.closed_reason || '-'}
                        </Typography.Text>
                      </Space>
                    ),
                  }))}
                />
              ) : (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无关联提醒任务" />
              )}
            </ProCard>

            <ProCard title={`审计摘要（${currentRiskTrace.audit_logs.length}）`}>
              {currentRiskTrace.audit_logs.length > 0 ? (
                <Timeline
                  items={currentRiskTrace.audit_logs.map((log) => ({
                    content: `${log.created_at} / ${auditActionLabel(log.action)} / ${auditResourceTypeLabel(
                      log.resource_type,
                    )} / ${log.actor_name || '-'} / 请求 ${log.request_id || '-'}`,
                  }))}
                />
              ) : (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无关联审计记录" />
              )}
            </ProCard>
          </Space>
        ) : (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="请选择风险项查看追溯链路" />
        )}
      </Drawer>
    </PageContainer>
  );
}
