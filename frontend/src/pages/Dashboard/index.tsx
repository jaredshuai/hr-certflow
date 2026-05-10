import { AlertOutlined, AuditOutlined, CheckCircleOutlined, FieldTimeOutlined } from '@ant-design/icons';
import { PageContainer, ProCard, ProTable, StatisticCard } from '@ant-design/pro-components';
import { Alert, Tag } from 'antd';
import { useEffect, useMemo, useState } from 'react';

import { listResource } from '@/services/api';
import type { Employee, EmployeeCertificate, ReminderTask, ReviewTask } from '@/types/domain';

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

    return {
      expiringCount,
      expiredCount,
      pendingReviewCount,
      coverage,
      riskRows: buildRiskRows(data),
    };
  }, [data]);

  return (
    <PageContainer title="工作台">
      {loadError ? <Alert message="工作台数据加载失败" description={loadError} type="error" showIcon style={{ marginBottom: 16 }} /> : null}

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

      <ProCard style={{ marginTop: 16 }} title="风险台账" bordered>
        <ProTable
          rowKey="id"
          search={false}
          options={false}
          pagination={false}
          loading={loading}
          dataSource={metrics.riskRows}
          locale={{ emptyText: '暂无风险项' }}
          columns={[
            { title: '指标', dataIndex: 'metric' },
            { title: '数量', dataIndex: 'count', valueType: 'digit' },
            {
              title: '状态',
              dataIndex: 'status',
              render: (_, record) => <Tag color={record.status === '需跟进' ? 'red' : 'gold'}>{record.status}</Tag>,
            },
          ]}
        />
      </ProCard>
    </PageContainer>
  );
}
