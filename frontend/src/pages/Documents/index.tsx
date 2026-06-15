import { PageContainer, ProCard, ProTable, type ActionType, type ProColumns } from '@ant-design/pro-components';
import { Alert, Button, Collapse, Descriptions, Drawer, Empty, Popconfirm, Space, Timeline, Typography } from 'antd';
import { useMemo, useRef, useState } from 'react';

import { history, useLocation } from '@umijs/max';

import { getResource, pageResource, postResource } from '@/services/api';
import type {
  CertificateDocument,
  CertificateDocumentTrace,
  DocumentStatus,
  RecognitionDispatch,
  RecognitionStatus,
} from '@/types/domain';
import {
  auditActionLabel,
  auditResourceTypeLabel,
  certificateStatusLabel,
  documentStatusLabel,
  documentStatusValueEnum,
  reviewStatusLabel,
} from '@/utils/displayLabels';
import { downloadCsv } from '@/utils/download';
import { emptyTableText } from '@/utils/emptyStates';
import { message } from '@/utils/messageApi';
import { getCurrentOperator } from '@/utils/operatorContext';

function documentStatusFromSearch(search: string): DocumentStatus | undefined {
  const value = new URLSearchParams(search).get('status');
  if (!value || !(value in documentStatusValueEnum)) return undefined;
  return value as DocumentStatus;
}

function traceValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '-';
  if (typeof value === 'object') return JSON.stringify(value, null, 2);
  return String(value);
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
  const [traceOpen, setTraceOpen] = useState(false);
  const [traceLoading, setTraceLoading] = useState(false);
  const [currentTrace, setCurrentTrace] = useState<CertificateDocumentTrace>();

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
      await postResource<RecognitionDispatch>(
        `/documents/${record.id}/recognize-async?user=${encodeURIComponent(operator)}`,
      );

      const pollIntervalMs = 2000;
      const timeoutMs = 180000;
      const startTime = Date.now();
      let finished = false;

      while (Date.now() - startTime < timeoutMs) {
        await new Promise((resolve) => {
          setTimeout(resolve, pollIntervalMs);
        });
        const poll = await getResource<RecognitionStatus>(
          `/documents/${record.id}/recognition-status`,
        );

        if (poll.status === 'PENDING_REVIEW') {
          finished = true;
          message.success('重新识别已完成，已进入待复核队列');
          actionRef.current?.reload();
          history.push('/review-queue');
          break;
        }

        if (poll.status === 'FAILED') {
          throw new Error(poll.failure_reason || '重新识别失败');
        }
      }

      if (!finished) {
        message.warning('识别超时（超过 180 秒），请稍后刷新查看状态');
        actionRef.current?.reload();
      }
    } catch (error) {
      message.error(error instanceof Error ? error.message : '重新识别失败');
    } finally {
      setRunningAction(undefined);
    }
  }

  async function openTrace(record: CertificateDocument) {
    setTraceOpen(true);
    setTraceLoading(true);
    setCurrentTrace(undefined);
    try {
      const trace = await getResource<CertificateDocumentTrace>(`/documents/${record.id}/trace`);
      setCurrentTrace(trace);
    } catch (error) {
      message.error(error instanceof Error ? error.message : '文件追溯链路加载失败');
    } finally {
      setTraceLoading(false);
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
          <Button type="link" size="small" onClick={() => openTrace(record)}>
            追溯
          </Button>
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

      <Drawer
        title="文件全链路追溯"
        open={traceOpen}
        onClose={() => setTraceOpen(false)}
        size={840}
        loading={traceLoading}
      >
        {currentTrace ? (
          <Space orientation="vertical" size={16} style={{ width: '100%' }}>
            <ProCard title="源文件">
              <Descriptions column={1} size="small">
                <Descriptions.Item label="文件名">
                  {currentTrace.source_document.original_filename}
                </Descriptions.Item>
                <Descriptions.Item label="状态">
                  {documentStatusLabel(currentTrace.source_document.status)}
                </Descriptions.Item>
                <Descriptions.Item label="文件类型">
                  {currentTrace.source_document.content_type || '-'}
                </Descriptions.Item>
                <Descriptions.Item label="文件大小">
                  {currentTrace.source_document.file_size || '-'}
                </Descriptions.Item>
                <Descriptions.Item label="SHA256">
                  <Typography.Text copyable={Boolean(currentTrace.source_document.sha256)}>
                    {currentTrace.source_document.sha256 || '-'}
                  </Typography.Text>
                </Descriptions.Item>
                <Descriptions.Item label="对象 Key">
                  {currentTrace.source_document.storage_key}
                </Descriptions.Item>
                <Descriptions.Item label="失败原因">
                  {currentTrace.source_document.failure_reason || '-'}
                </Descriptions.Item>
              </Descriptions>
            </ProCard>

            <ProCard title={`AI 识别结果（${currentTrace.ai_results.length}）`}>
              {currentTrace.ai_results.length > 0 ? (
                <Collapse
                  items={currentTrace.ai_results.map((result, index) => ({
                    key: result.id,
                    label: `AI 结果 ${index + 1}：${result.model_name || result.workflow_run_id || result.id}`,
                    children: (
                      <Space orientation="vertical" size={8} style={{ width: '100%' }}>
                        <Descriptions column={2} size="small">
                          <Descriptions.Item label="工作流">
                            {result.workflow_run_id || '-'}
                          </Descriptions.Item>
                          <Descriptions.Item label="模型">
                            {result.model_name || '-'}
                          </Descriptions.Item>
                          <Descriptions.Item label="置信度">
                            {result.confidence ?? '-'}
                          </Descriptions.Item>
                          <Descriptions.Item label="原始快照">
                            {result.raw_response_key || '-'}
                          </Descriptions.Item>
                        </Descriptions>
                        <Typography.Paragraph copyable style={{ whiteSpace: 'pre-wrap' }}>
                          {traceValue(result.output_json)}
                        </Typography.Paragraph>
                      </Space>
                    ),
                  }))}
                />
              ) : (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无 AI 识别结果" />
              )}
            </ProCard>

            <ProCard title={`复核任务（${currentTrace.review_tasks.length}）`}>
              {currentTrace.review_tasks.length > 0 ? (
                <Timeline
                  items={currentTrace.review_tasks.map((task) => ({
                    color: task.status === 'APPROVED' ? 'green' : task.status === 'REJECTED' ? 'red' : 'blue',
                    content: (
                      <Space orientation="vertical" size={4}>
                        <Typography.Text strong>
                          {reviewStatusLabel(task.status)} / {task.reviewed_by || '未复核'}
                        </Typography.Text>
                        <Typography.Text type="secondary">
                          创建：{task.created_at} / 更新：{task.updated_at}
                        </Typography.Text>
                        <Typography.Text type="secondary">
                          备注：{task.notes || '-'}
                        </Typography.Text>
                      </Space>
                    ),
                  }))}
                />
              ) : (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无复核任务" />
              )}
            </ProCard>

            <ProCard title={`正式持证记录（${currentTrace.certificates.length}）`}>
              {currentTrace.certificates.length > 0 ? (
                <Timeline
                  items={currentTrace.certificates.map((certificate) => ({
                    color: certificate.status === 'ACTIVE' || certificate.status === 'EXPIRING' ? 'green' : 'gray',
                    content: (
                      <Space orientation="vertical" size={4}>
                        <Typography.Text strong>
                          {certificate.holder_name} / {certificate.certificate_no || '-'} /{' '}
                          {certificateStatusLabel(certificate.status)}
                        </Typography.Text>
                        <Typography.Text type="secondary">
                          确认：{certificate.confirmed_by || '-'} / {certificate.confirmed_at || '-'}
                        </Typography.Text>
                        <Typography.Text type="secondary">
                          到期：{certificate.valid_to || '-'}
                        </Typography.Text>
                      </Space>
                    ),
                  }))}
                />
              ) : (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚未生成正式持证记录" />
              )}
            </ProCard>

            <ProCard title={`关联审计记录（${currentTrace.audit_logs.length}）`}>
              {currentTrace.audit_logs.length > 0 ? (
                <Timeline
                  items={currentTrace.audit_logs.map((log) => ({
                    color: log.resource_type === 'certificate_document' ? 'blue' : 'gray',
                    content: (
                      <Space orientation="vertical" size={4}>
                        <Typography.Text strong>
                          {auditActionLabel(log.action)} / {auditResourceTypeLabel(log.resource_type)}
                        </Typography.Text>
                        <Typography.Text type="secondary">
                          {log.created_at} / 操作人：{log.actor_name || '未知'} / 请求：{log.request_id || '-'}
                        </Typography.Text>
                      </Space>
                    ),
                  }))}
                />
              ) : (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无关联审计记录" />
              )}
            </ProCard>
          </Space>
        ) : (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="请选择文件查看追溯链路" />
        )}
      </Drawer>
    </PageContainer>
  );
}
