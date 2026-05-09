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
export type FeedbackStatus =
  | 'NOTIFIED_EMPLOYEE'
  | 'PROCESSING'
  | 'RENEWED'
  | 'NO_ACTION_REQUIRED'
  | 'EMPLOYEE_LEFT'
  | 'IGNORED';

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
  description?: string;
}

export interface EmployeeCertificate {
  id: string;
  employee_id: string;
  certificate_type_id: string;
  source_document_id?: string;
  replaced_by_id?: string;
  certificate_no?: string;
  holder_name: string;
  issuing_authority?: string;
  issue_date?: string;
  valid_from?: string;
  valid_to?: string;
  review_date?: string;
  status: CertificateStatus;
  confirmed_by?: string;
  confirmed_at?: string;
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
  document_original_filename?: string;
  ai_output_json?: Record<string, unknown>;
  ai_confidence?: number;
}

export interface UploadIntent {
  document_id: string;
  storage_bucket: string;
  storage_key: string;
  upload_url: string;
  read_url?: string;
}

export interface AiExtractionResult {
  id: string;
  document_id: string;
  workflow_run_id?: string;
  model_name?: string;
  output_json: Record<string, unknown>;
  raw_text?: string;
  suspicious_points: string[];
  confidence?: number;
  created_at: string;
  updated_at: string;
}

export interface ReviewApprovePayload {
  employee_id: string;
  certificate_type_id: string;
  certificate_no?: string;
  holder_name: string;
  issuing_authority?: string;
  issue_date?: string;
  valid_from?: string;
  valid_to?: string;
  review_date?: string;
  reviewed_by: string;
  notes?: string;
}

export interface ReviewDecision {
  review_task: ReviewTask;
  certificate?: EmployeeCertificate;
}
