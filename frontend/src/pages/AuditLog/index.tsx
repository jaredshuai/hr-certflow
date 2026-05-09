import { PageContainer, ProTable, type ProColumns } from '@ant-design/pro-components';

import { listResource } from '@/services/api';

interface AuditLogRow {
  id: string;
  actor_name?: string;
  action: string;
  resource_type: string;
  resource_id?: string;
  created_at: string;
}

const columns: ProColumns<AuditLogRow>[] = [
  { title: '操作者', dataIndex: 'actor_name', width: 140 },
  { title: '动作', dataIndex: 'action', width: 220 },
  { title: '资源类型', dataIndex: 'resource_type', width: 160 },
  { title: '资源 ID', dataIndex: 'resource_id', ellipsis: true },
  { title: '时间', dataIndex: 'created_at', valueType: 'dateTime', width: 180 },
];

export default function AuditLogPage() {
  return (
    <PageContainer title="审计日志">
      <ProTable<AuditLogRow>
        rowKey="id"
        columns={columns}
        request={async () => ({
          data: await listResource<AuditLogRow>('/audit-logs'),
          success: true,
        })}
        toolbar={{ title: '上传、智能识别、复核、提醒、反馈状态变更' }}
        search={{ labelWidth: 88 }}
      />
    </PageContainer>
  );
}
