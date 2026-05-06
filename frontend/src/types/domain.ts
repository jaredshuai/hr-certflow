export type EmploymentStatus = 'ACTIVE' | 'ON_LEAVE' | 'LEFT';
export type CertificateStatus =
  | 'DRAFT'
  | 'PENDING_REVIEW'
  | 'ACTIVE'
  | 'EXPIRING'
  | 'EXPIRED'
  | 'RENEWED'
  | 'REPLACED'
  | 'ARCHIVED';
export type ReminderTaskStatus =
  | 'PENDING'
  | 'FIRST_SENT'
  | 'WAITING_FEEDBACK'
  | 'SECOND_SENT'
  | 'ESCALATED'
  | 'RESOLVED'
  | 'CLOSED';
export type ReviewStatus = 'PENDING' | 'APPROVED' | 'REJECTED' | 'NEEDS_INFO';

export interface Employee {
  id: string;
  employee_no: string;
  name: string;
  department?: string;
  position?: string;
  employment_status: EmploymentStatus;
  phone?: string;
  email?: string;
}

export interface CertificateType {
  id: string;
  code: string;
  name: string;
  issuing_authority?: string;
  default_validity_months?: number;
  force_manual_review: boolean;
}

export interface EmployeeCertificate {
  id: string;
  employee_id: string;
  certificate_type_id: string;
  certificate_no?: string;
  holder_name: string;
  issuing_authority?: string;
  issue_date?: string;
  valid_from?: string;
  valid_to?: string;
  status: CertificateStatus;
}

export interface ReminderTask {
  id: string;
  employee_certificate_id: string;
  status: ReminderTaskStatus;
  trigger_date: string;
  due_date?: string;
  closed_reason?: string;
}

export interface ReviewTask {
  id: string;
  document_id: string;
  ai_result_id?: string;
  status: ReviewStatus;
  assigned_to?: string;
  reviewed_by?: string;
  reviewed_at?: string;
  decision_payload?: Record<string, unknown>;
  notes?: string;
  created_at: string;
  updated_at: string;
}
