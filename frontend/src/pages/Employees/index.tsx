import {
  PageContainer,
  ProForm,
  ProFormSelect,
  ProFormText,
  ProTable,
  type ActionType,
  type ProColumns,
} from '@ant-design/pro-components';
import { Button, Form, Modal, Tag, message } from 'antd';
import { useRef, useState } from 'react';

import { createResource, listResource, updateResource } from '@/services/api';
import type { Employee, EmploymentStatus } from '@/types/domain';

interface EmployeeFormValues {
  employee_no?: string;
  name?: string;
  department?: string;
  position?: string;
  employment_status?: EmploymentStatus;
  phone?: string;
  email?: string;
}

function optionalText(value: string | undefined): string | undefined {
  const trimmed = value?.trim();
  return trimmed || undefined;
}

export default function EmployeesPage() {
  const actionRef = useRef<ActionType>();
  const [form] = Form.useForm<EmployeeFormValues>();
  const [modalOpen, setModalOpen] = useState(false);
  const [currentEmployee, setCurrentEmployee] = useState<Employee>();
  const [submitting, setSubmitting] = useState(false);

  function openCreateModal() {
    setCurrentEmployee(undefined);
    form.resetFields();
    form.setFieldsValue({ employment_status: 'ACTIVE' });
    setModalOpen(true);
  }

  function openEditModal(record: Employee) {
    setCurrentEmployee(record);
    form.setFieldsValue(record);
    setModalOpen(true);
  }

  async function submitEmployee() {
    const values = await form.validateFields();
    const payload = {
      employee_no: values.employee_no?.trim(),
      name: values.name?.trim(),
      department: optionalText(values.department),
      position: optionalText(values.position),
      employment_status: values.employment_status || 'ACTIVE',
      phone: optionalText(values.phone),
      email: optionalText(values.email),
    };

    setSubmitting(true);
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
      setModalOpen(false);
      actionRef.current?.reload();
    } catch (error) {
      message.error(error instanceof Error ? error.message : '人员保存失败');
    } finally {
      setSubmitting(false);
    }
  }

  const columns: ProColumns<Employee>[] = [
    { title: '工号', dataIndex: 'employee_no', width: 120 },
    { title: '姓名', dataIndex: 'name', width: 140 },
    { title: '部门', dataIndex: 'department' },
    { title: '岗位', dataIndex: 'position' },
    {
      title: '在职状态',
      dataIndex: 'employment_status',
      width: 120,
      render: (_, record) => {
        const color = record.employment_status === 'ACTIVE' ? 'green' : record.employment_status === 'LEFT' ? 'default' : 'gold';
        return <Tag color={color}>{record.employment_status}</Tag>;
      },
    },
    { title: '手机', dataIndex: 'phone', search: false },
    { title: '邮箱', dataIndex: 'email', search: false },
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
    <PageContainer title="人员管理">
      <ProTable<Employee>
        actionRef={actionRef}
        rowKey="id"
        columns={columns}
        request={async () => ({
          data: await listResource<Employee>('/employees'),
          success: true,
        })}
        toolbar={{
          title: '人员列表',
          actions: [
            <Button key="create" type="primary" onClick={openCreateModal}>
              新增人员
            </Button>,
          ],
        }}
        search={{ labelWidth: 88 }}
      />

      <Modal
        title={currentEmployee ? '编辑人员' : '新增人员'}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={() => void submitEmployee()}
        confirmLoading={submitting}
        destroyOnClose
      >
        <ProForm form={form} submitter={false} layout="horizontal" labelCol={{ span: 5 }}>
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
            options={[
              { label: '在职', value: 'ACTIVE' },
              { label: '休假', value: 'ON_LEAVE' },
              { label: '离职', value: 'LEFT' },
            ]}
          />
          <ProFormText name="phone" label="手机" />
          <ProFormText name="email" label="邮箱" />
        </ProForm>
      </Modal>
    </PageContainer>
  );
}
