import { AlertOutlined, AuditOutlined, CheckCircleOutlined, FieldTimeOutlined } from '@ant-design/icons';
import { Column, Pie } from '@ant-design/charts';
import { PageContainer, ProCard, ProTable, StatisticCard } from '@ant-design/pro-components';
import { Alert, Button, Empty, Space, Steps, Typography } from 'antd';
import { useEffect, useMemo, useState } from 'react';

import { history, request } from '@umijs/max';

import type { DashboardRiskRow, DashboardSummary } from '@/types/domain';
import { emptyTableText } from '@/utils/emptyStates';

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
  const [summary, setSummary] = useState<DashboardSummary>(emptyDashboardSummary);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string>();

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
          onClick={() => navigateTo('/certificates?status=ACTIVE')}
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
              height={280}
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

        <ProCard title="待办压力分布" loading={loading}>
          {metrics.workloadRows.length > 0 ? (
            <Column
              data={metrics.workloadRows}
              xField="category"
              yField="count"
              height={280}
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
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无待办压力数据" />
          )}
        </ProCard>
      </div>

      <ProCard style={{ marginTop: 16 }} title="北极星交付进度" loading={loading}>
        {metrics.pipelineSteps.some((step) => step.count > 0) ? (
          <>
            <Typography.Paragraph type="secondary" style={{ marginBottom: 16 }}>
              按真实业务对象统计：上传和识别来自证书文件，复核来自复核任务，入库来自正式持证记录，提醒来自提醒任务。
            </Typography.Paragraph>
            <Steps
              current={-1}
              items={metrics.pipelineSteps.map((step) => ({
                title: step.title,
                description: (
                  <Space direction="vertical" size={4}>
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
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无交付进度数据" />
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
              width: 100,
              render: (_, record) => (
                <Button type="link" size="small" onClick={() => navigateTo(record.target_path)}>
                  查看明细
                </Button>
              ),
            },
          ]}
        />
      </ProCard>
    </PageContainer>
  );
}
