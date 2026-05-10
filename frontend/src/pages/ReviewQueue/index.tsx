import {
  PageContainer,
  ProForm,
  ProFormDatePicker,
  ProFormSelect,
  ProFormText,
  ProFormTextArea,
  ProTable,
  type ActionType,
  type ProColumns,
} from '@ant-design/pro-components';
import { Button, Form, Modal, Space, Tag, message } from 'antd';
import { useEffect, useRef, useState } from 'react';

import {
  ExtractionQualitySummary,
  buildExtractionQuality,
  extractionSuspiciousPoints,
  outputText,
} from '@/components/ExtractionQualitySummary';
import { listResource, postResource } from '@/services/api';
import type { CertificateType, Employee, ReviewApprovePayload, ReviewDecision, ReviewTask } from '@/types/domain';
import { reviewStatusLabel, reviewStatusOptions } from '@/utils/displayLabels';

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
  const [form] = Form.useForm<ReviewFormValues>();
  const [rejectForm] = Form.useForm<{ reviewed_by?: string; notes?: string }>();
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [certificateTypes, setCertificateTypes] = useState<CertificateType[]>([]);
  const [currentReview, setCurrentReview] = useState<ReviewTask>();
  const [rejectingReview, setRejectingReview] = useState<ReviewTask>();
  const [submitting, setSubmitting] = useState(false);

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

  function openApproveModal(record: ReviewTask) {
    const output = record.ai_output_json;
    const holderName = outputText(output, 'holder_name');
    const certificateName = outputText(output, 'certificate_name');
    const matchedEmployee = employees.find((employee) => employee.name === holderName);
    const matchedCertificateType = certificateTypes.find((certificateType) => certificateType.name === certificateName);

    setCurrentReview(record);
    form.setFieldsValue({
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
    });
  }

  async function approveCurrentReview() {
    if (!currentReview) return;
    const values = await form.validateFields();
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

    setSubmitting(true);
    try {
      await postResource<ReviewDecision, ReviewApprovePayload>(`/reviews/${currentReview.id}/approve`, payload);
      message.success('复核通过，已生成正式持证记录');
      setCurrentReview(undefined);
      actionRef.current?.reload();
    } catch (error) {
      message.error(error instanceof Error ? error.message : '复核提交失败');
    } finally {
      setSubmitting(false);
    }
  }

  function openRejectModal(record: ReviewTask) {
    setRejectingReview(record);
    rejectForm.resetFields();
    rejectForm.setFieldsValue({ notes: '识别结果不符合证书入库要求' });
  }

  async function submitRejectReview() {
    if (!rejectingReview) return;
    const values = await rejectForm.validateFields();
    setSubmitting(true);
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
    } catch (error) {
      message.error(error instanceof Error ? error.message : '复核驳回失败');
    } finally {
      setSubmitting(false);
    }
  }

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
      fieldProps: {
        options: reviewStatusOptions,
      },
      render: (_, record) => <Tag color={record.status === 'PENDING' ? 'blue' : 'gold'}>{reviewStatusLabel(record.status)}</Tag>,
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
            onClick={() => openApproveModal(record)}
          >
            复核
          </Button>
          <Button size="small" type="link" danger onClick={() => openRejectModal(record)}>
            驳回
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <PageContainer title="待复核队列">
      <ProTable<ReviewTask>
        actionRef={actionRef}
        rowKey="id"
        columns={columns}
        search={false}
        request={async () => ({
          data: await listResource<ReviewTask>('/reviews'),
          success: true,
        })}
        locale={{ emptyText: '暂无待复核任务，请先上传证书并完成智能识别' }}
        toolbar={{ title: '智能识别后等待人力复核的证书' }}
      />

      <Modal
        title="复核识别结果"
        open={Boolean(currentReview)}
        onCancel={() => setCurrentReview(undefined)}
        onOk={() => void approveCurrentReview()}
        confirmLoading={submitting}
        destroyOnClose
        width={760}
      >
        <div style={{ marginBottom: 16 }}>
          <ExtractionQualitySummary output={currentReview?.ai_output_json} />
        </div>
        <ProForm form={form} submitter={false} layout="horizontal" labelCol={{ span: 5 }}>
          <ProFormSelect
            name="employee_id"
            label="员工"
            rules={[{ required: true, message: '请选择员工' }]}
            options={employees.map((employee) => ({
              label: `${employee.name}（${employee.employee_no}）`,
              value: employee.id,
            }))}
            showSearch
          />
          <ProFormSelect
            name="certificate_type_id"
            label="证书类型"
            rules={[{ required: true, message: '请选择证书类型' }]}
            options={certificateTypes.map((certificateType) => ({
              label: certificateType.name,
              value: certificateType.id,
            }))}
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
      </Modal>

      <Modal
        title="驳回复核任务"
        open={Boolean(rejectingReview)}
        onCancel={() => setRejectingReview(undefined)}
        onOk={() => void submitRejectReview()}
        confirmLoading={submitting}
        okText="驳回"
        okButtonProps={{ danger: true }}
        destroyOnClose
      >
        <ProForm form={rejectForm} submitter={false} layout="horizontal" labelCol={{ span: 5 }}>
          <ProFormText name="reviewed_by" label="复核人" rules={[{ required: true, message: '请输入复核人' }]} />
          <ProFormTextArea name="notes" label="驳回原因" />
        </ProForm>
      </Modal>
    </PageContainer>
  );
}
