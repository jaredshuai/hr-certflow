import { listResource } from '@/services/api';
import type { CertificateType, Employee } from '@/types/domain';

export async function employeeSelectRequest(): Promise<Array<{ label: string; value: string }>> {
  const list = await listResource<Employee>('/employees');
  return list.map((employee) => ({
    label: `${employee.name}（${employee.employee_no}）`,
    value: employee.id,
  }));
}

export async function certificateTypeSelectRequest(): Promise<Array<{ label: string; value: string }>> {
  const list = await listResource<CertificateType>('/certificate-types');
  return list.map((certificateType) => ({
    label: certificateType.name,
    value: certificateType.id,
  }));
}
