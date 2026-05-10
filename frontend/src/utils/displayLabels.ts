import type { CertificateStatus, EmploymentStatus, ReminderTaskStatus, ReviewStatus } from '@/types/domain';

const employmentStatusLabels: Record<string, string> = {
  ACTIVE: '在职',
  ON_LEAVE: '休假',
  LEFT: '离职',
};

const certificateStatusLabels: Record<string, string> = {
  DRAFT: '草稿',
  PENDING_REVIEW: '待复核',
  ACTIVE: '有效',
  EXPIRING: '即将到期',
  EXPIRED: '已过期',
  RENEWED: '已续证',
  REPLACED: '已替换',
  ARCHIVED: '已归档',
};

const documentStatusLabels: Record<string, string> = {
  UPLOADED: '已上传',
  PARSING: '解析中',
  PENDING_REVIEW: '待复核',
  CONFIRMED: '已确认',
  FAILED: '处理失败',
  ARCHIVED: '已归档',
};

const reviewStatusLabels: Record<string, string> = {
  PENDING: '待复核',
  APPROVED: '已通过',
  REJECTED: '已驳回',
  NEEDS_INFO: '需补充',
};

const reminderStatusLabels: Record<string, string> = {
  PENDING: '待处理',
  FIRST_SENT: '已首次提醒',
  WAITING_FEEDBACK: '等待反馈',
  SECOND_SENT: '已二次提醒',
  ESCALATED: '已升级',
  RESOLVED: '已解决',
  CLOSED: '已关闭',
};

const feedbackStatusLabels: Record<string, string> = {
  NOTIFIED_EMPLOYEE: '已通知员工',
  PROCESSING: '办理中',
  RENEWED: '已换证',
  NO_ACTION_REQUIRED: '无需处理',
  EMPLOYEE_LEFT: '员工离职',
  IGNORED: '已忽略',
};

const auditActionLabels: Record<string, string> = {
  'certificate_document.upload_intent.create': '创建证书文件上传任务',
  'certificate_document.recognize': '发起证书智能识别',
  'certificate_document.recognize.failed': '证书智能识别失败',
  'employee_certificate.create': '创建持证记录',
  'employee_certificate.update': '更新持证记录',
  'certificate_type.create': '创建证书类型',
  'certificate_type.update': '更新证书类型',
  'employee.create': '创建人员档案',
  'employee.update': '更新人员档案',
  'reminder_policy.create': '创建提醒策略',
  'reminder_task.notification.dispatch': '发送提醒通知',
  'reminder_task.feedback.create': '记录人力反馈',
  'review_task.approve': '复核通过',
  'review_task.reject': '复核驳回',
};

const auditResourceTypeLabels: Record<string, string> = {
  certificate_document: '证书文件',
  employee_certificate: '持证记录',
  certificate_type: '证书类型',
  employee: '人员档案',
  reminder_policy: '提醒策略',
  reminder_task: '提醒任务',
  review_task: '复核任务',
};

export const employmentStatusOptions: Array<{ label: string; value: EmploymentStatus }> = [
  { label: '在职', value: 'ACTIVE' },
  { label: '休假', value: 'ON_LEAVE' },
  { label: '离职', value: 'LEFT' },
];

export const certificateStatusOptions: Array<{ label: string; value: CertificateStatus }> = [
  { label: '草稿', value: 'DRAFT' },
  { label: '待复核', value: 'PENDING_REVIEW' },
  { label: '有效', value: 'ACTIVE' },
  { label: '即将到期', value: 'EXPIRING' },
  { label: '已过期', value: 'EXPIRED' },
  { label: '已续证', value: 'RENEWED' },
  { label: '已替换', value: 'REPLACED' },
  { label: '已归档', value: 'ARCHIVED' },
];

export const reviewStatusOptions: Array<{ label: string; value: ReviewStatus }> = [
  { label: '待复核', value: 'PENDING' },
  { label: '已通过', value: 'APPROVED' },
  { label: '已驳回', value: 'REJECTED' },
  { label: '需补充', value: 'NEEDS_INFO' },
];

export const reminderStatusOptions: Array<{ label: string; value: ReminderTaskStatus }> = [
  { label: '待处理', value: 'PENDING' },
  { label: '已首次提醒', value: 'FIRST_SENT' },
  { label: '等待反馈', value: 'WAITING_FEEDBACK' },
  { label: '已二次提醒', value: 'SECOND_SENT' },
  { label: '已升级', value: 'ESCALATED' },
  { label: '已解决', value: 'RESOLVED' },
  { label: '已关闭', value: 'CLOSED' },
];

function labelFromMap(value: string | null | undefined, labels: Record<string, string>): string {
  if (!value) return '-';
  return labels[value] || value;
}

export function employmentStatusLabel(value: EmploymentStatus | null | undefined): string {
  return labelFromMap(value, employmentStatusLabels);
}

export function certificateStatusLabel(value: CertificateStatus | null | undefined): string {
  return labelFromMap(value, certificateStatusLabels);
}

export function documentStatusLabel(value: string | null | undefined): string {
  return labelFromMap(value, documentStatusLabels);
}

export function reviewStatusLabel(value: ReviewStatus | null | undefined): string {
  return labelFromMap(value, reviewStatusLabels);
}

export function reminderStatusLabel(value: ReminderTaskStatus | null | undefined): string {
  return labelFromMap(value, reminderStatusLabels);
}

export function feedbackStatusLabel(value: string | null | undefined): string {
  return labelFromMap(value, feedbackStatusLabels);
}

export function auditActionLabel(value: string | null | undefined): string {
  return labelFromMap(value, auditActionLabels);
}

export function auditResourceTypeLabel(value: string | null | undefined): string {
  return labelFromMap(value, auditResourceTypeLabels);
}
