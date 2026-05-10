import {
  DrawerForm,
  PageContainer,
  ProFormDatePicker,
  ProFormSelect,
  ProFormText,
  ProTable,
  type ActionType,
  type ProColumns,
} from '@ant-design/pro-components';
import { Alert, Button } from 'antd';
import { useEffect, useMemo, useState, useRef } from 'react';

import { createResource, listResource, updateResource } from '@/services/api';
import type { CertificateStatus, CertificateType, Employee, EmployeeCertificate } from '@/types/domain';
import { certificateStatusOptions, certificateStatusValueEnum } from '@/utils/displayLabels';
import { emptyTableText } from '@/utils/emptyStates';
import { certificateTypeSelectRequest, employeeSelectRequest } from '@/utils/formOptions';
import { message } from '@/utils/messageApi';

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
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [certificateTypes, setCertificateTypes] = useState<CertificateType[]>([]);
  const [open, setOpen] = useState(false);
  const [currentCertificate, setCurrentCertificate] = useState<EmployeeCertificate>();
  const [loadError, setLoadError] = useState<string>();

  // Keep useEffect to provide id->name mapping for table columns; form selects use ProFormSelect.request.
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

  function openCreate() {
    setCurrentCertificate(undefined);
    setOpen(true);
  }

  function openEdit(record: EmployeeCertificate) {
    setCurrentCertificate(record);
    setOpen(true);
  }

  async function handleFinish(values: CertificateFormValues): Promise<boolean> {
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

    try {
      if (currentCertificate) {
        await updateResource<EmployeeCertificate, typeof payload>(`/certificates/${currentCertificate.id}`, payload);
        message.success('持证记录已更新');
      } else {
        await createResource<EmployeeCertificate, typeof payload>('/certificates', payload);
        message.success('持证记录已创建');
      }
      actionRef.current?.reload();
      return true;
    } catch (error) {
      message.error(error instanceof Error ? error.message : '持证记录保存失败');
      return false;
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
      valueType: 'select',
      valueEnum: certificateStatusValueEnum,
    },
    {
      title: '操作',
      valueType: 'option',
      width: 100,
      render: (_, record) => (
        <Button type="link" size="small" onClick={() => openEdit(record)}>
          编辑
        </Button>
      ),
    },
  ];

  return (
    <PageContainer title="持证记录">
      {loadError ? (
        <Alert
          type="error"
          showIcon
          title="持证记录加载失败"
          description={loadError}
          style={{ marginBottom: 16 }}
          closable={{ onClose: () => setLoadError(undefined) }}
        />
      ) : null}
      <ProTable<EmployeeCertificate>
        actionRef={actionRef}
        rowKey="id"
        columns={columns}
        request={async () => {
          try {
            const data = await listResource<EmployeeCertificate>('/certificates');
            setLoadError(undefined);
            return { data, success: true };
          } catch (error) {
            const description = error instanceof Error ? error.message : '持证记录加载失败';
            setLoadError(description);
            message.error(description);
            return { data: [], success: false };
          }
        }}
        locale={{ emptyText: emptyTableText('暂无持证记录，请先上传识别或手动新增') }}
        toolbar={{
          title: '当前与历史持证记录',
          actions: [
            <Button key="create" type="primary" onClick={openCreate}>
              新增持证记录
            </Button>,
          ],
        }}
        search={{ labelWidth: 88 }}
      />

      <DrawerForm<CertificateFormValues>
        key={currentCertificate?.id ?? 'create'}
        title={currentCertificate ? '编辑持证记录' : '新增持证记录'}
        open={open}
        onOpenChange={setOpen}
        drawerProps={{ destroyOnHidden: true, mask: { closable: false } }}
        layout="horizontal"
        labelCol={{ span: 5 }}
        width={640}
        initialValues={
          currentCertificate
            ? {
                employee_id: currentCertificate.employee_id,
                certificate_type_id: currentCertificate.certificate_type_id,
                certificate_no: currentCertificate.certificate_no,
                holder_name: currentCertificate.holder_name,
                issuing_authority: currentCertificate.issuing_authority,
                issue_date: currentCertificate.issue_date,
                valid_from: currentCertificate.valid_from,
                valid_to: currentCertificate.valid_to,
                review_date: currentCertificate.review_date,
                status: currentCertificate.status,
                confirmed_by: currentCertificate.confirmed_by,
              }
            : { status: 'ACTIVE' as CertificateStatus }
        }
        onFinish={handleFinish}
      >
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
        <ProFormText name="certificate_no" label="证书编号" />
        <ProFormText name="issuing_authority" label="发证机构" />
        <ProFormDatePicker name="issue_date" label="发证日期" />
        <ProFormDatePicker name="valid_from" label="有效开始" />
        <ProFormDatePicker name="valid_to" label="有效截止" />
        <ProFormDatePicker name="review_date" label="复审日期" />
        <ProFormSelect
          name="status"
          label="状态"
          rules={[{ required: true, message: '请选择状态' }]}
          options={certificateStatusOptions}
        />
        <ProFormText name="confirmed_by" label="确认人" />
      </DrawerForm>
    </PageContainer>
  );
}
