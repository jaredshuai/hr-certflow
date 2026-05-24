import {
  ModalForm,
  PageContainer,
  ProFormSelect,
  ProFormText,
  ProTable,
  type ActionType,
  type ProColumns,
} from '@ant-design/pro-components';
import { UploadOutlined } from '@ant-design/icons';
import { Alert, Button, Modal, Table, Upload } from 'antd';
import type { UploadProps } from 'antd';
import { useMemo, useRef, useState } from 'react';

import { useLocation } from '@umijs/max';

import { createResource, pageResource, updateResource, uploadResource } from '@/services/api';
import type { Employee, EmploymentStatus } from '@/types/domain';
import { emptyTableText } from '@/utils/emptyStates';
import { employmentStatusOptions, employmentStatusValueEnum } from '@/utils/displayLabels';
import { message } from '@/utils/messageApi';
import { downloadCsv } from '@/utils/download';

interface EmployeeFormValues {
  employee_no?: string;
  name?: string;
  department?: string;
  position?: string;
  employment_status?: EmploymentStatus;
  phone?: string;
  email?: string;
}

interface EmployeeImportError {
  row_number: number;
  employee_no?: string;
  message: string;
}

interface EmployeeImportResult {
  total: number;
  created: number;
  updated: number;
  failed: number;
  errors: EmployeeImportError[];
}

function optionalText(value: string | undefined): string | undefined {
  const trimmed = value?.trim();
  return trimmed || undefined;
}

export default function EmployeesPage() {
  const actionRef = useRef<ActionType>();
  const lastSearchParamsRef = useRef<Record<string, unknown>>({});
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const [currentEmployee, setCurrentEmployee] = useState<Employee>();
  const [loadError, setLoadError] = useState<string>();
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState<EmployeeImportResult>();

  const urlFilters = useMemo(() => {
    const params = new URLSearchParams(location.search);
    const department = params.get('department');
    const employmentStatus = params.get('employment_status');
    return {
      ...(department ? { department } : {}),
      ...(employmentStatus && employmentStatus in employmentStatusValueEnum
        ? { employment_status: employmentStatus as EmploymentStatus }
        : {}),
    };
  }, [location.search]);

  function openCreate() {
    setCurrentEmployee(undefined);
    setOpen(true);
  }

  function openEdit(record: Employee) {
    setCurrentEmployee(record);
    setOpen(true);
  }

  async function handleFinish(values: EmployeeFormValues): Promise<boolean> {
    const payload = {
      employee_no: values.employee_no?.trim(),
      name: values.name?.trim(),
      department: optionalText(values.department),
      position: optionalText(values.position),
      employment_status: values.employment_status || 'ACTIVE',
      phone: optionalText(values.phone),
      email: optionalText(values.email),
    };

    try {
      if (currentEmployee) {
        await updateResource<Employee, Omit<typeof payload, 'employee_no'>>(`/employees/${currentEmployee.id}`, {
          name: payload.name,
          department: payload.department,
          position: payload.position,
          employment_status: payload.employment_status,
          phone: payload.phone,
          email: payload.email,
        });
        message.success('人员信息已更新');
      } else {
        await createResource<Employee, typeof payload>('/employees', payload);
        message.success('人员已创建');
      }
      actionRef.current?.reload();
      return true;
    } catch (error) {
      message.error(error instanceof Error ? error.message : '人员保存失败');
      return false;
    }
  }

  async function exportEmployees() {
    try {
      await downloadCsv('/employees/export.csv', lastSearchParamsRef.current, 'employees.csv');
      message.success('人员数据已开始导出');
    } catch (error) {
      message.error(error instanceof Error ? error.message : '人员数据导出失败');
    }
  }

  async function importEmployees(file: File) {
    const formData = new FormData();
    formData.append('file', file);
    setImporting(true);
    try {
      const result = await uploadResource<EmployeeImportResult>('/employees/import.csv', formData);
      setImportResult(result);
      actionRef.current?.reload();
      message.success(`人员导入完成：新增 ${result.created} 人，更新 ${result.updated} 人`);
    } catch (error) {
      message.error(error instanceof Error ? error.message : '人员导入失败');
    } finally {
      setImporting(false);
    }
  }

  const importUploadProps: UploadProps = {
    accept: '.csv,text/csv',
    showUploadList: false,
    beforeUpload: (file) => {
      void importEmployees(file);
      return false;
    },
  };

  const columns: ProColumns<Employee>[] = [
    { title: '工号', dataIndex: 'employee_no', width: 120 },
    { title: '姓名', dataIndex: 'name', width: 140 },
    { title: '部门', dataIndex: 'department' },
    { title: '岗位', dataIndex: 'position' },
    {
      title: '在职状态',
      dataIndex: 'employment_status',
      width: 120,
      valueType: 'select',
      valueEnum: employmentStatusValueEnum,
    },
    { title: '手机', dataIndex: 'phone', search: false },
    { title: '邮箱', dataIndex: 'email', search: false },
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
    <PageContainer title="人员管理">
      {loadError ? (
        <Alert
          type="error"
          showIcon
          title="人员数据加载失败"
          description={loadError}
          style={{ marginBottom: 16 }}
          closable={{ onClose: () => setLoadError(undefined) }}
        />
      ) : null}
      <ProTable<Employee>
        actionRef={actionRef}
        rowKey="id"
        columns={columns}
        params={urlFilters}
        request={async (params) => {
          try {
            const { current, pageSize, ...searchParams } = params;
            lastSearchParamsRef.current = searchParams;
            const result = await pageResource<Employee>('/employees/page', {
              ...searchParams,
              current,
              page_size: pageSize,
            });
            setLoadError(undefined);
            return { data: result.data, total: result.total, success: true };
          } catch (error) {
            const description = error instanceof Error ? error.message : '人员数据加载失败';
            setLoadError(description);
            message.error(description);
            return { data: [], success: false };
          }
        }}
        locale={{ emptyText: emptyTableText('暂无人员，请先新增员工档案') }}
        toolbar={{
          title: '人员列表',
          actions: [
            <Upload key="import" {...importUploadProps}>
              <Button icon={<UploadOutlined />} loading={importing}>
                导入CSV
              </Button>
            </Upload>,
            <Button key="export" onClick={exportEmployees}>
              导出当前筛选
            </Button>,
            <Button key="create" type="primary" onClick={openCreate}>
              新增人员
            </Button>,
          ],
        }}
        pagination={{ defaultPageSize: 20, showSizeChanger: true }}
        search={{ labelWidth: 88 }}
      />

      <ModalForm<EmployeeFormValues>
        key={currentEmployee?.id ?? 'create'}
        title={currentEmployee ? '编辑人员' : '新增人员'}
        open={open}
        onOpenChange={setOpen}
        modalProps={{ destroyOnHidden: true, mask: { closable: false } }}
        layout="horizontal"
        labelCol={{ span: 5 }}
        width={520}
        initialValues={
          currentEmployee
            ? {
                employee_no: currentEmployee.employee_no,
                name: currentEmployee.name,
                department: currentEmployee.department,
                position: currentEmployee.position,
                employment_status: currentEmployee.employment_status,
                phone: currentEmployee.phone,
                email: currentEmployee.email,
              }
            : { employment_status: 'ACTIVE' as EmploymentStatus }
        }
        onFinish={handleFinish}
      >
        <ProFormText
          name="employee_no"
          label="工号"
          disabled={Boolean(currentEmployee)}
          rules={[{ required: true, message: '请输入工号' }]}
        />
        <ProFormText name="name" label="姓名" rules={[{ required: true, message: '请输入姓名' }]} />
        <ProFormText name="department" label="部门" />
        <ProFormText name="position" label="岗位" />
        <ProFormSelect
          name="employment_status"
          label="在职状态"
          rules={[{ required: true, message: '请选择在职状态' }]}
          options={employmentStatusOptions}
        />
        <ProFormText name="phone" label="手机" />
        <ProFormText name="email" label="邮箱" />
      </ModalForm>

      <Modal
        title="人员导入结果"
        open={Boolean(importResult)}
        onCancel={() => setImportResult(undefined)}
        footer={
          <Button type="primary" onClick={() => setImportResult(undefined)}>
            知道了
          </Button>
        }
      >
        {importResult ? (
          <>
            <Alert
              type={importResult.failed > 0 ? 'warning' : 'success'}
              showIcon
              message={`共处理 ${importResult.total} 行，新增 ${importResult.created} 人，更新 ${importResult.updated} 人，失败 ${importResult.failed} 行`}
              style={{ marginBottom: 16 }}
            />
            {importResult.errors.length > 0 ? (
              <Table<EmployeeImportError>
                size="small"
                rowKey={(record) => `${record.row_number}-${record.employee_no ?? 'empty'}`}
                pagination={false}
                dataSource={importResult.errors}
                columns={[
                  { title: '行号', dataIndex: 'row_number', width: 80 },
                  { title: '工号', dataIndex: 'employee_no', width: 120 },
                  { title: '原因', dataIndex: 'message' },
                ]}
              />
            ) : null}
          </>
        ) : null}
      </Modal>
    </PageContainer>
  );
}
