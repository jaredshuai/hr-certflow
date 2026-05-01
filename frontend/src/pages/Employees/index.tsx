import { PageContainer, ProTable, type ProColumns } from '@ant-design/pro-components';
import { Tag } from 'antd';

import { listResource } from '@/services/api';
import type { Employee } from '@/types/domain';

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
];

export default function EmployeesPage() {
  return (
    <PageContainer title="人员管理">
      <ProTable<Employee>
        rowKey="id"
        columns={columns}
        request={async () => ({
          data: await listResource<Employee>('/employees'),
          success: true,
        })}
        toolbar={{
          title: '人员列表',
        }}
        search={{ labelWidth: 88 }}
      />
    </PageContainer>
  );
}
