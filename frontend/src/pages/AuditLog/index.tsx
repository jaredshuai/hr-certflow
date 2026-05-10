import { PageContainer, ProTable, type ProColumns } from '@ant-design/pro-components';
import { Alert, Button, Collapse, Modal, Typography } from 'antd';
import { useState } from 'react';

import { listResource } from '@/services/api';
import { auditActionLabel, auditResourceTypeLabel } from '@/utils/displayLabels';
import { emptyTableText } from '@/utils/emptyStates';
import { message } from '@/utils/messageApi';

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
  const text = JSON.stringify(value, null, 2);
  return (
    <Typography.Paragraph
      copyable={{ text, tooltips: ['复制 JSON', '已复制'] }}
      style={{ marginBottom: 0 }}
    >
      <pre
        style={{
          maxHeight: 260,
          overflow: 'auto',
          padding: 12,
          margin: 0,
          background: '#f6f8fa',
          borderRadius: 6,
        }}
      >
        {text}
      </pre>
    </Typography.Paragraph>
  );
}

export default function AuditLogPage() {
  const [currentLog, setCurrentLog] = useState<AuditLogRow>();
  const [loadError, setLoadError] = useState<string>();

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
      {loadError ? (
        <Alert
          type="error"
          showIcon
          title="审计日志加载失败"
          description={loadError}
          style={{ marginBottom: 16 }}
          closable={{ onClose: () => setLoadError(undefined) }}
        />
      ) : null}
      <ProTable<AuditLogRow>
        rowKey="id"
        columns={columns}
        request={async () => {
          try {
            const data = await listResource<AuditLogRow>('/audit-logs');
            setLoadError(undefined);
            return { data, success: true };
          } catch (error) {
            const description = error instanceof Error ? error.message : '审计日志加载失败';
            setLoadError(description);
            message.error(description);
            return { data: [], success: false };
          }
        }}
        locale={{ emptyText: emptyTableText('暂无审计日志，业务操作后会自动记录') }}
        toolbar={{ title: '上传、智能识别、复核、提醒、反馈状态变更' }}
        search={{ labelWidth: 88 }}
      />
      <Modal
        title="审计详情"
        open={Boolean(currentLog)}
        onCancel={() => setCurrentLog(undefined)}
        footer={null}
        width={760}
        destroyOnHidden
      >
        <Collapse
          defaultActiveKey={['before', 'after']}
          items={[
            {
              key: 'before',
              label: '变更前',
              children: <JsonBlock value={currentLog?.before} />,
            },
            {
              key: 'after',
              label: '变更后',
              children: <JsonBlock value={currentLog?.after} />,
            },
          ]}
        />
      </Modal>
    </PageContainer>
  );
}
