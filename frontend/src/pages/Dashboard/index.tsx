import { AlertOutlined, AuditOutlined, CheckCircleOutlined, FieldTimeOutlined } from '@ant-design/icons';
import { Column, Pie } from '@ant-design/charts';
import { PageContainer, ProCard, ProTable, StatisticCard } from '@ant-design/pro-components';
import { Alert, Empty, Steps } from 'antd';
import { useEffect, useMemo, useState } from 'react';

import { listResource } from '@/services/api';
import type { Employee, EmployeeCertificate, ReminderTask, ReviewTask } from '@/types/domain';
import { certificateStatusLabel } from '@/utils/displayLabels';
import { emptyTableText } from '@/utils/emptyStates';

interface DashboardData {
  employees: Employee[];
  certificates: EmployeeCertificate[];
  reviews: ReviewTask[];
  reminders: ReminderTask[];
}

interface RiskRow {
  id: string;
  metric: string;
  count: number;
  status: string;
}

interface ChartRow {
  category: string;
  count: number;
}

const emptyDashboardData: DashboardData = {
  employees: [],
  certificates: [],
  reviews: [],
  reminders: [],
};

const expiringStatuses = new Set(['EXPIRING']);
const expiredStatuses = new Set(['EXPIRED']);
const activeCoverageStatuses = new Set(['ACTIVE', 'EXPIRING']);
const pendingReviewStatuses = new Set(['PENDING', 'NEEDS_INFO']);
const secondReminderStatuses = new Set(['SECOND_SENT', 'ESCALATED']);

function buildRiskRows(data: DashboardData): RiskRow[] {
  const expiredCount = data.certificates.filter((certificate) => expiredStatuses.has(certificate.status)).length;
  const pendingReviewCount = data.reviews.filter((review) => pendingReviewStatuses.has(review.status)).length;
  const secondReminderCount = data.reminders.filter((reminder) => secondReminderStatuses.has(reminder.status)).length;

  return [
    { id: 'expired-certificates', metric: '已过期证书', count: expiredCount, status: '需跟进' },
    { id: 'pending-reviews', metric: '待复核识别', count: pendingReviewCount, status: '处理中' },
    { id: 'second-reminders', metric: '二次或升级提醒', count: secondReminderCount, status: '升级前' },
  ].filter((row) => row.count > 0);
}

function buildCertificateStatusRows(certificates: EmployeeCertificate[]): ChartRow[] {
  const counts = certificates.reduce<Partial<Record<EmployeeCertificate['status'], number>>>((acc, certificate) => {
    acc[certificate.status] = (acc[certificate.status] || 0) + 1;
    return acc;
  }, {});

  return Object.entries(counts)
    .map(([status, count]) => ({
      category: certificateStatusLabel(status as EmployeeCertificate['status']),
      count: count || 0,
    }))
    .filter((row) => row.count > 0);
}

export default function DashboardPage() {
  const [data, setData] = useState<DashboardData>(emptyDashboardData);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string>();

  useEffect(() => {
    let cancelled = false;

    async function loadDashboardData() {
      setLoading(true);
      setLoadError(undefined);
      try {
        const [employees, certificates, reviews, reminders] = await Promise.all([
          listResource<Employee>('/employees'),
          listResource<EmployeeCertificate>('/certificates'),
          listResource<ReviewTask>('/reviews'),
          listResource<ReminderTask>('/reminders/tasks'),
        ]);

        if (!cancelled) {
          setData({ employees, certificates, reviews, reminders });
        }
      } catch (error) {
        if (!cancelled) {
          setData(emptyDashboardData);
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
    const expiringCount = data.certificates.filter((certificate) => expiringStatuses.has(certificate.status)).length;
    const expiredCount = data.certificates.filter((certificate) => expiredStatuses.has(certificate.status)).length;
    const pendingReviewCount = data.reviews.filter((review) => pendingReviewStatuses.has(review.status)).length;
    const coveredEmployeeIds = new Set(
      data.certificates
        .filter((certificate) => activeCoverageStatuses.has(certificate.status))
        .map((certificate) => certificate.employee_id),
    );
    const coverage = data.employees.length > 0 ? Number(((coveredEmployeeIds.size / data.employees.length) * 100).toFixed(1)) : 0;

    const draftCount = data.certificates.filter((c) => c.status === 'DRAFT').length;
    const aiRecognitionCount = data.reviews.filter((r) => r.status === 'PENDING').length;
    const manualReviewCount = data.reviews.filter((r) => pendingReviewStatuses.has(r.status)).length;
    const archivedCount = data.certificates.filter((c) => activeCoverageStatuses.has(c.status)).length;
    const activeReminderCount = data.reminders.filter((r) => !['RESOLVED', 'CLOSED'].includes(r.status)).length;

    return {
      expiringCount,
      expiredCount,
      pendingReviewCount,
      coverage,
      riskRows: buildRiskRows(data),
      certificateStatusRows: buildCertificateStatusRows(data.certificates),
      workloadRows: [
        { category: '即将到期', count: expiringCount },
        { category: '已过期', count: expiredCount },
        { category: '待复核', count: pendingReviewCount },
        {
          category: '升级提醒',
          count: data.reminders.filter((reminder) => secondReminderStatuses.has(reminder.status)).length,
        },
      ].filter((row) => row.count > 0),
      pipelineSteps: [
        { title: '上传原件', description: `${draftCount} 件待识别`, count: draftCount },
        { title: 'AI 识别', description: `${aiRecognitionCount} 件识别中`, count: aiRecognitionCount },
        { title: '人工复核', description: `${manualReviewCount} 件待复核`, count: manualReviewCount },
        { title: '正式入库', description: `${archivedCount} 件已入库`, count: archivedCount },
        { title: '到期提醒', description: `${activeReminderCount} 件提醒中`, count: activeReminderCount },
      ],
    };
  }, [data]);

  return (
    <PageContainer title="工作台">
      {loadError ? <Alert title="工作台数据加载失败" description={loadError} type="error" showIcon style={{ marginBottom: 16 }} /> : null}

      <StatisticCard.Group direction="row">
        <StatisticCard
          loading={loading}
          statistic={{
            title: '即将到期',
            value: metrics.expiringCount,
            icon: <FieldTimeOutlined />,
          }}
        />
        <StatisticCard
          loading={loading}
          statistic={{
            title: '已过期',
            value: metrics.expiredCount,
            status: 'error',
            icon: <AlertOutlined />,
          }}
        />
        <StatisticCard
          loading={loading}
          statistic={{
            title: '待复核',
            value: metrics.pendingReviewCount,
            icon: <AuditOutlined />,
          }}
        />
        <StatisticCard
          loading={loading}
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
            />
          ) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无待办压力数据" />
          )}
        </ProCard>
      </div>

      <ProCard style={{ marginTop: 16 }} title="北极星交付进度" loading={loading}>
        {metrics.pipelineSteps.some((step) => step.count > 0) ? (
          <Steps
            current={-1}
            items={metrics.pipelineSteps.map((step) => ({
              title: step.title,
              description: step.description,
            }))}
          />
        ) : (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无交付进度数据" />
        )}
      </ProCard>

      <ProCard style={{ marginTop: 16 }} title="风险台账">
        <ProTable
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
          ]}
        />
      </ProCard>
    </PageContainer>
  );
}
