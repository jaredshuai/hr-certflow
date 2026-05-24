import { PageContainer, ProTable, type ActionType, type ProColumns } from '@ant-design/pro-components';
import { Alert, Button, Popconfirm, Space, Typography } from 'antd';
import { useMemo, useRef, useState } from 'react';

import { history, useLocation } from '@umijs/max';

import { pageResource, postResource } from '@/services/api';
import type { AiExtractionResult, CertificateDocument, DocumentStatus } from '@/types/domain';
import { documentStatusValueEnum } from '@/utils/displayLabels';
import { downloadCsv } from '@/utils/download';
import { emptyTableText } from '@/utils/emptyStates';
import { message } from '@/utils/messageApi';
import { getCurrentOperator } from '@/utils/operatorContext';

function documentStatusFromSearch(search: string): DocumentStatus | undefined {
  const value = new URLSearchParams(search).get('status');
  if (!value || !(value in documentStatusValueEnum)) return undefined;
  return value as DocumentStatus;
}

export default function DocumentsPage() {
  const actionRef = useRef<ActionType>();
  const lastSearchParamsRef = useRef<Record<string, unknown>>({});
  const location = useLocation();
  const [loadError, setLoadError] = useState<string>();
  const [runningAction, setRunningAction] = useState<{
    documentId: string;
    action: 'confirm' | 'recognize';
  }>();

  const urlFilters = useMemo(() => {
    const status = documentStatusFromSearch(location.search);
    return status ? { status } : {};
  }, [location.search]);

  async function exportDocuments() {
    try {
      await downloadCsv('/documents/export.csv', lastSearchParamsRef.current, 'certificate-documents.csv');
      message.success('文件台账已开始导出');
    } catch (error) {
      message.error(error instanceof Error ? error.message : '文件台账导出失败');
    }
  }

  async function confirmUpload(record: CertificateDocument) {
    setRunningAction({ documentId: record.id, action: 'confirm' });
    try {
      await postResource<CertificateDocument>(`/documents/${record.id}/confirm-upload`);
      message.success('上传完整性已确认');
      actionRef.current?.reload();
    } catch (error) {
      message.error(error instanceof Error ? error.message : '确认上传失败');
    } finally {
      setRunningAction(undefined);
    }
  }

  async function recognizeDocument(record: CertificateDocument) {
    const operator = getCurrentOperator();
    if (!operator) {
      message.warning('请先在右上角填写当前操作人');
      return;
    }

    setRunningAction({ documentId: record.id, action: 'recognize' });
    try {
      await postResource<AiExtractionResult>(
        `/documents/${record.id}/recognize?user=${encodeURIComponent(operator)}`,
      );
      message.success('重新识别已完成，已进入待复核队列');
      actionRef.current?.reload();
      history.push('/review-queue');
    } catch (error) {
      message.error(error instanceof Error ? error.message : '重新识别失败');
    } finally {
      setRunningAction(undefined);
    }
  }

  function canConfirmUpload(record: CertificateDocument): boolean {
    return record.status === 'PENDING_UPLOAD' || (record.status === 'FAILED' && !record.sha256);
  }

  function canRecognize(record: CertificateDocument): boolean {
    return record.status === 'UPLOADED' || record.status === 'PENDING_REVIEW' || (record.status === 'FAILED' && Boolean(record.sha256));
  }

  const columns: ProColumns<CertificateDocument>[] = [
    { title: '文件名', dataIndex: 'original_filename', ellipsis: true },
    {
      title: '状态',
      dataIndex: 'status',
      width: 140,
      valueType: 'select',
      valueEnum: documentStatusValueEnum,
    },
    { title: '文件类型', dataIndex: 'content_type', width: 160, search: false, renderText: (value) => value || '-' },
    { title: '文件大小', dataIndex: 'file_size', valueType: 'digit', width: 120, search: false },
    { title: 'SHA256', dataIndex: 'sha256', ellipsis: true, search: false, renderText: (value) => value || '-' },
    { title: '存储 Key', dataIndex: 'storage_key', ellipsis: true, search: false },
    {
      title: '失败原因',
      dataIndex: 'failure_reason',
      ellipsis: true,
      search: false,
      renderText: (value) => value || '-',
    },
    { title: '创建时间', dataIndex: 'created_at', valueType: 'dateTime', width: 180, search: false },
    { title: '更新时间', dataIndex: 'updated_at', valueType: 'dateTime', width: 180, search: false },
    {
      title: '操作',
      valueType: 'option',
      width: 220,
      render: (_, record) => (
        <Space>
          <Button
            type="link"
            size="small"
            disabled={!canConfirmUpload(record)}
            loading={runningAction?.documentId === record.id && runningAction.action === 'confirm'}
            onClick={() => confirmUpload(record)}
          >
            确认上传
          </Button>
          <Popconfirm
            title="重新识别"
            description="重新识别会替换该文件上仍未完成的旧复核任务。"
            okText="重新识别"
            cancelText="取消"
            disabled={!canRecognize(record)}
            onConfirm={() => recognizeDocument(record)}
          >
            <Button
              type="link"
              size="small"
              disabled={!canRecognize(record)}
              loading={runningAction?.documentId === record.id && runningAction.action === 'recognize'}
            >
              重新识别
            </Button>
          </Popconfirm>
          {record.status === 'PENDING_REVIEW' ? (
            <Button type="link" size="small" onClick={() => history.push('/review-queue')}>
              去复核
            </Button>
          ) : null}
        </Space>
      ),
    },
  ];

  return (
    <PageContainer title="文件台账">
      {loadError ? (
        <Alert
          type="error"
          showIcon
          title="文件台账加载失败"
          description={loadError}
          style={{ marginBottom: 16 }}
          closable={{ onClose: () => setLoadError(undefined) }}
        />
      ) : null}
      <ProTable<CertificateDocument>
        actionRef={actionRef}
        rowKey="id"
        columns={columns}
        params={urlFilters}
        request={async (params) => {
          try {
            const { current, pageSize, ...searchParams } = params;
            lastSearchParamsRef.current = searchParams;
            const result = await pageResource<CertificateDocument>('/documents/page', {
              ...searchParams,
              current,
              page_size: pageSize,
            });
            setLoadError(undefined);
            return { data: result.data, total: result.total, success: true };
          } catch (error) {
            const description = error instanceof Error ? error.message : '文件台账加载失败';
            setLoadError(description);
            message.error(description);
            return { data: [], success: false };
          }
        }}
        locale={{ emptyText: emptyTableText('暂无证书文件，请先在上传识别页上传原件') }}
        toolbar={{
          title: <Typography.Text>上传原件、识别状态、失败原因和对象存储校验结果</Typography.Text>,
          actions: [
            <Button key="export" onClick={exportDocuments}>
              导出当前筛选
            </Button>,
          ],
        }}
        pagination={{ defaultPageSize: 20, showSizeChanger: true }}
        search={{ labelWidth: 88 }}
      />
    </PageContainer>
  );
}
