import { InboxOutlined, RobotOutlined, SaveOutlined, UploadOutlined } from '@ant-design/icons';
import {
  PageContainer,
  ProCard,
  ProDescriptions,
  ProForm,
  ProFormDatePicker,
  ProFormSelect,
  ProFormText,
} from '@ant-design/pro-components';
import { Alert, Button, Divider, Form, Input, Result, Space, Steps, Typography, Upload } from 'antd';
import { useMemo, useState } from 'react';

import { ExtractionQualitySummary, outputText } from '@/components/ExtractionQualitySummary';
import { listResource, postResource } from '@/services/api';
import type {
  AiExtractionResult,
  CertificateDocument,
  ReviewApprovePayload,
  ReviewDecision,
  ReviewTask,
  UploadIntent,
} from '@/types/domain';
import { documentStatusLabel } from '@/utils/displayLabels';
import { certificateTypeSelectRequest, employeeSelectRequest } from '@/utils/formOptions';
import { message } from '@/utils/messageApi';

interface CertificateFormValues {
  employee_id?: string;
  certificate_type_id?: string;
  holder_name?: string;
  certificate_name?: string;
  certificate_no?: string;
  issuing_authority?: string;
  issue_date?: unknown;
  valid_from?: unknown;
  valid_to?: unknown;
  review_date?: unknown;
  reviewed_by?: string;
  notes?: string;
}

const MAX_UPLOAD_SIZE_BYTES = 20 * 1024 * 1024;
const ALLOWED_UPLOAD_CONTENT_TYPES = new Set([
  'application/pdf',
  'image/jpeg',
  'image/png',
  'image/webp',
  'image/tiff',
]);

function isAllowedUploadFile(file: File): boolean {
  const contentType = file.type;
  const lowerName = file.name.toLowerCase();
  return (
    ALLOWED_UPLOAD_CONTENT_TYPES.has(contentType) ||
    lowerName.endsWith('.pdf') ||
    lowerName.endsWith('.jpg') ||
    lowerName.endsWith('.jpeg') ||
    lowerName.endsWith('.png') ||
    lowerName.endsWith('.webp') ||
    lowerName.endsWith('.tif') ||
    lowerName.endsWith('.tiff')
  );
}

function validateUploadFile(file: File): boolean {
  if (file.size > MAX_UPLOAD_SIZE_BYTES) {
    message.warning('文件不能超过 20MB');
    return false;
  }
  if (!isAllowedUploadFile(file)) {
    message.warning('仅支持 PDF、JPG、PNG、WEBP、TIFF 格式');
    return false;
  }
  return true;
}

function formatDateValue(value: unknown): string | undefined {
  if (!value) return undefined;
  if (typeof value === 'string') return value.slice(0, 10);
  if (typeof value === 'object' && value && 'format' in value && typeof value.format === 'function') {
    return value.format('YYYY-MM-DD');
  }
  return undefined;
}

type FlowStep = 'select' | 'upload' | 'recognize' | 'confirm' | 'done';

const STEP_INDEX: Record<FlowStep, number> = {
  select: 0,
  upload: 1,
  recognize: 2,
  confirm: 3,
  done: 3,
};

export default function UploadRecognitionPage() {
  const [form] = Form.useForm<CertificateFormValues>();
  const [selectedFile, setSelectedFile] = useState<File>();
  const [documentId, setDocumentId] = useState<string>();
  const [reviewTaskId, setReviewTaskId] = useState<string>();
  const [reviewTaskUpdatedAt, setReviewTaskUpdatedAt] = useState<string>();
  const [documentStatus, setDocumentStatus] = useState('未上传');
  const [recognitionStatus, setRecognitionStatus] = useState('未识别');
  const [recognitionActor, setRecognitionActor] = useState('');
  const [uploading, setUploading] = useState(false);
  const [recognizing, setRecognizing] = useState(false);
  const [approving, setApproving] = useState(false);
  const [extractionResult, setExtractionResult] = useState<AiExtractionResult>();
  const [errorMessage, setErrorMessage] = useState<string>();

  const flowStep: FlowStep = useMemo(() => {
    if (documentStatus === 'CONFIRMED') return 'done';
    if (reviewTaskId && extractionResult) return 'confirm';
    if (documentId) return 'recognize';
    if (selectedFile) return 'upload';
    return 'select';
  }, [documentStatus, reviewTaskId, extractionResult, documentId, selectedFile]);

  const currentStepIndex = STEP_INDEX[flowStep];
  const submitting = uploading || recognizing || approving;

  async function findPendingReviewTask(targetDocumentId: string) {
    const pendingReviews = await listResource<ReviewTask>('/reviews?status=PENDING');
    const review = pendingReviews.find((item) => item.document_id === targetDocumentId);
    setReviewTaskId(review?.id);
    setReviewTaskUpdatedAt(review?.updated_at);
    return review;
  }

  async function recognizeDocument(targetDocumentId: string, actor: string) {
    setRecognitionStatus('识别中');
    const result = await postResource<AiExtractionResult>(
      `/documents/${targetDocumentId}/recognize?user=${encodeURIComponent(actor)}`,
    );
    setExtractionResult(result);
    setRecognitionStatus('待人工确认');
    setDocumentStatus('PENDING_REVIEW');
    await findPendingReviewTask(targetDocumentId);

    const output = result.output_json;
    form.setFieldsValue({
      holder_name: outputText(output, 'holder_name'),
      certificate_name: outputText(output, 'certificate_name'),
      certificate_no: outputText(output, 'certificate_no'),
      issuing_authority: outputText(output, 'issuing_authority'),
      issue_date: outputText(output, 'issue_date'),
      valid_from: outputText(output, 'valid_from'),
      valid_to: outputText(output, 'valid_to'),
      review_date: outputText(output, 'review_date'),
    });
  }

  async function uploadAndRecognize() {
    if (!selectedFile) {
      message.warning('请先选择证书图片或 PDF');
      return;
    }
    if (!validateUploadFile(selectedFile)) {
      return;
    }
    const actor = recognitionActor.trim();
    if (!actor) {
      message.warning('请先填写识别操作人');
      return;
    }
    if (submitting) return;

    setErrorMessage(undefined);
    setUploading(true);
    try {
      const intent = await postResource<
        UploadIntent,
        { original_filename: string; content_type?: string; file_size: number }
      >('/documents/upload-intents', {
        original_filename: selectedFile.name,
        content_type: selectedFile.type || undefined,
        file_size: selectedFile.size,
      });
      setDocumentId(intent.document_id);
      setDocumentStatus('PENDING_UPLOAD');

      const uploadResponse = await fetch(intent.upload_url, {
        method: 'PUT',
        headers: {
          'Content-Type': selectedFile.type || 'application/octet-stream',
        },
        body: selectedFile,
      });
      if (!uploadResponse.ok) {
        throw new Error(`对象存储上传失败: ${uploadResponse.status}`);
      }

      const confirmedDocument = await postResource<CertificateDocument>(
        `/documents/${intent.document_id}/confirm-upload`,
      );
      setDocumentStatus(confirmedDocument.status);
      setUploading(false);
      setRecognizing(true);
      try {
        await recognizeDocument(intent.document_id, actor);
        message.success('上传和识别已完成，请复核后确认');
      } finally {
        setRecognizing(false);
      }
    } catch (error) {
      setRecognitionStatus('识别失败');
      const description = error instanceof Error ? error.message : '上传识别失败';
      setErrorMessage(description);
      message.error(description);
      setUploading(false);
      setRecognizing(false);
    }
  }

  async function rerunRecognition() {
    if (!documentId) {
      message.warning('请先上传文件');
      return;
    }
    const actor = recognitionActor.trim();
    if (!actor) {
      message.warning('请先填写识别操作人');
      return;
    }
    if (submitting) return;

    setErrorMessage(undefined);
    setRecognizing(true);
    try {
      await recognizeDocument(documentId, actor);
      message.success('重新识别已完成');
    } catch (error) {
      setRecognitionStatus('识别失败');
      const description = error instanceof Error ? error.message : '重新识别失败';
      setErrorMessage(description);
      message.error(description);
    } finally {
      setRecognizing(false);
    }
  }

  async function approveReview() {
    if (!reviewTaskId) {
      message.error('没有可确认的复核任务，请先完成识别');
      return;
    }
    if (submitting) return;

    let values: CertificateFormValues;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }

    const payload: ReviewApprovePayload = {
      employee_id: values.employee_id!,
      certificate_type_id: values.certificate_type_id!,
      certificate_no: values.certificate_no,
      holder_name: values.holder_name!,
      issuing_authority: values.issuing_authority,
      issue_date: formatDateValue(values.issue_date),
      valid_from: formatDateValue(values.valid_from),
      valid_to: formatDateValue(values.valid_to),
      review_date: formatDateValue(values.review_date),
      reviewed_by: values.reviewed_by!.trim(),
      notes: values.notes,
      expected_updated_at: reviewTaskUpdatedAt!,
    };

    setApproving(true);
    try {
      await postResource<ReviewDecision, ReviewApprovePayload>(`/reviews/${reviewTaskId}/approve`, payload);
      setDocumentStatus('CONFIRMED');
      setRecognitionStatus('已确认');
      setReviewTaskId(undefined);
      setReviewTaskUpdatedAt(undefined);
      message.success('已生成正式持证记录');
    } catch (error) {
      message.error(error instanceof Error ? error.message : '确认失败');
    } finally {
      setApproving(false);
    }
  }

  function resetFlow() {
    setSelectedFile(undefined);
    setDocumentId(undefined);
    setReviewTaskId(undefined);
    setReviewTaskUpdatedAt(undefined);
    setExtractionResult(undefined);
    setDocumentStatus('未上传');
    setRecognitionStatus('未识别');
    setErrorMessage(undefined);
    form.resetFields();
  }

  const showConfirmReady =
    flowStep === 'confirm' && extractionResult && reviewTaskId && documentStatus !== 'CONFIRMED';

  return (
    <PageContainer title="上传识别">
      <ProCard style={{ marginBottom: 16 }}>
        <Steps
          current={currentStepIndex}
          status={errorMessage ? 'error' : flowStep === 'done' ? 'finish' : 'process'}
          items={[
            { title: '选择文件', content: '拖拽证书原件' },
            { title: '上传原件', content: '推送至对象存储' },
            { title: 'AI 识别', content: '调用智能识别' },
            { title: '人工确认', content: '复核并入库' },
          ]}
        />
      </ProCard>

      {errorMessage ? (
        <Alert
          type="error"
          showIcon
          title="流程出现错误"
          description={errorMessage}
          closable={{ onClose: () => setErrorMessage(undefined) }}
          style={{ marginBottom: 16 }}
        />
      ) : null}

      {flowStep === 'done' ? (
        <ProCard style={{ marginBottom: 16 }}>
          <Result
            status="success"
            title="证书已确认入库"
            subTitle="后续可在持证记录中查看与维护，提醒任务也会自动生成。"
            extra={[
              <Button key="next" type="primary" onClick={resetFlow}>
                继续上传下一份
              </Button>,
            ]}
          />
        </ProCard>
      ) : null}

      {showConfirmReady ? (
        <Alert
          type="info"
          showIcon
          title="智能识别完成，请人工复核字段后确认入库"
          style={{ marginBottom: 16 }}
        />
      ) : null}

      <div className="certflow-upload-grid">
        <ProCard title="证书原件">
          <Upload.Dragger
            multiple={false}
            maxCount={1}
            disabled={submitting}
            beforeUpload={(file) => {
              if (!validateUploadFile(file)) {
                return Upload.LIST_IGNORE;
              }
              setSelectedFile(file);
              setDocumentId(undefined);
              setReviewTaskId(undefined);
              setExtractionResult(undefined);
              setDocumentStatus('待上传');
              setRecognitionStatus('未识别');
              setErrorMessage(undefined);
              message.info('已选择文件');
              return false;
            }}
          >
            <p className="ant-upload-drag-icon">
              <InboxOutlined />
            </p>
            <p className="ant-upload-text">拖拽证书图片或 PDF 到这里</p>
            <p className="ant-upload-hint">支持证书原图、扫描件、PDF 文件</p>
          </Upload.Dragger>

          <Divider />

          <Space style={{ marginBottom: 16 }} wrap>
            <Typography.Text>识别操作人</Typography.Text>
            <Input
              aria-label="识别操作人"
              value={recognitionActor}
              onChange={(event) => setRecognitionActor(event.target.value)}
              style={{ width: 150 }}
              disabled={submitting}
            />
            <Button
              type="primary"
              icon={<UploadOutlined />}
              disabled={!selectedFile || submitting || Boolean(documentId)}
              loading={uploading || (recognizing && !documentId)}
              onClick={uploadAndRecognize}
            >
              上传并识别
            </Button>
            <Button
              icon={<RobotOutlined />}
              disabled={!documentId || submitting}
              loading={recognizing && Boolean(documentId)}
              onClick={rerunRecognition}
            >
              重新识别
            </Button>
          </Space>

          <ProDescriptions
            size="small"
            column={1}
            dataSource={{
              status: documentStatus,
              file: selectedFile?.name || '未选择',
              ai: recognitionStatus,
              result: extractionResult?.model_name || extractionResult?.workflow_run_id || '-',
            }}
            columns={[
              { title: '状态', dataIndex: 'status', render: (text) => documentStatusLabel(String(text)) },
              { title: '当前文件', dataIndex: 'file' },
              { title: '识别结果', dataIndex: 'ai' },
              { title: '模型/工作流', dataIndex: 'result' },
            ]}
          />
          <Divider />
          <ExtractionQualitySummary output={extractionResult?.output_json} />
        </ProCard>

        <ProCard
          title="智能预填与人工确认"
          extra={
            <Button
              type="primary"
              icon={<SaveOutlined />}
              disabled={!reviewTaskId || submitting || documentStatus === 'CONFIRMED'}
              loading={approving}
              onClick={approveReview}
            >
              确认为正式证书
            </Button>
          }
        >
          <ProForm form={form} submitter={false} layout="horizontal" labelCol={{ span: 5 }}>
            <ProFormSelect
              name="employee_id"
              label="员工"
              rules={[{ required: true, message: '请选择员工' }]}
              request={employeeSelectRequest}
              showSearch
            />
            <ProFormSelect
              name="certificate_type_id"
              label="证书类型"
              rules={[{ required: true, message: '请选择证书类型' }]}
              request={certificateTypeSelectRequest}
              showSearch
            />
            <ProFormText name="holder_name" label="持证人" rules={[{ required: true, message: '请输入持证人' }]} />
            <ProFormText name="certificate_name" label="识别证书名" disabled />
            <ProFormText name="certificate_no" label="证书编号" />
            <ProFormText name="issuing_authority" label="发证机构" />
            <ProFormDatePicker name="issue_date" label="发证日期" />
            <ProFormDatePicker name="valid_from" label="有效开始" />
            <ProFormDatePicker name="valid_to" label="有效截止" />
            <ProFormDatePicker name="review_date" label="复审日期" />
            <ProFormText name="reviewed_by" label="复核人" rules={[{ required: true, message: '请输入复核人' }]} />
            <ProFormText name="notes" label="复核备注" />
          </ProForm>
        </ProCard>
      </div>
    </PageContainer>
  );
}
