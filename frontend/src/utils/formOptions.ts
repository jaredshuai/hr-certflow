import { listResource } from '@/services/api';
import type { CertificateType, Employee } from '@/types/domain';
import { employmentStatusLabel } from '@/utils/displayLabels';

type SelectOption = { label: string; value: string; disabled?: boolean };

export function employeeOptionLabel(employee: Employee): string {
  const details = [
    employee.employee_no,
    employee.department,
    employee.position,
    employmentStatusLabel(employee.employment_status),
  ].filter(Boolean);
  return `${employee.name}（${details.join(' / ')}）`;
}

export function employeeSelectOption(employee: Employee): SelectOption {
  return {
    label: employeeOptionLabel(employee),
    value: employee.id,
    disabled: employee.employment_status === 'LEFT',
  };
}

export async function employeeSelectRequest(): Promise<SelectOption[]> {
  const list = await listResource<Employee>('/employees');
  return list.map(employeeSelectOption);
}

export async function certificateTypeSelectRequest(): Promise<Array<{ label: string; value: string }>> {
  const list = await listResource<CertificateType>('/certificate-types');
  return list.map((certificateType) => ({
    label: certificateType.name,
    value: certificateType.id,
  }));
}
