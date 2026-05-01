import { PageContainer, ProTable, type ProColumns } from '@ant-design/pro-components';
import { Tag } from 'antd';

import { listResource } from '@/services/api';
import type { CertificateType } from '@/types/domain';

const columns: ProColumns<CertificateType>[] = [
  { title: '编码', dataIndex: 'code', width: 140 },
  { title: '证书类型', dataIndex: 'name' },
  { title: '发证机构', dataIndex: 'issuing_authority' },
  { title: '默认有效期(月)', dataIndex: 'default_validity_months', valueType: 'digit', width: 140 },
  {
    title: '强制复核',
    dataIndex: 'force_manual_review',
    valueType: 'select',
    valueEnum: {
      true: { text: '是' },
      false: { text: '否' },
    },
    render: (_, record) => <Tag color={record.force_manual_review ? 'gold' : 'green'}>{record.force_manual_review ? '是' : '否'}</Tag>,
  },
];

export default function CertificateTypesPage() {
  return (
    <PageContainer title="证书类型管理">
      <ProTable<CertificateType>
        rowKey="id"
        columns={columns}
        request={async () => ({
          data: await listResource<CertificateType>('/certificate-types'),
          success: true,
        })}
        toolbar={{ title: '证书类型' }}
        search={{ labelWidth: 96 }}
      />
    </PageContainer>
  );
}
