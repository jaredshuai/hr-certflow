import { PageContainer, ProTable, type ProColumns } from '@ant-design/pro-components';
import { Button, Modal, Space, Typography } from 'antd';
import { useState } from 'react';

import { listResource } from '@/services/api';
import { auditActionLabel, auditResourceTypeLabel } from '@/utils/displayLabels';

interface AuditLogRow {
  id: string;
  actor_name?: string;
  action: string;
  resource_type: string;
  resource_id?: string;
  before?: Record<string, unknown> | null;
  after?: Record<string, unknown> | null;
  created_at: string;
}

function JsonBlock({ value }: { value?: Record<string, unknown> | null }) {
  if (!value || Object.keys(value).length === 0) {
    return <Typography.Text type="secondary">无</Typography.Text>;
  }
  return (
    <pre style={{ maxHeight: 260, overflow: 'auto', padding: 12, background: '#f6f8fa' }}>
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

export default function AuditLogPage() {
  const [currentLog, setCurrentLog] = useState<AuditLogRow>();

  const columns: ProColumns<AuditLogRow>[] = [
    { title: '操作者', dataIndex: 'actor_name', width: 140 },
    { title: '动作', dataIndex: 'action', width: 220, renderText: (value) => auditActionLabel(value) },
    { title: '资源类型', dataIndex: 'resource_type', width: 160, renderText: (value) => auditResourceTypeLabel(value) },
    { title: '资源 ID', dataIndex: 'resource_id', ellipsis: true },
    { title: '时间', dataIndex: 'created_at', valueType: 'dateTime', width: 180 },
    {
      title: '详情',
      valueType: 'option',
      width: 88,
      render: (_, record) => (
        <Button type="link" size="small" onClick={() => setCurrentLog(record)}>
          查看
        </Button>
      ),
    },
  ];

  return (
    <PageContainer title="审计日志">
      <ProTable<AuditLogRow>
        rowKey="id"
        columns={columns}
        request={async () => ({
          data: await listResource<AuditLogRow>('/audit-logs'),
          success: true,
        })}
        locale={{ emptyText: '暂无审计日志，业务操作后会自动记录' }}
        toolbar={{ title: '上传、智能识别、复核、提醒、反馈状态变更' }}
        search={{ labelWidth: 88 }}
      />
      <Modal
        title="审计详情"
        open={Boolean(currentLog)}
        onCancel={() => setCurrentLog(undefined)}
        footer={null}
        width={760}
        destroyOnClose
      >
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          <Typography.Text type="secondary">变更前</Typography.Text>
          <JsonBlock value={currentLog?.before} />
          <Typography.Text type="secondary">变更后</Typography.Text>
          <JsonBlock value={currentLog?.after} />
        </Space>
      </Modal>
    </PageContainer>
  );
}
