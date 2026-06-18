import {
  ModalForm,
  PageContainer,
  ProCard,
  ProFormDependency,
  ProFormDigit,
  ProFormSelect,
  ProFormSwitch,
  ProFormText,
  ProFormTextArea,
  ProTable,
  type ActionType,
  type ProColumns,
} from '@ant-design/pro-components';
import { UploadOutlined } from '@ant-design/icons';
import { Alert, Button, Descriptions, Drawer, Empty, Modal, Space, Table, Timeline, Typography, Upload } from 'antd';
import type { UploadProps } from 'antd';
import { useRef, useState } from 'react';

import { createResource, getResource, pageResource, updateResource, uploadResource } from '@/services/api';
import type { CertificateType, CertificateTypeTrace } from '@/types/domain';
import { emptyTableText } from '@/utils/emptyStates';
import {
  auditActionLabel,
  auditResourceTypeLabel,
  certificateTypeRequiredValueEnum,
  certificateStatusLabel,
  forceManualReviewValueEnum,
  reminderChannelLabel,
  reminderChannelOptions,
  reminderStatusLabel,
} from '@/utils/displayLabels';
import { message } from '@/utils/messageApi';
import { downloadCsv } from '@/utils/download';
import { formatDaysBeforeExpiryText, parseDaysBeforeExpiryText } from '@/utils/reminderPolicyForm';

interface CertificateTypeFormValues {
  code?: string;
  name?: string;
  issuing_authority?: string;
  default_validity_months?: number;
  is_required?: boolean;
  force_manual_review?: boolean;
  description?: string;
  configure_default_reminder_policy?: boolean;
  reminder_policy_name?: string;
  reminder_days_before_expiry_text?: string;
  reminder_second_reminder_after_days?: number;
  reminder_escalation_after_days?: number;
  reminder_channels?: string[];
  reminder_enabled?: boolean;
}

interface CertificateTypeImportError {
  row_number: number;
  code?: string;
  message: string;
}

interface CertificateTypeImportResult {
  total: number;
  created: number;
  updated: number;
  failed: number;
  errors: CertificateTypeImportError[];
}

function optionalText(value: string | undefined): string | undefined {
  const trimmed = value?.trim();
  return trimmed || undefined;
}

type DefaultReminderPolicyPayload = {
  name?: string;
  days_before_expiry: number[];
  second_reminder_after_days: number;
  escalation_after_days: number;
  channels: string[];
  enabled: boolean;
};

type CertificateTypePayload = {
  code?: string;
  name?: string;
  issuing_authority?: string;
  default_validity_months?: number;
  is_required: boolean;
  force_manual_review: boolean;
  description?: string;
  default_reminder_policy?: DefaultReminderPolicyPayload;
};

function reminderPolicySummary(record: CertificateType): string {
  const policy = record.default_reminder_policy;
  if (!policy) return '-';
  const status = policy.enabled ? '启用' : '停用';
  const days = policy.days_before_expiry.join('、');
  const channels = policy.channels.map(reminderChannelLabel).join('、');
  return `${status} / 提前 ${days} 天 / ${channels}`;
}

function buildDefaultReminderPolicyPayload(
  values: CertificateTypeFormValues,
): DefaultReminderPolicyPayload | undefined {
  if (!values.configure_default_reminder_policy) return undefined;
  const channels = values.reminder_channels || [];
  if (channels.length === 0) {
    throw new Error('请选择默认提醒渠道');
  }
  return {
    name: optionalText(values.reminder_policy_name),
    days_before_expiry: parseDaysBeforeExpiryText(values.reminder_days_before_expiry_text),
    second_reminder_after_days: values.reminder_second_reminder_after_days ?? 7,
    escalation_after_days: values.reminder_escalation_after_days ?? 5,
    channels,
    enabled: values.reminder_enabled ?? true,
  };
}

function buildInitialValues(currentType: CertificateType | undefined): CertificateTypeFormValues {
  const policy = currentType?.default_reminder_policy;
  if (!currentType) {
    return {
      is_required: true,
      force_manual_review: true,
      configure_default_reminder_policy: true,
      reminder_days_before_expiry_text: '60,30,7',
      reminder_second_reminder_after_days: 7,
      reminder_escalation_after_days: 5,
      reminder_channels: ['email'],
      reminder_enabled: true,
    };
  }
  return {
    code: currentType.code,
    name: currentType.name,
    issuing_authority: currentType.issuing_authority,
    default_validity_months: currentType.default_validity_months,
    is_required: currentType.is_required,
    force_manual_review: currentType.force_manual_review,
    description: currentType.description,
    configure_default_reminder_policy: Boolean(policy),
    reminder_policy_name: policy?.name,
    reminder_days_before_expiry_text: formatDaysBeforeExpiryText(policy?.days_before_expiry),
    reminder_second_reminder_after_days: policy?.second_reminder_after_days ?? 7,
    reminder_escalation_after_days: policy?.escalation_after_days ?? 5,
    reminder_channels: policy?.channels ?? ['email'],
    reminder_enabled: policy?.enabled ?? true,
  };
}

export default function CertificateTypesPage() {
  const actionRef = useRef<ActionType>();
  const lastSearchParamsRef = useRef<Record<string, unknown>>({});
  const [open, setOpen] = useState(false);
  const [currentType, setCurrentType] = useState<CertificateType>();
  const [loadError, setLoadError] = useState<string>();
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState<CertificateTypeImportResult>();
  const [traceOpen, setTraceOpen] = useState(false);
  const [traceLoading, setTraceLoading] = useState(false);
  const [currentTrace, setCurrentTrace] = useState<CertificateTypeTrace>();

  function openCreate() {
    setCurrentType(undefined);
    setOpen(true);
  }

  function openEdit(record: CertificateType) {
    setCurrentType(record);
    setOpen(true);
  }

  async function handleFinish(values: CertificateTypeFormValues): Promise<boolean> {
    let defaultReminderPolicy: DefaultReminderPolicyPayload | undefined;
    try {
      defaultReminderPolicy = buildDefaultReminderPolicyPayload(values);
    } catch (error) {
      message.error(error instanceof Error ? error.message : '默认提醒策略格式不正确');
      return false;
    }

    const payload: CertificateTypePayload = {
      code: values.code?.trim(),
      name: values.name?.trim(),
      issuing_authority: optionalText(values.issuing_authority),
      default_validity_months: values.default_validity_months,
      is_required: values.is_required ?? true,
      force_manual_review: values.force_manual_review ?? true,
      description: optionalText(values.description),
      default_reminder_policy: defaultReminderPolicy,
    };

    try {
      if (currentType) {
        const updatePayload: Omit<CertificateTypePayload, 'code'> = {
          name: payload.name,
          issuing_authority: payload.issuing_authority,
          default_validity_months: payload.default_validity_months,
          is_required: payload.is_required,
          force_manual_review: payload.force_manual_review,
          description: payload.description,
          default_reminder_policy: payload.default_reminder_policy,
        };
        await updateResource<CertificateType, Omit<CertificateTypePayload, 'code'>>(
          `/certificate-types/${currentType.id}`,
          updatePayload,
        );
        message.success('证书类型已更新');
      } else {
        await createResource<CertificateType, CertificateTypePayload>('/certificate-types', payload);
        message.success('证书类型已创建');
      }
      actionRef.current?.reload();
      return true;
    } catch (error) {
      message.error(error instanceof Error ? error.message : '证书类型保存失败');
      return false;
    }
  }

  async function exportCertificateTypes() {
    try {
      await downloadCsv('/certificate-types/export.csv', lastSearchParamsRef.current, 'certificate-types.csv');
      message.success('证书类型已开始导出');
    } catch (error) {
      message.error(error instanceof Error ? error.message : '证书类型导出失败');
    }
  }

  async function downloadImportTemplate() {
    try {
      await downloadCsv('/certificate-types/import-template.csv', {}, 'certificate-types-import-template.csv');
      message.success('证书类型导入模板已开始下载');
    } catch (error) {
      message.error(error instanceof Error ? error.message : '证书类型导入模板下载失败');
    }
  }

  async function importCertificateTypes(file: File) {
    const formData = new FormData();
    formData.append('file', file);
    setImporting(true);
    try {
      const result = await uploadResource<CertificateTypeImportResult>('/certificate-types/import.csv', formData);
      setImportResult(result);
      actionRef.current?.reload();
      message.success(`证书类型导入完成：新增 ${result.created} 项，更新 ${result.updated} 项`);
    } catch (error) {
      message.error(error instanceof Error ? error.message : '证书类型导入失败');
    } finally {
      setImporting(false);
    }
  }

  async function openTrace(record: CertificateType) {
    setTraceOpen(true);
    setTraceLoading(true);
    setCurrentTrace(undefined);
    try {
      const trace = await getResource<CertificateTypeTrace>(`/certificate-types/${record.id}/trace`);
      setCurrentTrace(trace);
    } catch (error) {
      message.error(error instanceof Error ? error.message : '证书类型追溯链路加载失败');
    } finally {
      setTraceLoading(false);
    }
  }

  const importUploadProps: UploadProps = {
    accept: '.csv,text/csv',
    showUploadList: false,
    beforeUpload: (file) => {
      void importCertificateTypes(file);
      return false;
    },
  };

  const columns: ProColumns<CertificateType>[] = [
    { title: '编码', dataIndex: 'code', width: 140 },
    { title: '证书类型', dataIndex: 'name' },
    { title: '发证机构', dataIndex: 'issuing_authority' },
    { title: '默认有效期(月)', dataIndex: 'default_validity_months', valueType: 'digit', width: 140 },
    {
      title: '是否必备',
      dataIndex: 'is_required',
      width: 110,
      valueType: 'select',
      valueEnum: certificateTypeRequiredValueEnum,
      renderText: (val: boolean) => String(val),
    },
    {
      title: '默认提醒策略',
      dataIndex: 'default_reminder_policy',
      search: false,
      ellipsis: true,
      renderText: (_, record) => reminderPolicySummary(record),
    },
    {
      title: '强制复核',
      dataIndex: 'force_manual_review',
      width: 110,
      valueType: 'select',
      valueEnum: forceManualReviewValueEnum,
      renderText: (val: boolean) => String(val),
    },
    {
      title: '操作',
      valueType: 'option',
      width: 150,
      render: (_, record) => (
        <Space>
          <Button type="link" size="small" onClick={() => openTrace(record)}>
            追溯
          </Button>
          <Button type="link" size="small" onClick={() => openEdit(record)}>
            编辑
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <PageContainer title="证书类型管理">
      {loadError ? (
        <Alert
          type="error"
          showIcon
          title="证书类型数据加载失败"
          description={loadError}
          style={{ marginBottom: 16 }}
          closable={{ onClose: () => setLoadError(undefined) }}
        />
      ) : null}
      <ProTable<CertificateType>
        actionRef={actionRef}
        rowKey="id"
        columns={columns}
        request={async (params) => {
          try {
            const { current, pageSize, ...searchParams } = params;
            lastSearchParamsRef.current = searchParams;
            const result = await pageResource<CertificateType>('/certificate-types/page', {
              ...searchParams,
              current,
              page_size: pageSize,
            });
            setLoadError(undefined);
            return { data: result.data, total: result.total, success: true };
          } catch (error) {
            const description = error instanceof Error ? error.message : '证书类型数据加载失败';
            setLoadError(description);
            message.error(description);
            return { data: [], success: false };
          }
        }}
        locale={{ emptyText: emptyTableText('暂无证书类型，请先新增可管理的证书类型') }}
        toolbar={{
          title: '证书类型',
          actions: [
            <Button key="template" onClick={downloadImportTemplate}>
              下载导入模板
            </Button>,
            <Upload key="import" {...importUploadProps}>
              <Button icon={<UploadOutlined />} loading={importing}>
                导入CSV
              </Button>
            </Upload>,
            <Button key="export" onClick={exportCertificateTypes}>
              导出当前筛选
            </Button>,
            <Button key="create" type="primary" onClick={openCreate}>
              新增证书类型
            </Button>,
          ],
        }}
        pagination={{ defaultPageSize: 20, showSizeChanger: true }}
        search={{ labelWidth: 96 }}
      />

      <ModalForm<CertificateTypeFormValues>
        key={currentType?.id ?? 'create'}
        title={currentType ? '编辑证书类型' : '新增证书类型'}
        open={open}
        onOpenChange={setOpen}
        modalProps={{ destroyOnHidden: true, mask: { closable: false } }}
        layout="horizontal"
        labelCol={{ span: 6 }}
        width={680}
        initialValues={buildInitialValues(currentType)}
        onFinish={handleFinish}
      >
        <ProFormText
          name="code"
          label="编码"
          disabled={Boolean(currentType)}
          rules={[{ required: true, message: '请输入编码' }]}
        />
        <ProFormText name="name" label="证书类型" rules={[{ required: true, message: '请输入证书类型' }]} />
        <ProFormText name="issuing_authority" label="发证机构" />
        <ProFormDigit name="default_validity_months" label="默认有效期(月)" min={1} />
        <ProFormSwitch
          name="is_required"
          label="必备证书"
          extra="开启后会纳入缺失必备证书统计；关闭后仍可维护持证记录，但不会把未持有员工计入缺失风险。"
        />
        <ProFormSwitch name="force_manual_review" label="强制复核" />
        <ProFormTextArea name="description" label="说明" />
        <ProFormSwitch
          name="configure_default_reminder_policy"
          label="维护默认提醒"
          extra="开启后会为该证书类型创建或更新绑定的提醒策略，审批生成的正式证书会按该策略进入提醒扫描。"
        />
        <ProFormDependency name={['configure_default_reminder_policy']}>
          {({ configure_default_reminder_policy }) =>
            configure_default_reminder_policy ? (
              <>
                <ProFormText name="reminder_policy_name" label="策略名称" placeholder="默认使用证书类型名生成" />
                <ProFormText
                  name="reminder_days_before_expiry_text"
                  label="提前提醒天数"
                  extra="多个天数用逗号分隔，例如 60,30,7"
                  rules={[{ required: true, message: '请输入提前提醒天数' }]}
                />
                <ProFormDigit
                  name="reminder_second_reminder_after_days"
                  label="二次提醒间隔"
                  min={1}
                  rules={[{ required: true, message: '请输入二次提醒间隔' }]}
                />
                <ProFormDigit
                  name="reminder_escalation_after_days"
                  label="升级提醒间隔"
                  min={1}
                  rules={[{ required: true, message: '请输入升级提醒间隔' }]}
                />
                <ProFormSelect
                  name="reminder_channels"
                  label="提醒渠道"
                  mode="multiple"
                  options={reminderChannelOptions}
                  rules={[{ required: true, message: '请选择提醒渠道' }]}
                />
                <ProFormSwitch name="reminder_enabled" label="启用策略" />
              </>
            ) : null
          }
        </ProFormDependency>
      </ModalForm>

      <Modal
        title="证书类型导入结果"
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
              title={`共处理 ${importResult.total} 行，新增 ${importResult.created} 项，更新 ${importResult.updated} 项，失败 ${importResult.failed} 行`}
              style={{ marginBottom: 16 }}
            />
            {importResult.errors.length > 0 ? (
              <Table<CertificateTypeImportError>
                size="small"
                rowKey={(record) => `${record.row_number}-${record.code ?? 'empty'}`}
                pagination={false}
                dataSource={importResult.errors}
                columns={[
                  { title: '行号', dataIndex: 'row_number', width: 80 },
                  { title: '编码', dataIndex: 'code', width: 120 },
                  { title: '原因', dataIndex: 'message' },
                ]}
              />
            ) : null}
          </>
        ) : null}
      </Modal>

      <Drawer
        title="证书类型全链路追溯"
        open={traceOpen}
        onClose={() => setTraceOpen(false)}
        size={840}
        loading={traceLoading}
      >
        {currentTrace ? (
          <Space orientation="vertical" size={16} style={{ width: '100%' }}>
            <ProCard title="证书类型">
              <Descriptions column={2} size="small">
                <Descriptions.Item label="编码">{currentTrace.certificate_type.code}</Descriptions.Item>
                <Descriptions.Item label="名称">{currentTrace.certificate_type.name}</Descriptions.Item>
                <Descriptions.Item label="发证机构">
                  {currentTrace.certificate_type.issuing_authority || '-'}
                </Descriptions.Item>
                <Descriptions.Item label="默认有效期">
                  {currentTrace.certificate_type.default_validity_months
                    ? `${currentTrace.certificate_type.default_validity_months} 个月`
                    : '-'}
                </Descriptions.Item>
                <Descriptions.Item label="是否必备">
                  {currentTrace.certificate_type.is_required ? '必备' : '可选'}
                </Descriptions.Item>
                <Descriptions.Item label="强制复核">
                  {currentTrace.certificate_type.force_manual_review ? '是' : '否'}
                </Descriptions.Item>
                <Descriptions.Item label="说明">{currentTrace.certificate_type.description || '-'}</Descriptions.Item>
              </Descriptions>
            </ProCard>

            <ProCard title={`提醒策略（${currentTrace.reminder_policies.length}）`}>
              {currentTrace.reminder_policies.length > 0 ? (
                <Timeline
                  items={currentTrace.reminder_policies.map((policy) => ({
                    color: policy.enabled ? 'green' : 'gray',
                    content: (
                      <Space orientation="vertical" size={4}>
                        <Typography.Text strong>
                          {policy.name} / {policy.enabled ? '启用' : '停用'}
                        </Typography.Text>
                        <Typography.Text type="secondary">
                          提前 {policy.days_before_expiry.join(' / ')} 天；渠道{' '}
                          {policy.channels.map(reminderChannelLabel).join(' / ')}
                        </Typography.Text>
                      </Space>
                    ),
                  }))}
                />
              ) : (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无提醒策略" />
              )}
            </ProCard>

            <ProCard title={`关联持证记录（${currentTrace.certificates.length}）`}>
              {currentTrace.certificates.length > 0 ? (
                <Timeline
                  items={currentTrace.certificates.map((certificate) => ({
                    color: certificate.status === 'ACTIVE' || certificate.status === 'EXPIRING' ? 'green' : 'gray',
                    content: (
                      <Space orientation="vertical" size={4}>
                        <Typography.Text strong>
                          {certificate.holder_name} / {certificate.certificate_no || '-'} /{' '}
                          {certificateStatusLabel(certificate.status)}
                        </Typography.Text>
                        <Typography.Text type="secondary">
                          员工：{certificate.employee_id} / 到期：{certificate.valid_to || '-'}
                        </Typography.Text>
                      </Space>
                    ),
                  }))}
                />
              ) : (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无关联持证记录" />
              )}
            </ProCard>

            <ProCard title={`提醒任务（${currentTrace.reminder_tasks.length}）`}>
              {currentTrace.reminder_tasks.length > 0 ? (
                <Timeline
                  items={currentTrace.reminder_tasks.map((task) => ({
                    color: task.status === 'ESCALATED' ? 'red' : 'blue',
                    content: `${reminderStatusLabel(task.status)} / 发起 ${task.trigger_date} / 截止 ${
                      task.due_date || '-'
                    }`,
                  }))}
                />
              ) : (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无提醒任务" />
              )}
            </ProCard>

            <ProCard title={`审计记录（${currentTrace.audit_logs.length}）`}>
              {currentTrace.audit_logs.length > 0 ? (
                <Timeline
                  items={currentTrace.audit_logs.map((log) => ({
                    content: `${log.created_at} / ${auditActionLabel(log.action)} / ${auditResourceTypeLabel(
                      log.resource_type,
                    )} / ${log.actor_name || '-'}`,
                  }))}
                />
              ) : (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无审计记录" />
              )}
            </ProCard>
          </Space>
        ) : (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="请选择证书类型查看追溯链路" />
        )}
      </Drawer>
    </PageContainer>
  );
}
