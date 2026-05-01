import { PageContainer, ProTable, type ProColumns } from '@ant-design/pro-components';
import { Tag } from 'antd';

import { listResource } from '@/services/api';
import type { EmployeeCertificate } from '@/types/domain';

const statusColor: Record<string, string> = {
  ACTIVE: 'green',
  EXPIRING: 'gold',
  EXPIRED: 'red',
  PENDING_REVIEW: 'blue',
  REPLACED: 'default',
  ARCHIVED: 'default',
};

const columns: ProColumns<EmployeeCertificate>[] = [
  { title: '持证人', dataIndex: 'holder_name', width: 140 },
  { title: '证书编号', dataIndex: 'certificate_no', width: 180 },
  { title: '发证机构', dataIndex: 'issuing_authority' },
  { title: '发证日期', dataIndex: 'issue_date', valueType: 'date', width: 130 },
  { title: '到期日期', dataIndex: 'valid_to', valueType: 'date', width: 130 },
  {
    title: '状态',
    dataIndex: 'status',
    width: 130,
    render: (_, record) => <Tag color={statusColor[record.status] || 'default'}>{record.status}</Tag>,
  },
];

export default function CertificatesPage() {
  return (
    <PageContainer title="持证记录">
      <ProTable<EmployeeCertificate>
        rowKey="id"
        columns={columns}
        request={async () => ({
          data: await listResource<EmployeeCertificate>('/certificates'),
          success: true,
        })}
        toolbar={{ title: '当前与历史持证记录' }}
        search={{ labelWidth: 88 }}
      />
    </PageContainer>
  );
}
