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
import { Button, Form, Modal, Tag, message } from 'antd';
import { useEffect, useMemo, useRef, useState } from 'react';

import { createResource, listResource, updateResource } from '@/services/api';
import type { CertificateStatus, CertificateType, Employee, EmployeeCertificate } from '@/types/domain';

const statusColor: Record<string, string> = {
  ACTIVE: 'green',
  EXPIRING: 'gold',
  EXPIRED: 'red',
  PENDING_REVIEW: 'blue',
  REPLACED: 'default',
  ARCHIVED: 'default',
};

const statusOptions: Array<{ label: string; value: CertificateStatus }> = [
  { label: '有效', value: 'ACTIVE' },
  { label: '即将到期', value: 'EXPIRING' },
  { label: '已过期', value: 'EXPIRED' },
  { label: '已续证', value: 'RENEWED' },
  { label: '已替换', value: 'REPLACED' },
  { label: '已归档', value: 'ARCHIVED' },
];

interface CertificateFormValues {
  employee_id?: string;
  certificate_type_id?: string;
  certificate_no?: string;
  holder_name?: string;
  issuing_authority?: string;
  issue_date?: unknown;
  valid_from?: unknown;
  valid_to?: unknown;
  review_date?: unknown;
  status?: CertificateStatus;
  confirmed_by?: string;
}

function optionalText(value: string | undefined): string | undefined {
  const trimmed = value?.trim();
  return trimmed || undefined;
}

function formatDateValue(value: unknown): string | undefined {
  if (!value) return undefined;
  if (typeof value === 'string') return value.slice(0, 10);
  if (typeof value === 'object' && value && 'format' in value && typeof value.format === 'function') {
    return value.format('YYYY-MM-DD');
  }
  return undefined;
}

export default function CertificatesPage() {
  const actionRef = useRef<ActionType>();
  const [form] = Form.useForm<CertificateFormValues>();
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [certificateTypes, setCertificateTypes] = useState<CertificateType[]>([]);
  const [modalOpen, setModalOpen] = useState(false);
  const [currentCertificate, setCurrentCertificate] = useState<EmployeeCertificate>();
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

  const employeeNameById = useMemo(
    () => new Map(employees.map((employee) => [employee.id, `${employee.name}（${employee.employee_no}）`])),
    [employees],
  );
  const certificateTypeNameById = useMemo(
    () => new Map(certificateTypes.map((certificateType) => [certificateType.id, certificateType.name])),
    [certificateTypes],
  );

  function openCreateModal() {
    setCurrentCertificate(undefined);
    form.resetFields();
    form.setFieldsValue({ status: 'ACTIVE', confirmed_by: 'hr' });
    setModalOpen(true);
  }

  function openEditModal(record: EmployeeCertificate) {
    setCurrentCertificate(record);
    form.setFieldsValue({
      employee_id: record.employee_id,
      certificate_type_id: record.certificate_type_id,
      certificate_no: record.certificate_no,
      holder_name: record.holder_name,
      issuing_authority: record.issuing_authority,
      issue_date: record.issue_date,
      valid_from: record.valid_from,
      valid_to: record.valid_to,
      review_date: record.review_date,
      status: record.status,
      confirmed_by: record.confirmed_by || 'hr',
    });
    setModalOpen(true);
  }

  async function submitCertificate() {
    const values = await form.validateFields();
    const payload = {
      employee_id: values.employee_id!,
      certificate_type_id: values.certificate_type_id!,
      certificate_no: optionalText(values.certificate_no),
      holder_name: values.holder_name!.trim(),
      issuing_authority: optionalText(values.issuing_authority),
      issue_date: formatDateValue(values.issue_date),
      valid_from: formatDateValue(values.valid_from),
      valid_to: formatDateValue(values.valid_to),
      review_date: formatDateValue(values.review_date),
      status: values.status || 'ACTIVE',
      confirmed_by: optionalText(values.confirmed_by),
    };

    setSubmitting(true);
    try {
      if (currentCertificate) {
        await updateResource<EmployeeCertificate, typeof payload>(`/certificates/${currentCertificate.id}`, payload);
        message.success('持证记录已更新');
      } else {
        await createResource<EmployeeCertificate, typeof payload>('/certificates', payload);
        message.success('持证记录已创建');
      }
      setModalOpen(false);
      actionRef.current?.reload();
    } catch (error) {
      message.error(error instanceof Error ? error.message : '持证记录保存失败');
    } finally {
      setSubmitting(false);
    }
  }

  const columns: ProColumns<EmployeeCertificate>[] = [
    {
      title: '员工',
      dataIndex: 'employee_id',
      width: 180,
      renderText: (value) => employeeNameById.get(value) || value,
    },
    {
      title: '证书类型',
      dataIndex: 'certificate_type_id',
      width: 180,
      renderText: (value) => certificateTypeNameById.get(value) || value,
    },
    { title: '持证人', dataIndex: 'holder_name', width: 140 },
    { title: '证书编号', dataIndex: 'certificate_no', width: 180 },
    { title: '发证机构', dataIndex: 'issuing_authority' },
    { title: '发证日期', dataIndex: 'issue_date', valueType: 'date', width: 130 },
    { title: '到期日期', dataIndex: 'valid_to', valueType: 'date', width: 130 },
    {
      title: '状态',
      dataIndex: 'status',
      width: 130,
      render: (_, record) => <Tag color={statusColor[record.status] || 'default'}>{record.status}</Tag>,
    },
    {
      title: '操作',
      valueType: 'option',
      width: 100,
      render: (_, record) => (
        <Button type="link" size="small" onClick={() => openEditModal(record)}>
          编辑
        </Button>
      ),
    },
  ];

  return (
    <PageContainer title="持证记录">
      <ProTable<EmployeeCertificate>
        actionRef={actionRef}
        rowKey="id"
        columns={columns}
        request={async () => ({
          data: await listResource<EmployeeCertificate>('/certificates'),
          success: true,
        })}
        toolbar={{
          title: '当前与历史持证记录',
          actions: [
            <Button key="create" type="primary" onClick={openCreateModal}>
              新增持证记录
            </Button>,
          ],
        }}
        search={{ labelWidth: 88 }}
      />

      <Modal
        title={currentCertificate ? '编辑持证记录' : '新增持证记录'}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={() => void submitCertificate()}
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
          <ProFormText name="certificate_no" label="证书编号" />
          <ProFormText name="issuing_authority" label="发证机构" />
          <ProFormDatePicker name="issue_date" label="发证日期" />
          <ProFormDatePicker name="valid_from" label="有效开始" />
          <ProFormDatePicker name="valid_to" label="有效截止" />
          <ProFormDatePicker name="review_date" label="复审日期" />
          <ProFormSelect name="status" label="状态" rules={[{ required: true, message: '请选择状态' }]} options={statusOptions} />
          <ProFormText name="confirmed_by" label="确认人" />
        </ProForm>
      </Modal>
    </PageContainer>
  );
}
