import { AlertOutlined, AuditOutlined, CheckCircleOutlined, FieldTimeOutlined } from '@ant-design/icons';
import { PageContainer, ProCard, ProTable, StatisticCard } from '@ant-design/pro-components';
import { Tag } from 'antd';

const riskRows = [
  {
    id: 'risk-1',
    owner: '人力一组',
    metric: '高风险证书',
    count: 8,
    status: '需跟进',
  },
  {
    id: 'risk-2',
    owner: '人力二组',
    metric: '待复核识别',
    count: 15,
    status: '处理中',
  },
  {
    id: 'risk-3',
    owner: '人力共享服务',
    metric: '二次提醒',
    count: 4,
    status: '升级前',
  },
];

export default function DashboardPage() {
  return (
    <PageContainer title="Dashboard">
      <StatisticCard.Group direction="row">
        <StatisticCard
          statistic={{
            title: '即将到期',
            value: 42,
            icon: <FieldTimeOutlined />,
          }}
        />
        <StatisticCard
          statistic={{
            title: '已过期',
            value: 6,
            status: 'error',
            icon: <AlertOutlined />,
          }}
        />
        <StatisticCard
          statistic={{
            title: '待复核',
            value: 18,
            icon: <AuditOutlined />,
          }}
        />
        <StatisticCard
          statistic={{
            title: '覆盖率',
            value: 91.2,
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
          dataSource={riskRows}
          columns={[
            { title: '责任组', dataIndex: 'owner' },
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
