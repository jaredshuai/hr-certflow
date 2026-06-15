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
export type ReminderEventType =
  | 'FIRST_REMINDER'
  | 'SECOND_REMINDER'
  | 'ESCALATION'
  | 'FEEDBACK'
  | 'CLOSED'
  | 'FAILED';
export type DocumentStatus =
  | 'PENDING_UPLOAD'
  | 'UPLOADED'
  | 'PARSING'
  | 'PENDING_REVIEW'
  | 'CONFIRMED'
  | 'FAILED'
  | 'ARCHIVED';
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

export interface EmployeeTraceCertificate {
  id: string;
  certificate_type_id: string;
  certificate_type_name?: string;
  source_document_id?: string;
  replaced_by_id?: string;
  certificate_no?: string;
  holder_name: string;
  issuing_authority?: string;
  valid_to?: string;
  status: CertificateStatus;
  confirmed_by?: string;
  confirmed_at?: string;
  created_at: string;
  updated_at: string;
}

export interface EmployeeTraceDocument {
  id: string;
  status: DocumentStatus;
  original_filename: string;
  content_type?: string;
  file_size?: number;
  sha256?: string;
  failure_reason?: string;
  created_at: string;
  updated_at: string;
}

export interface EmployeeTraceReviewTask {
  id: string;
  document_id: string;
  ai_result_id?: string;
  status: ReviewStatus;
  reviewed_by?: string;
  reviewed_at?: string;
  notes?: string;
  created_at: string;
  updated_at: string;
}

export interface EmployeeTraceReminderTask {
  id: string;
  employee_certificate_id: string;
  status: ReminderTaskStatus;
  trigger_date: string;
  due_date?: string;
  last_event_at?: string;
  resolved_at?: string;
  closed_reason?: string;
}

export interface EmployeeTrace {
  employee: Employee;
  certificates: EmployeeTraceCertificate[];
  documents: EmployeeTraceDocument[];
  review_tasks: EmployeeTraceReviewTask[];
  reminder_tasks: EmployeeTraceReminderTask[];
  audit_logs: CertificateTraceAuditLog[];
}

export interface CertificateType {
  id: string;
  code: string;
  name: string;
  issuing_authority?: string;
  default_validity_months?: number;
  is_required: boolean;
  force_manual_review: boolean;
  description?: string;
  default_reminder_policy?: CertificateTypeDefaultReminderPolicy | null;
}

export interface CertificateTypeDefaultReminderPolicy {
  id: string;
  name: string;
  days_before_expiry: number[];
  second_reminder_after_days: number;
  escalation_after_days: number;
  channels: string[];
  enabled: boolean;
  updated_at: string;
}

export interface CertificateTypeTracePolicy {
  id: string;
  certificate_type_id?: string;
  name: string;
  days_before_expiry: number[];
  second_reminder_after_days: number;
  escalation_after_days: number;
  channels: string[];
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface CertificateTypeTrace {
  certificate_type: CertificateType;
  reminder_policies: CertificateTypeTracePolicy[];
  certificates: EmployeeCertificate[];
  reminder_tasks: CertificateTraceReminderTask[];
  audit_logs: CertificateTraceAuditLog[];
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
  policy_id?: string;
  status: ReminderTaskStatus;
  trigger_date: string;
  due_date?: string;
  last_event_at?: string;
  resolved_at?: string;
  closed_reason?: string;
  idempotency_key: string;
  created_at: string;
  updated_at: string;
  employee_name?: string;
  employee_no?: string;
  certificate_type_name?: string;
  certificate_no?: string;
  holder_name?: string;
  valid_to?: string;
  policy_name?: string;
}

export interface ReminderEvent {
  id: string;
  reminder_task_id: string;
  event_type: ReminderEventType;
  event_date: string;
  channel?: string;
  recipient?: string;
  provider_message_id?: string;
  payload?: Record<string, unknown>;
  sent_at?: string;
  error?: string;
  created_at: string;
  updated_at: string;
}

export interface ReminderFeedback {
  id: string;
  reminder_task_id: string;
  employee_certificate_id: string;
  status: FeedbackStatus;
  content?: string;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface ReminderTaskTimeline {
  task: ReminderTask;
  events: ReminderEvent[];
  feedback_items: ReminderFeedback[];
  audit_logs: CertificateTraceAuditLog[];
}

export interface ReminderPolicy {
  id: string;
  certificate_type_id?: string | null;
  certificate_type_name?: string | null;
  name: string;
  days_before_expiry: number[];
  second_reminder_after_days: number;
  escalation_after_days: number;
  channels: string[];
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface CertificateDocument {
  id: string;
  employee_id?: string;
  status: DocumentStatus;
  storage_bucket: string;
  storage_key: string;
  original_filename: string;
  content_type?: string;
  file_size?: number;
  sha256?: string;
  paperless_document_id?: string;
  failure_reason?: string;
  created_at: string;
  updated_at: string;
}

export interface CertificateDocumentTrace {
  source_document: CertificateDocument;
  ai_results: AiExtractionResult[];
  review_tasks: ReviewTask[];
  certificates: EmployeeCertificate[];
  audit_logs: CertificateTraceAuditLog[];
}

export interface DashboardRiskRow {
  id: string;
  metric: string;
  count: number;
  status: string;
  target_path: string;
}

export interface DashboardRiskTrace {
  risk: DashboardRiskRow;
  certificates: EmployeeCertificate[];
  documents: CertificateDocument[];
  review_tasks: ReviewTask[];
  reminder_tasks: ReminderTask[];
  audit_logs: CertificateTraceAuditLog[];
  missing_required_items: DashboardMissingRequiredItem[];
}

export interface DashboardMissingRequiredItem {
  employee_id: string;
  employee_no: string;
  employee_name: string;
  department?: string;
  certificate_type_id: string;
  certificate_type_code: string;
  certificate_type_name: string;
  target_path: string;
}

export interface DashboardChartRow {
  category: string;
  count: number;
  target_path: string;
}

export interface DashboardPipelineStep {
  title: string;
  description: string;
  count: number;
  target_path: string;
}

export interface DashboardSummary {
  expiring_count: number;
  expired_count: number;
  pending_review_count: number;
  coverage: number;
  certificate_status_rows: DashboardChartRow[];
  workload_rows: DashboardChartRow[];
  pipeline_steps: DashboardPipelineStep[];
  risk_rows: DashboardRiskRow[];
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
  document_status?: DocumentStatus;
  document_content_type?: string;
  document_file_size?: number;
  document_sha256?: string;
  document_failure_reason?: string;
  document_read_url?: string;
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

export interface RecognitionDispatch {
  document_id: string;
  status: DocumentStatus;
  task_id: string;
}

export interface RecognitionStatus {
  document_id: string;
  status: DocumentStatus;
  ai_result_id?: string;
  failure_reason?: string;
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
  expected_updated_at: string;
}

export interface ReviewDecision {
  review_task: ReviewTask;
  certificate?: EmployeeCertificate;
}

export interface ReviewTaskTrace {
  review_task: ReviewTask;
  source_document?: CertificateDocument | null;
  ai_result?: AiExtractionResult | null;
  certificate?: EmployeeCertificate | null;
  audit_logs: CertificateTraceAuditLog[];
}

export interface ReminderDispatchPayload {
  operator: string;
  simulate: boolean;
  channels?: string[];
}

export interface ReminderDispatchResult {
  task: ReminderTask;
  event_type: string;
  simulated: boolean;
  results: Array<Record<string, unknown>>;
}

export interface ReminderTaskScanPayload {
  operator: string;
  scan_date?: string;
}

export interface ReminderTaskScanResult {
  created: number;
  scan_date: string;
}

export interface CertificateTraceCertificateType {
  id: string;
  code: string;
  name: string;
  issuing_authority?: string;
}

export interface CertificateTraceDocument {
  id: string;
  status: string;
  storage_key: string;
  original_filename: string;
  content_type?: string;
  file_size?: number;
  sha256?: string;
  failure_reason?: string;
  created_at: string;
  updated_at: string;
}

export interface CertificateTraceAiResult {
  id: string;
  document_id: string;
  workflow_run_id?: string;
  model_name?: string;
  output_json: Record<string, unknown>;
  suspicious_points: string[];
  confidence?: number;
  created_at: string;
}

export interface CertificateTraceReviewTask {
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

export interface CertificateTraceReminderTask {
  id: string;
  status: ReminderTaskStatus;
  trigger_date: string;
  due_date?: string;
  last_event_at?: string;
  resolved_at?: string;
  closed_reason?: string;
}

export interface CertificateTraceFeedback {
  id: string;
  reminder_task_id: string;
  status: FeedbackStatus;
  content?: string;
  created_by: string;
  created_at: string;
}

export interface CertificateTraceAuditLog {
  id: string;
  action: string;
  resource_type: string;
  resource_id?: string;
  actor_name?: string;
  request_id?: string;
  ip_address?: string;
  created_at: string;
}

export interface EmployeeCertificateTrace {
  certificate: EmployeeCertificate;
  employee?: Employee;
  certificate_type?: CertificateTraceCertificateType;
  source_document?: CertificateTraceDocument;
  ai_results: CertificateTraceAiResult[];
  review_tasks: CertificateTraceReviewTask[];
  reminder_tasks: CertificateTraceReminderTask[];
  feedback_items: CertificateTraceFeedback[];
  audit_logs: CertificateTraceAuditLog[];
}

export interface ReportChartRow {
  category: string;
  count: number;
  target_path: string;
}

export interface CertificateCoverageDepartmentRow {
  department: string;
  employee_count: number;
  covered_employee_count: number;
  coverage: number;
  target_path: string;
}

export interface CertificateTypeRiskRow {
  certificate_type_id: string;
  certificate_type_name: string;
  is_required: boolean;
  active_count: number;
  expiring_count: number;
  expired_count: number;
  missing_employee_count: number;
  risk_count: number;
  target_path: string;
  active_target_path: string;
  expiring_target_path: string;
  expired_target_path: string;
  missing_employee_target_path: string;
}

export interface CertificateCoverageReport {
  employee_count: number;
  covered_employee_count: number;
  coverage: number;
  department_rows: CertificateCoverageDepartmentRow[];
  certificate_type_risk_rows: CertificateTypeRiskRow[];
  expiry_month_rows: ReportChartRow[];
}
