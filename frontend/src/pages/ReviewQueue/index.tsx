import {
  DrawerForm,
  ModalForm,
  PageContainer,
  ProFormDatePicker,
  ProFormSelect,
  ProFormText,
  ProFormTextArea,
  ProTable,
  type ActionType,
  type ProColumns,
} from '@ant-design/pro-components';
import { Alert, Button, Space } from 'antd';
import { useEffect, useRef, useState } from 'react';

import {
  ExtractionQualitySummary,
  buildExtractionQuality,
  extractionSuspiciousPoints,
  outputText,
} from '@/components/ExtractionQualitySummary';
import { listResource, postResource } from '@/services/api';
import type { CertificateType, Employee, ReviewApprovePayload, ReviewDecision, ReviewTask } from '@/types/domain';
import { reviewStatusValueEnum } from '@/utils/displayLabels';
import { emptyTableText } from '@/utils/emptyStates';
import { message } from '@/utils/messageApi';

interface ReviewFormValues {
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

interface RejectFormValues {
  reviewed_by?: string;
  notes?: string;
}

function formatDateValue(value: unknown): string | undefined {
  if (!value) return undefined;
  if (typeof value === 'string') return value.slice(0, 10);
  if (typeof value === 'object' && value && 'format' in value && typeof value.format === 'function') {
    return value.format('YYYY-MM-DD');
  }
  return undefined;
}

export default function ReviewQueuePage() {
  const actionRef = useRef<ActionType>();
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [certificateTypes, setCertificateTypes] = useState<CertificateType[]>([]);
  const [currentReview, setCurrentReview] = useState<ReviewTask>();
  const [rejectingReview, setRejectingReview] = useState<ReviewTask>();
  const [loadError, setLoadError] = useState<string>();

  // Need full lists to match AI output to employee/cert type for prefill.
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

  function buildApproveInitial(record: ReviewTask): ReviewFormValues {
    const output = record.ai_output_json;
    const holderName = outputText(output, 'holder_name');
    const certificateName = outputText(output, 'certificate_name');
    const matchedEmployee = employees.find((employee) => employee.name === holderName);
    const matchedCertificateType = certificateTypes.find((certificateType) => certificateType.name === certificateName);

    return {
      employee_id: matchedEmployee?.id,
      certificate_type_id: matchedCertificateType?.id,
      holder_name: holderName,
      certificate_name: certificateName,
      certificate_no: outputText(output, 'certificate_no'),
      issuing_authority: outputText(output, 'issuing_authority'),
      issue_date: outputText(output, 'issue_date'),
      valid_from: outputText(output, 'valid_from'),
      valid_to: outputText(output, 'valid_to'),
      review_date: outputText(output, 'review_date'),
      reviewed_by: undefined,
      notes: record.notes,
    };
  }

  async function handleApprove(values: ReviewFormValues): Promise<boolean> {
    if (!currentReview) return false;
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
    };

    try {
      await postResource<ReviewDecision, ReviewApprovePayload>(`/reviews/${currentReview.id}/approve`, payload);
      message.success('复核通过，已生成正式持证记录');
      setCurrentReview(undefined);
      actionRef.current?.reload();
      return true;
    } catch (error) {
      message.error(error instanceof Error ? error.message : '复核提交失败');
      return false;
    }
  }

  async function handleReject(values: RejectFormValues): Promise<boolean> {
    if (!rejectingReview) return false;
    try {
      await postResource<ReviewTask, { status: 'REJECTED'; reviewed_by: string; notes?: string }>(
        `/reviews/${rejectingReview.id}/reject`,
        {
          status: 'REJECTED',
          reviewed_by: values.reviewed_by!.trim(),
          notes: values.notes,
        },
      );
      message.success('复核任务已驳回');
      setRejectingReview(undefined);
      actionRef.current?.reload();
      return true;
    } catch (error) {
      message.error(error instanceof Error ? error.message : '复核驳回失败');
      return false;
    }
  }

  const employeeOptions = employees.map((employee) => ({
    label: `${employee.name}（${employee.employee_no}）`,
    value: employee.id,
  }));
  const certificateTypeOptions = certificateTypes.map((certificateType) => ({
    label: certificateType.name,
    value: certificateType.id,
  }));

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
      width: 160,
      render: (_, record) => (
        <Space>
          <Button
            size="small"
            type="link"
            danger={!buildExtractionQuality(record.ai_output_json).complete}
            onClick={() => setCurrentReview(record)}
          >
            复核
          </Button>
          <Button size="small" type="link" danger onClick={() => setRejectingReview(record)}>
            驳回
          </Button>
        </Space>
      ),
    },
  ];

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

      <DrawerForm<ReviewFormValues>
        key={currentReview?.id ?? 'approve-empty'}
        title="复核识别结果"
        open={Boolean(currentReview)}
        onOpenChange={(value) => {
          if (!value) setCurrentReview(undefined);
        }}
        drawerProps={{ destroyOnHidden: true, mask: { closable: false } }}
        layout="horizontal"
        labelCol={{ span: 5 }}
        width={680}
        initialValues={currentReview ? buildApproveInitial(currentReview) : undefined}
        onFinish={handleApprove}
      >
        {currentReview ? (
          <div style={{ marginBottom: 16 }}>
            <ExtractionQualitySummary output={currentReview.ai_output_json} />
          </div>
        ) : null}
        <ProFormSelect
          name="employee_id"
          label="员工"
          rules={[{ required: true, message: '请选择员工' }]}
          options={employeeOptions}
          showSearch
        />
        <ProFormSelect
          name="certificate_type_id"
          label="证书类型"
          rules={[{ required: true, message: '请选择证书类型' }]}
          options={certificateTypeOptions}
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
      </DrawerForm>

      <ModalForm<RejectFormValues>
        key={rejectingReview?.id ?? 'reject-empty'}
        title="驳回复核任务"
        open={Boolean(rejectingReview)}
        onOpenChange={(value) => {
          if (!value) setRejectingReview(undefined);
        }}
        modalProps={{
          destroyOnHidden: true,
          mask: { closable: false },
          okText: '驳回',
        }}
        submitter={{ submitButtonProps: { danger: true } }}
        layout="horizontal"
        labelCol={{ span: 5 }}
        width={520}
        initialValues={{ notes: '识别结果不符合证书入库要求' }}
        onFinish={handleReject}
      >
        <ProFormText name="reviewed_by" label="复核人" rules={[{ required: true, message: '请输入复核人' }]} />
        <ProFormTextArea name="notes" label="驳回原因" />
      </ModalForm>
    </PageContainer>
  );
}
