import {
  ModalForm,
  PageContainer,
  ProFormDatePicker,
  ProFormSelect,
  ProFormText,
  ProFormTextArea,
  ProCard,
  ProTable,
  type ActionType,
  type ProColumns,
} from '@ant-design/pro-components';
import { Alert, Button, Collapse, Descriptions, Drawer, Empty, Segmented, Space, Timeline, Typography, message as antdMessage } from 'antd';
import { useEffect, useMemo, useRef, useState } from 'react';

import {
  ExtractionQualitySummary,
  buildExtractionQuality,
  extractionSuspiciousPoints,
} from '@/components/ExtractionQualitySummary';
import type {
  CertificateType,
  Employee,
  ExtractedCertificate,
  ReviewApproveItem,
  ReviewApprovePayload,
  ReviewDecision,
  ReviewStatus,
  ReviewTask,
  ReviewTaskTrace,
} from '@/types/domain';
import { apiErrorMessage, isReviewStaleActionError, reviewStaleActionMessage } from '@/utils/apiErrors';
import {
  auditActionLabel,
  auditResourceTypeLabel,
  certificateStatusLabel,
  documentStatusLabel,
  reviewStatusLabel,
  reviewStatusValueEnum,
} from '@/utils/displayLabels';
import { emptyTableText } from '@/utils/emptyStates';
import { employeeSelectOption } from '@/utils/formOptions';
import { message } from '@/utils/messageApi';

interface RejectFormValues {
  reviewed_by?: string;
  notes?: string;
}

interface ReviewDecisionTarget {
  review: ReviewTask;
  status: Extract<ReviewStatus, 'REJECTED' | 'NEEDS_INFO'>;
}

function formatFileSize(value: number | undefined): string {
  if (!value) return '-';
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function traceValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '-';
  if (typeof value === 'object') return JSON.stringify(value, null, 2);
  return String(value);
}

function normalizePersonName(value: string | undefined): string {
  return (value || '').replace(/\s+/g, '').toLocaleLowerCase();
}

function employeeMatchesByHolderName(employees: Employee[], holderName: string | undefined): Employee[] {
  const normalizedHolderName = normalizePersonName(holderName);
  if (!normalizedHolderName) return [];
  return employees.filter((employee) => normalizePersonName(employee.name) === normalizedHolderName);
}

function autoMatchedEmployee(employees: Employee[], holderName: string | undefined): Employee | undefined {
  const matches = employeeMatchesByHolderName(employees, holderName);
  if (matches.length !== 1) return undefined;
  return matches[0].employment_status === 'LEFT' ? undefined : matches[0];
}

function employeeMatchWarning(employees: Employee[], holderName: string | undefined): string | undefined {
  if (!holderName) return undefined;
  const matches = employeeMatchesByHolderName(employees, holderName);
  if (matches.length === 0) return '没有找到同名员工，请先确认员工档案，或按工号手动选择正确员工。';
  if (matches.length > 1) return `存在 ${matches.length} 个同名员工，请按工号、部门和岗位手动选择，系统不会自动预填。`;
  if (matches[0].employment_status === 'LEFT') return '匹配到的员工已离职，不能生成新的当前正式证书。';
  return undefined;
}

function emptyApproveItem(): ReviewApproveItem {
  return {
    employee_id: '',
    certificate_type_id: '',
    holder_name: '',
  };
}

/** 从 review task 的 ai_output_json 构建 N 条证书表单初始值 */
function buildApproveItems(
  record: ReviewTask,
  employees: Employee[],
  certificateTypes: CertificateType[],
): ReviewApproveItem[] {
  const output = record.ai_output_json as { certificates?: ExtractedCertificate[] } | undefined;
  const certs = output?.certificates;
  if (!Array.isArray(certs) || certs.length === 0) {
    return [emptyApproveItem()];
  }
  return certs.map((cert) => {
    const holderName = cert.holder_name?.trim();
    const certificateName = cert.certificate_name?.trim();
    const matchedEmployee = autoMatchedEmployee(employees, holderName);
    const matchedCertificateType = certificateTypes.find((ct) => ct.name === certificateName);
    return {
      employee_id: matchedEmployee?.id || '',
      certificate_type_id: matchedCertificateType?.id || '',
      holder_name: holderName || '',
      certificate_no: cert.certificate_no,
      issuing_authority: cert.issuing_authority,
      issue_date: cert.issue_date,
      valid_from: cert.valid_from,
      valid_to: cert.valid_to,
      review_date: cert.review_date,
    };
  });
}

export default function ReviewQueuePage() {
  const actionRef = useRef<ActionType>();
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [certificateTypes, setCertificateTypes] = useState<CertificateType[]>([]);
  const [currentReview, setCurrentReview] = useState<ReviewTask>();
  const [certificateForms, setCertificateForms] = useState<ReviewApproveItem[]>([]);
  const [activeCertIndex, setActiveCertIndex] = useState(0);
  const [reviewedBy, setReviewedBy] = useState('');
  const [reviewNotes, setReviewNotes] = useState('');
  const [approving, setApproving] = useState(false);
  const [decisionTarget, setDecisionTarget] = useState<ReviewDecisionTarget>();
  const [traceOpen, setTraceOpen] = useState(false);
  const [traceLoading, setTraceLoading] = useState(false);
  const [currentTrace, setCurrentTrace] = useState<ReviewTaskTrace>();
  const [loadError, setLoadError] = useState<string>();
  const [staleActionError, setStaleActionError] = useState<string>();

  useEffect(() => {
    async function loadOptions() {
      const [employeeList, typeList] = await Promise.all([
        listResource<Employee>('/employees'),
        listResource<CertificateType>('/certificate-types'),
      ]);
      setEmployees(employeeList);
      setCertificateTypes(typeList);
    }

    void loadOptions().catch((error) => {
      message.error(error instanceof Error ? error.message : '基础数据加载失败');
    });
  }, []);

  function openApproveDrawer(record: ReviewTask) {
    setCurrentReview(record);
    setCertificateForms(buildApproveItems(record, employees, certificateTypes));
    setActiveCertIndex(0);
    setReviewedBy('');
    setReviewNotes(record.notes || '');
  }

  function updateActiveCert(patch: Partial<ReviewApproveItem>) {
    setCertificateForms((prev) => {
      const next = [...prev];
      next[activeCertIndex] = { ...next[activeCertIndex], ...patch };
      return next;
    });
  }

  function addCertificate() {
    setCertificateForms((prev) => [...prev, emptyApproveItem()]);
    setActiveCertIndex(certificateForms.length);
  }

  function removeCertificate(index: number) {
    if (certificateForms.length <= 1) return;
    setCertificateForms((prev) => prev.filter((_, i) => i !== index));
    setActiveCertIndex((prev) => Math.max(0, prev > index ? prev - 1 : prev));
  }

  async function handleApprove() {
    if (!currentReview) return;
    if (!reviewedBy.trim()) {
      antdMessage.warning('请输入复核人');
      return;
    }
    for (let i = 0; i < certificateForms.length; i++) {
      const item = certificateForms[i];
      if (!item.employee_id || !item.certificate_type_id || !item.holder_name?.trim()) {
        antdMessage.warning(`第 ${i + 1} 条证书缺少必填字段（员工、证书类型、持证人）`);
        return;
      }
    }

    const payload: ReviewApprovePayload = {
      certificates: certificateForms.map((item) => ({
        ...item,
        holder_name: item.holder_name.trim(),
      })),
      reviewed_by: reviewedBy.trim(),
      notes: reviewNotes.trim() || undefined,
      expected_updated_at: currentReview.updated_at,
    };

    setApproving(true);
    try {
      await postResource<ReviewDecision, ReviewApprovePayload>(
        `/reviews/${currentReview.id}/approve`,
        payload,
      );
      message.success(`复核通过，已生成 ${certificateForms.length} 条正式持证记录`);
      setCurrentReview(undefined);
      setStaleActionError(undefined);
      actionRef.current?.reload();
    } catch (error) {
      if (isReviewStaleActionError(error)) {
        const description = reviewStaleActionMessage(error);
        setStaleActionError(description);
        setCurrentReview(undefined);
        actionRef.current?.reload();
        message.warning(description);
      } else {
        message.error(apiErrorMessage(error, '复核提交失败'));
      }
    } finally {
      setApproving(false);
    }
  }

  async function handleReject(values: RejectFormValues): Promise<boolean> {
    if (!decisionTarget) return false;
    try {
      await postResource<
        ReviewTask,
        {
          status: ReviewDecisionTarget['status'];
          reviewed_by: string;
          notes?: string;
          expected_updated_at: string;
        }
      >(
        `/reviews/${decisionTarget.review.id}/reject`,
        {
          status: decisionTarget.status,
          reviewed_by: values.reviewed_by!.trim(),
          notes: values.notes,
          expected_updated_at: decisionTarget.review.updated_at,
        },
      );
      message.success(decisionTarget.status === 'NEEDS_INFO' ? '复核任务已标记为需补充' : '复核任务已驳回');
      setDecisionTarget(undefined);
      setStaleActionError(undefined);
      actionRef.current?.reload();
      return true;
    } catch (error) {
      if (isReviewStaleActionError(error)) {
        const description = reviewStaleActionMessage(error);
        setStaleActionError(description);
        setDecisionTarget(undefined);
        actionRef.current?.reload();
        message.warning(description);
        return false;
      }
      message.error(apiErrorMessage(error, '复核处理失败'));
      return false;
    }
  }

  async function openTrace(record: ReviewTask) {
    setTraceOpen(true);
    setTraceLoading(true);
    setCurrentTrace(undefined);
    try {
      const trace = await getResource<ReviewTaskTrace>(`/reviews/${record.id}/trace`);
      setCurrentTrace(trace);
    } catch (error) {
      message.error(error instanceof Error ? error.message : '复核追溯链路加载失败');
    } finally {
      setTraceLoading(false);
    }
  }

  const employeeOptions = useMemo(() => employees.map(employeeSelectOption), [employees]);
  const certificateTypeOptions = useMemo(
    () => certificateTypes.map((ct) => ({ label: ct.name, value: ct.id })),
    [certificateTypes],
  );

  const activeCert = certificateForms[activeCertIndex];
  const holderNameForWarning = activeCert?.holder_name;

  const columns: ProColumns<ReviewTask>[] = [
    { title: '文件', dataIndex: 'document_original_filename', ellipsis: true, renderText: (value) => value || '-' },
    { title: '文档 ID', dataIndex: 'document_id', ellipsis: true },
    {
      title: '识别字段',
      dataIndex: 'ai_output_json',
      width: 220,
      render: (_, record) => <ExtractionQualitySummary output={record.ai_output_json} compact />,
    },
    {
      title: '疑点',
      dataIndex: 'ai_output_json',
      ellipsis: true,
      render: (_, record) => {
        const suspiciousPoints = extractionSuspiciousPoints(record.ai_output_json);
        return suspiciousPoints.length > 0 ? suspiciousPoints.join('；') : '-';
      },
    },
    { title: '复核备注', dataIndex: 'notes', ellipsis: true, renderText: (value) => value || '-' },
    {
      title: '状态',
      dataIndex: 'status',
      width: 130,
      valueType: 'select',
      valueEnum: reviewStatusValueEnum,
    },
    { title: '创建时间', dataIndex: 'created_at', valueType: 'dateTime', width: 180 },
    {
      title: '操作',
      valueType: 'option',
      width: 210,
      render: (_, record) => (
        <Space>
          <Button
            size="small"
            type="link"
            danger={!buildExtractionQuality(record.ai_output_json).complete}
            onClick={() => openApproveDrawer(record)}
          >
            复核
          </Button>
          <Button size="small" type="link" onClick={() => openTrace(record)}>
            追溯
          </Button>
          <Button size="small" type="link" danger onClick={() => setDecisionTarget({ review: record, status: 'REJECTED' })}>
            驳回
          </Button>
          <Button size="small" type="link" onClick={() => setDecisionTarget({ review: record, status: 'NEEDS_INFO' })}>
            需补充
          </Button>
        </Space>
      ),
    },
  ];

  const certSegmentedOptions = certificateForms.map((_, index) => ({
    label: `证书 ${index + 1}/${certificateForms.length}`,
    value: index,
  }));

  return (
    <PageContainer title="待复核队列">
      {loadError ? (
        <Alert
          type="error"
          showIcon
          title="复核任务加载失败"
          description={loadError}
          style={{ marginBottom: 16 }}
          closable={{ onClose: () => setLoadError(undefined) }}
        />
      ) : null}
      {staleActionError ? (
        <Alert
          type="warning"
          showIcon
          title="复核任务状态已变化"
          description={staleActionError}
          action={
            <Button
              size="small"
              type="primary"
              onClick={() => {
                setStaleActionError(undefined);
                actionRef.current?.reload();
              }}
            >
              刷新队列
            </Button>
          }
          style={{ marginBottom: 16 }}
          closable={{ onClose: () => setStaleActionError(undefined) }}
        />
      ) : null}
      <ProTable<ReviewTask>
        actionRef={actionRef}
        rowKey="id"
        columns={columns}
        search={false}
        request={async () => {
          try {
            const data = await listResource<ReviewTask>('/reviews');
            setLoadError(undefined);
            return { data, success: true };
          } catch (error) {
            const description = error instanceof Error ? error.message : '复核任务加载失败';
            setLoadError(description);
            message.error(description);
            return { data: [], success: false };
          }
        }}
        locale={{ emptyText: emptyTableText('暂无待复核任务，请先上传证书并完成智能识别') }}
        toolbar={{ title: '智能识别后等待人力复核的证书' }}
      />

      <Drawer
        title="复核任务追溯"
        open={traceOpen}
        onClose={() => setTraceOpen(false)}
        size={820}
        loading={traceLoading}
      >
        {currentTrace ? (
          <Space orientation="vertical" size={16} style={{ width: '100%' }}>
            <ProCard title="复核任务">
              <Descriptions column={2} size="small">
                <Descriptions.Item label="任务状态">
                  {reviewStatusLabel(currentTrace.review_task.status)}
                </Descriptions.Item>
                <Descriptions.Item label="复核人">
                  {currentTrace.review_task.reviewed_by || '-'}
                </Descriptions.Item>
                <Descriptions.Item label="复核时间">
                  {currentTrace.review_task.reviewed_at || '-'}
                </Descriptions.Item>
                <Descriptions.Item label="更新时间">
                  {currentTrace.review_task.updated_at}
                </Descriptions.Item>
                <Descriptions.Item label="备注">
                  {currentTrace.review_task.notes || '-'}
                </Descriptions.Item>
              </Descriptions>
            </ProCard>

            <ProCard title="源文件">
              {currentTrace.source_document ? (
                <Descriptions column={1} size="small">
                  <Descriptions.Item label="文件名">
                    {currentTrace.source_document.original_filename}
                  </Descriptions.Item>
                  <Descriptions.Item label="文件状态">
                    {documentStatusLabel(currentTrace.source_document.status)}
                  </Descriptions.Item>
                  <Descriptions.Item label="文件类型">
                    {currentTrace.source_document.content_type || '-'}
                  </Descriptions.Item>
                  <Descriptions.Item label="文件大小">
                    {formatFileSize(currentTrace.source_document.file_size)}
                  </Descriptions.Item>
                  <Descriptions.Item label="SHA256">
                    <Typography.Text copyable={Boolean(currentTrace.source_document.sha256)}>
                      {currentTrace.source_document.sha256 || '-'}
                    </Typography.Text>
                  </Descriptions.Item>
                  <Descriptions.Item label="失败原因">
                    {currentTrace.source_document.failure_reason || '-'}
                  </Descriptions.Item>
                </Descriptions>
              ) : (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有关联源文件" />
              )}
            </ProCard>

            <ProCard title="AI 识别结果">
              {currentTrace.ai_result ? (
                <Space orientation="vertical" size={12} style={{ width: '100%' }}>
                  <ExtractionQualitySummary output={currentTrace.ai_result.output_json} />
                  <Descriptions column={2} size="small">
                    <Descriptions.Item label="识别批次号">
                      {currentTrace.ai_result.workflow_run_id || '-'}
                    </Descriptions.Item>
                    <Descriptions.Item label="模型">
                      {currentTrace.ai_result.model_name || '-'}
                    </Descriptions.Item>
                    <Descriptions.Item label="置信度">
                      {currentTrace.ai_result.confidence ?? '-'}
                    </Descriptions.Item>
                  </Descriptions>
                  <Typography.Paragraph copyable style={{ whiteSpace: 'pre-wrap' }}>
                    {traceValue(currentTrace.ai_result.output_json)}
                  </Typography.Paragraph>
                </Space>
              ) : (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有关联 AI 结果" />
              )}
            </ProCard>

            <ProCard title="正式持证记录">
              {currentTrace.certificate ? (
                <Descriptions column={2} size="small">
                  <Descriptions.Item label="持证人">
                    {currentTrace.certificate.holder_name}
                  </Descriptions.Item>
                  <Descriptions.Item label="证书编号">
                    {currentTrace.certificate.certificate_no || '-'}
                  </Descriptions.Item>
                  <Descriptions.Item label="状态">
                    {certificateStatusLabel(currentTrace.certificate.status)}
                  </Descriptions.Item>
                  <Descriptions.Item label="确认人">
                    {currentTrace.certificate.confirmed_by || '-'}
                  </Descriptions.Item>
                  <Descriptions.Item label="确认时间">
                    {currentTrace.certificate.confirmed_at || '-'}
                  </Descriptions.Item>
                  <Descriptions.Item label="到期日期">
                    {currentTrace.certificate.valid_to || '-'}
                  </Descriptions.Item>
                </Descriptions>
              ) : (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚未生成正式持证记录" />
              )}
            </ProCard>

            <ProCard title="审计记录">
              {currentTrace.audit_logs.length > 0 ? (
                <Timeline
                  items={currentTrace.audit_logs.map((log) => ({
                    content: (
                      <Space orientation="vertical" size={2}>
                        <Typography.Text>
                          {auditActionLabel(log.action)} / {auditResourceTypeLabel(log.resource_type)}
                        </Typography.Text>
                        <Typography.Text type="secondary">
                          {log.created_at} / {log.actor_name || '未知操作人'} / 请求 {log.request_id || '-'}
                        </Typography.Text>
                      </Space>
                    ),
                  }))}
                />
              ) : (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无关联审计记录" />
              )}
            </ProCard>

            <Collapse
              items={[
                {
                  key: 'decision-payload',
                  label: '复核决策载荷',
                  children: (
                    <Typography.Paragraph copyable style={{ whiteSpace: 'pre-wrap' }}>
                      {traceValue(currentTrace.review_task.decision_payload)}
                    </Typography.Paragraph>
                  ),
                },
              ]}
            />
          </Space>
        ) : (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无追溯数据" />
        )}
      </Drawer>

      <Drawer
        title="复核识别结果"
        open={Boolean(currentReview)}
        onClose={() => setCurrentReview(undefined)}
        destroyOnHidden
        mask={{ closable: false }}
        width={720}
        extra={
          <Space>
            <Button onClick={() => setCurrentReview(undefined)}>取消</Button>
            <Button type="primary" loading={approving} onClick={handleApprove}>
              确认全部 ({certificateForms.length})
            </Button>
          </Space>
        }
      >
        {currentReview && activeCert ? (
          <Space orientation="vertical" size={16} style={{ width: '100%' }}>
            <ProCard title="源文件">
              <Descriptions column={1} size="small">
                <Descriptions.Item label="文件名">
                  {currentReview.document_original_filename || '-'}
                </Descriptions.Item>
                <Descriptions.Item label="文件状态">
                  {documentStatusLabel(currentReview.document_status)}
                </Descriptions.Item>
                <Descriptions.Item label="文件大小">
                  {formatFileSize(currentReview.document_file_size)}
                </Descriptions.Item>
              </Descriptions>
              {currentReview.document_read_url ? (
                <Button type="primary" href={currentReview.document_read_url} target="_blank" rel="noreferrer">
                  打开源文件
                </Button>
              ) : (
                <Alert type="warning" showIcon title="暂时无法生成源文件预览链接" style={{ marginTop: 12 }} />
              )}
            </ProCard>

            <ProCard title="AI 识别质量">
              <ExtractionQualitySummary output={currentReview.ai_output_json} />
            </ProCard>

            {certificateForms.length > 1 ? (
              <ProCard
                title="证书切换"
                extra={
                  <Space>
                    <Button size="small" onClick={addCertificate}>添加证书</Button>
                    <Button size="small" danger onClick={() => removeCertificate(activeCertIndex)}>
                      删除当前
                    </Button>
                  </Space>
                }
              >
                <Segmented
                  options={certSegmentedOptions}
                  value={activeCertIndex}
                  onChange={(value) => setActiveCertIndex(value as number)}
                  block
                />
              </ProCard>
            ) : (
              <Space>
                <Button size="small" onClick={addCertificate}>添加证书</Button>
              </Space>
            )}

            {employeeMatchWarning(employees, holderNameForWarning) ? (
              <Alert
                type="warning"
                showIcon
                title="员工匹配需要人工确认"
                description={employeeMatchWarning(employees, holderNameForWarning)}
              />
            ) : null}

            <ProCard title={`证书 ${activeCertIndex + 1} 详情`}>
              <Space direction="vertical" size={12} style={{ width: '100%' }}>
                <ProFormSelect
                  label="员工"
                  options={employeeOptions}
                  showSearch
                  value={activeCert.employee_id}
                  onChange={(value) => updateActiveCert({ employee_id: value })}
                />
                <ProFormSelect
                  label="证书类型"
                  options={certificateTypeOptions}
                  showSearch
                  value={activeCert.certificate_type_id}
                  onChange={(value) => updateActiveCert({ certificate_type_id: value })}
                />
                <ProFormText
                  label="持证人"
                  value={activeCert.holder_name}
                  onChange={(e) => updateActiveCert({ holder_name: e.target.value })}
                />
                <ProFormText
                  label="证书编号"
                  value={activeCert.certificate_no}
                  onChange={(e) => updateActiveCert({ certificate_no: e.target.value })}
                />
                <ProFormText
                  label="发证机构"
                  value={activeCert.issuing_authority}
                  onChange={(e) => updateActiveCert({ issuing_authority: e.target.value })}
                />
                <ProFormDatePicker
                  label="发证日期"
                  value={activeCert.issue_date}
                  onChange={(_, dateStr) => updateActiveCert({ issue_date: dateStr as string })}
                />
                <ProFormDatePicker
                  label="有效开始"
                  value={activeCert.valid_from}
                  onChange={(_, dateStr) => updateActiveCert({ valid_from: dateStr as string })}
                />
                <ProFormDatePicker
                  label="有效截止"
                  tooltip="留空时，系统会按证书类型默认有效期和有效开始/发证日期自动计算"
                  value={activeCert.valid_to}
                  onChange={(_, dateStr) => updateActiveCert({ valid_to: dateStr as string })}
                />
                <ProFormDatePicker
                  label="复审日期"
                  value={activeCert.review_date}
                  onChange={(_, dateStr) => updateActiveCert({ review_date: dateStr as string })}
                />
              </Space>
            </ProCard>

            <ProCard title="复核信息（所有证书共享）">
              <Space direction="vertical" size={12} style={{ width: '100%' }}>
                <ProFormText
                  label="复核人"
                  value={reviewedBy}
                  onChange={(e) => setReviewedBy(e.target.value)}
                  placeholder="请输入复核人"
                />
                <ProFormTextArea
                  label="复核备注"
                  value={reviewNotes}
                  onChange={(e) => setReviewNotes(e.target.value)}
                />
              </Space>
            </ProCard>
          </Space>
        ) : null}
      </Drawer>

      <ModalForm<RejectFormValues>
        key={decisionTarget ? `${decisionTarget.review.id}-${decisionTarget.status}` : 'decision-empty'}
        title={decisionTarget?.status === 'NEEDS_INFO' ? '标记为需补充' : '驳回复核任务'}
        open={Boolean(decisionTarget)}
        onOpenChange={(value) => {
          if (!value) setDecisionTarget(undefined);
        }}
        modalProps={{
          destroyOnHidden: true,
          mask: { closable: false },
          okText: decisionTarget?.status === 'NEEDS_INFO' ? '标记需补充' : '驳回',
        }}
        submitter={{ submitButtonProps: { danger: decisionTarget?.status === 'REJECTED' } }}
        layout="horizontal"
        labelCol={{ span: 5 }}
        width={520}
        initialValues={{
          notes:
            decisionTarget?.status === 'NEEDS_INFO'
              ? '请补充或更换证书原件后重新识别'
              : '识别结果不符合证书入库要求',
        }}
        onFinish={handleReject}
      >
        <ProFormText name="reviewed_by" label="复核人" rules={[{ required: true, message: '请输入复核人' }]} />
        <ProFormTextArea
          name="notes"
          label={decisionTarget?.status === 'NEEDS_INFO' ? '补充说明' : '驳回原因'}
        />
      </ModalForm>
    </PageContainer>
  );
}