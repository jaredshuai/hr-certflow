import {
  PageContainer,
  ProForm,
  ProFormDatePicker,
  ProFormSelect,
  ProFormText,
  ProTable,
  type ActionType,
  type ProColumns,
} from '@ant-design/pro-components';
import { Button, Form, Modal, Space, Tag, message } from 'antd';
import { useEffect, useRef, useState } from 'react';

import { listResource, postResource } from '@/services/api';
import type { CertificateType, Employee, ReviewApprovePayload, ReviewDecision, ReviewTask } from '@/types/domain';

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
  notes?: string;
}

function textValue(output: Record<string, unknown> | undefined, key: string): string | undefined {
  const value = output?.[key];
  return typeof value === 'string' && value.trim() ? value : undefined;
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
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [certificateTypes, setCertificateTypes] = useState<CertificateType[]>([]);
  const [currentReview, setCurrentReview] = useState<ReviewTask>();
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
    const holderName = textValue(output, 'holder_name');
    const certificateName = textValue(output, 'certificate_name');
    const matchedEmployee = employees.find((employee) => employee.name === holderName);
    const matchedCertificateType = certificateTypes.find((certificateType) => certificateType.name === certificateName);

    setCurrentReview(record);
    form.setFieldsValue({
      employee_id: matchedEmployee?.id,
      certificate_type_id: matchedCertificateType?.id,
      holder_name: holderName,
      certificate_name: certificateName,
      certificate_no: textValue(output, 'certificate_no'),
      issuing_authority: textValue(output, 'issuing_authority'),
      issue_date: textValue(output, 'issue_date'),
      valid_from: textValue(output, 'valid_from'),
      valid_to: textValue(output, 'valid_to'),
      review_date: textValue(output, 'review_date'),
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
      reviewed_by: 'hr',
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

  function rejectReview(record: ReviewTask) {
    Modal.confirm({
      title: '驳回复核任务',
      content: `确认驳回 ${record.document_original_filename || record.document_id} 的识别结果？`,
      okText: '驳回',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        await postResource<ReviewTask, { status: 'REJECTED'; reviewed_by: string; notes: string }>(
          `/reviews/${record.id}/reject`,
          {
            status: 'REJECTED',
            reviewed_by: 'hr',
            notes: 'HR 驳回识别结果',
          },
        );
        message.success('复核任务已驳回');
        actionRef.current?.reload();
      },
    });
  }

  const columns: ProColumns<ReviewTask>[] = [
    { title: '文件', dataIndex: 'document_original_filename', ellipsis: true, renderText: (value) => value || '-' },
    { title: '文档 ID', dataIndex: 'document_id', ellipsis: true },
    { title: '复核备注', dataIndex: 'notes', ellipsis: true, renderText: (value) => value || '-' },
    {
      title: '状态',
      dataIndex: 'status',
      width: 130,
      render: (_, record) => <Tag color={record.status === 'PENDING' ? 'blue' : 'gold'}>{record.status}</Tag>,
    },
    { title: '创建时间', dataIndex: 'created_at', valueType: 'dateTime', width: 180 },
    {
      title: '操作',
      valueType: 'option',
      width: 160,
      render: (_, record) => (
        <Space>
          <Button size="small" type="link" onClick={() => openApproveModal(record)}>
            复核
          </Button>
          <Button size="small" type="link" danger onClick={() => rejectReview(record)}>
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
        toolbar={{ title: 'AI 识别后等待 HR 确认的证书' }}
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
          <ProFormText name="notes" label="复核备注" />
        </ProForm>
      </Modal>
    </PageContainer>
  );
}
