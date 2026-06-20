import type {
  CertificateStatus,
  DocumentStatus,
  EmploymentStatus,
  ReminderEventType,
  ReminderTaskStatus,
  ReviewStatus,
} from '@/types/domain';

type ProValueEnumStatus = 'Default' | 'Processing' | 'Success' | 'Warning' | 'Error';
export type StatusValueEnum<K extends string = string> = Record<
  K,
  { text: string; status?: ProValueEnumStatus }
>;

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
  PENDING_UPLOAD: '待确认上传',
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

const reminderEventTypeLabels: Record<string, string> = {
  FIRST_REMINDER: '首次提醒',
  SECOND_REMINDER: '二次提醒',
  ESCALATION: '升级提醒',
  FEEDBACK: '人力反馈',
  CLOSED: '关闭',
  FAILED: '失败',
};

const feedbackStatusLabels: Record<string, string> = {
  NOTIFIED_EMPLOYEE: '已通知员工',
  PROCESSING: '办理中',
  RENEWED: '已换证',
  NO_ACTION_REQUIRED: '无需处理',
  EMPLOYEE_LEFT: '员工离职',
  IGNORED: '已忽略',
};

export const reminderChannelOptions = [
  { label: '邮件', value: 'email' },
  { label: '企业微信', value: 'wecom' },
  { label: '钉钉', value: 'dingtalk' },
  { label: '飞书', value: 'feishu' },
];

const auditActionLabels: Record<string, string> = {
  'certificate_document.upload_intent.create': '创建证书文件上传任务',
  'certificate_document.upload.confirm': '确认证书文件上传',
  'certificate_document.upload.confirm.failed': '证书文件上传确认失败',
  'certificate_document.recognize': '发起证书智能识别',
  'certificate_document.recognize.dispatched': '派发证书智能识别',
  'certificate_document.recognize.failed': '证书智能识别失败',
  'employee_certificate.create': '创建持证记录',
  'employee_certificate.update': '更新持证记录',
  'certificate_type.create': '创建证书类型',
  'certificate_type.update': '更新证书类型',
  'certificate_type.import.create': '导入新增证书类型',
  'certificate_type.import.update': '导入更新证书类型',
  'certificate_type.default_reminder_policy.create': '创建证书类型默认提醒策略',
  'certificate_type.default_reminder_policy.update': '更新证书类型默认提醒策略',
  'employee.create': '创建人员档案',
  'employee.update': '更新人员档案',
  'employee.import.create': '导入新增人员档案',
  'employee.import.update': '导入更新人员档案',
  'reminder_policy.create': '创建提醒策略',
  'reminder_policy.update': '更新提醒策略',
  'reminder_task.scan': '扫描生成提醒任务',
  'reminder_task.notification.dispatch': '发送提醒通知',
  'reminder_task.notification.manual_dispatch': '手动发送提醒通知',
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

export const auditResourceTypeOptions = Object.entries(auditResourceTypeLabels).map(
  ([value, label]) => ({ label, value }),
);

export const auditActionOptions = Object.entries(auditActionLabels).map(([value, label]) => ({
  label,
  value,
}));

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

export function reminderEventTypeLabel(value: ReminderEventType | null | undefined): string {
  return labelFromMap(value, reminderEventTypeLabels);
}

export function feedbackStatusLabel(value: string | null | undefined): string {
  return labelFromMap(value, feedbackStatusLabels);
}

export function reminderChannelLabel(value: string | null | undefined): string {
  if (!value) return '-';
  return reminderChannelOptions.find((option) => option.value === value)?.label || value;
}

export function auditActionLabel(value: string | null | undefined): string {
  return labelFromMap(value, auditActionLabels);
}

export function auditResourceTypeLabel(value: string | null | undefined): string {
  return labelFromMap(value, auditResourceTypeLabels);
}

export const employmentStatusValueEnum: StatusValueEnum<EmploymentStatus> = {
  ACTIVE: { text: '在职', status: 'Success' },
  ON_LEAVE: { text: '休假', status: 'Warning' },
  LEFT: { text: '离职', status: 'Default' },
};

export const certificateStatusValueEnum: StatusValueEnum<CertificateStatus> = {
  DRAFT: { text: '草稿', status: 'Default' },
  PENDING_REVIEW: { text: '待复核', status: 'Processing' },
  ACTIVE: { text: '有效', status: 'Success' },
  EXPIRING: { text: '即将到期', status: 'Warning' },
  EXPIRED: { text: '已过期', status: 'Error' },
  RENEWED: { text: '已续证', status: 'Success' },
  REPLACED: { text: '已替换', status: 'Default' },
  ARCHIVED: { text: '已归档', status: 'Default' },
};

export const reviewStatusValueEnum: StatusValueEnum<ReviewStatus> = {
  PENDING: { text: '待复核', status: 'Processing' },
  APPROVED: { text: '已通过', status: 'Success' },
  REJECTED: { text: '已驳回', status: 'Error' },
  NEEDS_INFO: { text: '需补充', status: 'Warning' },
};

export const reminderStatusValueEnum: StatusValueEnum<ReminderTaskStatus> = {
  PENDING: { text: '待处理', status: 'Default' },
  FIRST_SENT: { text: '已首次提醒', status: 'Processing' },
  WAITING_FEEDBACK: { text: '等待反馈', status: 'Warning' },
  SECOND_SENT: { text: '已二次提醒', status: 'Warning' },
  ESCALATED: { text: '已升级', status: 'Error' },
  RESOLVED: { text: '已解决', status: 'Success' },
  CLOSED: { text: '已关闭', status: 'Default' },
};

export const forceManualReviewValueEnum: StatusValueEnum<'true' | 'false'> = {
  true: { text: '是', status: 'Warning' },
  false: { text: '否', status: 'Success' },
};

export const certificateTypeRequiredValueEnum: StatusValueEnum<'true' | 'false'> = {
  true: { text: '必备', status: 'Error' },
  false: { text: '可选', status: 'Default' },
};

export const documentStatusValueEnum: StatusValueEnum<DocumentStatus> = {
  PENDING_UPLOAD: { text: '待确认上传', status: 'Processing' },
  UPLOADED: { text: '已上传', status: 'Processing' },
  PARSING: { text: '解析中', status: 'Processing' },
  PENDING_REVIEW: { text: '待复核', status: 'Warning' },
  CONFIRMED: { text: '已确认', status: 'Success' },
  FAILED: { text: '处理失败', status: 'Error' },
  ARCHIVED: { text: '已归档', status: 'Default' },
};
