import { Column, Pie } from '@ant-design/charts';
import { PageContainer, ProCard, ProTable, StatisticCard, type ProColumns } from '@ant-design/pro-components';
import { Alert, Button, Empty } from 'antd';
import { useEffect, useMemo, useState } from 'react';

import { history } from '@umijs/max';

import { getResource } from '@/services/api';
import type {
  CertificateCoverageDepartmentRow,
  CertificateCoverageReport,
  CertificateTypeRiskRow,
  ReportChartRow,
} from '@/types/domain';
import { downloadCsv } from '@/utils/download';
import { emptyTableText } from '@/utils/emptyStates';
import { useChartHeight } from '@/utils/useChartHeight';
import { certificateTypeRequiredValueEnum } from '@/utils/displayLabels';
import { message } from '@/utils/messageApi';

const emptyReport: CertificateCoverageReport = {
  employee_count: 0,
  covered_employee_count: 0,
  coverage: 0,
  department_rows: [],
  certificate_type_risk_rows: [],
  expiry_month_rows: [],
};

interface ChartClickEvent<T extends { target_path?: string }> {
  type?: string;
  data?: {
    data?: Partial<T>;
    datum?: Partial<T>;
  };
}

function chartTargetPath<T extends { target_path?: string }>(event: unknown): string | undefined {
  const chartEvent = event as ChartClickEvent<T>;
  const datum = chartEvent.data?.data ?? chartEvent.data?.datum;
  return typeof datum?.target_path === 'string' ? datum.target_path : undefined;
}

type CertificateRiskBreakdownRow = {
  category: string;
  count: number;
  target_path: string;
};

export default function ReportsPage() {
  const chartHeight = useChartHeight();
  const [report, setReport] = useState<CertificateCoverageReport>(emptyReport);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string>();

  useEffect(() => {
    let cancelled = false;

    async function loadReport() {
      setLoading(true);
      setLoadError(undefined);
      try {
        const response = await getResource<CertificateCoverageReport>('/reports/certificate-coverage');
        if (!cancelled) {
          setReport(response);
        }
      } catch (error) {
        if (!cancelled) {
          setReport(emptyReport);
          setLoadError(error instanceof Error ? error.message : '统计报表加载失败');
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void loadReport();
    return () => {
      cancelled = true;
    };
  }, []);

  async function exportReport() {
    try {
      await downloadCsv('/reports/certificate-coverage/export.csv', {}, 'certificate-coverage-report.csv');
      message.success('统计报表已开始导出');
    } catch (error) {
      message.error(error instanceof Error ? error.message : '统计报表导出失败');
    }
  }

  function handleChartEvent<T extends { target_path?: string }>(event: unknown) {
    const chartEvent = event as ChartClickEvent<T>;
    if (chartEvent.type !== 'element:click') return;
    const targetPath = chartTargetPath<T>(chartEvent);
    if (targetPath) history.push(targetPath);
  }

  const certificateRiskBreakdownRows = useMemo<CertificateRiskBreakdownRow[]>(
    () =>
      report.certificate_type_risk_rows.flatMap((row) => [
        {
          category: `${row.certificate_type_name} / 即将到期`,
          count: row.expiring_count,
          target_path: row.expiring_target_path,
        },
        {
          category: `${row.certificate_type_name} / 已过期`,
          count: row.expired_count,
          target_path: row.expired_target_path,
        },
        {
          category: `${row.certificate_type_name} / 缺失员工`,
          count: row.missing_employee_count,
          target_path: row.missing_employee_target_path,
        },
      ]).filter((row) => row.count > 0),
    [report.certificate_type_risk_rows],
  );

  const riskColumns: ProColumns<CertificateTypeRiskRow>[] = [
    { title: '证书类型', dataIndex: 'certificate_type_name' },
    {
      title: '策略',
      dataIndex: 'is_required',
      width: 90,
      valueType: 'select',
      valueEnum: certificateTypeRequiredValueEnum,
      renderText: (val: boolean) => String(val),
    },
    {
      title: '有效数',
      dataIndex: 'active_count',
      valueType: 'digit',
      width: 90,
      render: (_, record) => (
        <Button type="link" size="small" disabled={record.active_count === 0} onClick={() => history.push(record.active_target_path)}>
          {record.active_count}
        </Button>
      ),
    },
    {
      title: '即将到期',
      dataIndex: 'expiring_count',
      valueType: 'digit',
      width: 110,
      render: (_, record) => (
        <Button type="link" size="small" disabled={record.expiring_count === 0} onClick={() => history.push(record.expiring_target_path)}>
          {record.expiring_count}
        </Button>
      ),
    },
    {
      title: '已过期',
      dataIndex: 'expired_count',
      valueType: 'digit',
      width: 90,
      render: (_, record) => (
        <Button type="link" size="small" disabled={record.expired_count === 0} onClick={() => history.push(record.expired_target_path)}>
          {record.expired_count}
        </Button>
      ),
    },
    {
      title: '缺失员工数',
      dataIndex: 'missing_employee_count',
      valueType: 'digit',
      width: 120,
      render: (_, record) => (
        <Button
          type="link"
          size="small"
          disabled={record.missing_employee_count === 0}
          onClick={() => history.push(record.missing_employee_target_path)}
        >
          {record.missing_employee_count}
        </Button>
      ),
    },
    { title: '风险合计', dataIndex: 'risk_count', valueType: 'digit', width: 100 },
    {
      title: '操作',
      valueType: 'option',
      width: 100,
      render: (_, record) => (
        <Button type="link" size="small" onClick={() => history.push(record.target_path)}>
          查看明细
        </Button>
      ),
    },
  ];

  return (
    <PageContainer
      title="统计报表"
      extra={
        <Button type="primary" onClick={exportReport}>
          导出报表
        </Button>
      }
    >
      {loadError ? (
        <Alert
          title="统计报表加载失败"
          description={loadError}
          type="error"
          showIcon
          style={{ marginBottom: 16 }}
        />
      ) : null}

      <StatisticCard.Group direction="row">
        <StatisticCard loading={loading} statistic={{ title: '在职员工数', value: report.employee_count }} />
        <StatisticCard loading={loading} statistic={{ title: '已覆盖员工', value: report.covered_employee_count }} />
        <StatisticCard
          loading={loading}
          statistic={{ title: '证书覆盖率', value: report.coverage, suffix: '%', status: 'success' }}
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
        <ProCard title="部门覆盖率" loading={loading}>
          {report.department_rows.length > 0 ? (
            <Column
              data={report.department_rows}
              xField="department"
              yField="coverage"
              height={chartHeight}
              label={{ text: 'coverage', position: 'top' }}
              tooltip={{ title: 'department', items: [{ field: 'coverage', name: '覆盖率' }] }}
              onEvent={(_, event) => handleChartEvent<CertificateCoverageDepartmentRow>(event)}
            />
          ) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无部门覆盖数据" />
          )}
        </ProCard>

        <ProCard title="证书类型风险分布" loading={loading}>
          {certificateRiskBreakdownRows.length > 0 ? (
            <Pie
              data={certificateRiskBreakdownRows}
              angleField="count"
              colorField="category"
              height={chartHeight}
              innerRadius={0.62}
              legend={{ color: { position: 'bottom' } }}
              tooltip={{ title: 'category', items: [{ field: 'count', name: '风险数' }] }}
              onEvent={(_, event) => handleChartEvent<CertificateRiskBreakdownRow>(event)}
            />
          ) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无证书类型风险" />
          )}
        </ProCard>

        <ProCard title="到期月份趋势" loading={loading}>
          {report.expiry_month_rows.length > 0 ? (
            <Column
              data={report.expiry_month_rows}
              xField="category"
              yField="count"
              height={chartHeight}
              label={{ text: 'count', position: 'top' }}
              tooltip={{ title: 'category', items: [{ field: 'count', name: '风险证书数' }] }}
              onEvent={(_, event) => handleChartEvent<ReportChartRow>(event)}
            />
          ) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无到期趋势数据" />
          )}
        </ProCard>
      </div>

      <ProCard title="证书类型风险清单" style={{ marginTop: 16 }}>
        <ProTable<CertificateTypeRiskRow>
          rowKey="certificate_type_id"
          search={false}
          options={false}
          pagination={false}
          loading={loading}
          columns={riskColumns}
          dataSource={report.certificate_type_risk_rows}
          locale={{ emptyText: emptyTableText('暂无证书类型风险数据') }}
        />
      </ProCard>
    </PageContainer>
  );
}
