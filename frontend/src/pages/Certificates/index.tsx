import {
  DrawerForm,
  PageContainer,
  ProCard,
  ProFormDatePicker,
  ProFormSelect,
  ProFormText,
  ProTable,
  type ActionType,
  type ProColumns,
} from '@ant-design/pro-components';
import { Alert, Button, Collapse, Descriptions, Drawer, Empty, Space, Timeline, Typography } from 'antd';
import { useEffect, useMemo, useState, useRef } from 'react';

import { useLocation } from '@umijs/max';

import { createResource, getResource, listResource, pageResource, updateResource } from '@/services/api';
import type {
  CertificateStatus,
  CertificateType,
  Employee,
  EmployeeCertificate,
  EmployeeCertificateTrace,
} from '@/types/domain';
import {
  auditActionLabel,
  auditResourceTypeLabel,
  certificateStatusLabel,
  certificateStatusOptions,
  certificateStatusValueEnum,
  documentStatusLabel,
  feedbackStatusLabel,
  reminderStatusLabel,
  reviewStatusLabel,
} from '@/utils/displayLabels';
import { downloadCsv } from '@/utils/download';
import { emptyTableText } from '@/utils/emptyStates';
import { certificateTypeSelectRequest, employeeOptionLabel, employeeSelectOption, employeeSelectRequest } from '@/utils/formOptions';
import { message } from '@/utils/messageApi';

interface CertificateFormValues {
  employee_id?: string;
  certificate_type_id?: string;
  certificate_no?: string;
  holder_name?: string;
  issuing_authority?: string;
  issue_date?: unknown;
  valid_from?: unknown;
  valid_to?: unknown;
  review_date?: unknown;
  status?: CertificateStatus;
  confirmed_by?: string;
}

function optionalText(value: string | undefined): string | undefined {
  const trimmed = value?.trim();
  return trimmed || undefined;
}

function formatDateValue(value: unknown): string | undefined {
  if (!value) return undefined;
  if (typeof value === 'string') return value.slice(0, 10);
  if (typeof value === 'object' && value && 'format' in value && typeof value.format === 'function') {
    return value.format('YYYY-MM-DD');
  }
  return undefined;
}

function traceValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '-';
  if (typeof value === 'object') return JSON.stringify(value, null, 2);
  return String(value);
}

export default function CertificatesPage() {
  const actionRef = useRef<ActionType>();
  const lastSearchParamsRef = useRef<Record<string, unknown>>({});
  const location = useLocation();
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [certificateTypes, setCertificateTypes] = useState<CertificateType[]>([]);
  const [open, setOpen] = useState(false);
  const [currentCertificate, setCurrentCertificate] = useState<EmployeeCertificate>();
  const [traceOpen, setTraceOpen] = useState(false);
  const [traceLoading, setTraceLoading] = useState(false);
  const [currentTrace, setCurrentTrace] = useState<EmployeeCertificateTrace>();
  const [loadError, setLoadError] = useState<string>();

  // Keep useEffect to provide id->name mapping for table columns; form selects use ProFormSelect.request.
  useEffect(() => {
    async function loadOptions() {
      const [employeeList, typeList] = await Promise.all([
        listResource<Employee>('/employees'),
        listResource<CertificateType>('/certificate-types'),
      ]);
      setEmployees(employeeList);
      setCertificateTypes(typeList);
    }

    void loadOptions().catch((error) => {
      message.error(error instanceof Error ? error.message : '基础数据加载失败');
    });
  }, []);

  const employeeNameById = useMemo(
    () => new Map(employees.map((employee) => [employee.id, employeeOptionLabel(employee)])),
    [employees],
  );
  const certificateTypeNameById = useMemo(
    () => new Map(certificateTypes.map((certificateType) => [certificateType.id, certificateType.name])),
    [certificateTypes],
  );
  const urlFilters = useMemo(() => {
    const params = new URLSearchParams(location.search);
    const status = params.get('status');
    const certificateTypeId = params.get('certificate_type_id');
    const statusGroup = params.get('status_group');
    const validToFrom = params.get('valid_to_from');
    const validToTo = params.get('valid_to_to');
    return {
      ...(status && status in certificateStatusValueEnum ? { status: status as CertificateStatus } : {}),
      ...(certificateTypeId ? { certificate_type_id: certificateTypeId } : {}),
      ...(statusGroup ? { status_group: statusGroup } : {}),
      ...(validToFrom ? { valid_to_from: validToFrom } : {}),
      ...(validToTo ? { valid_to_to: validToTo } : {}),
    };
  }, [location.search]);

  function openCreate() {
    setCurrentCertificate(undefined);
    setOpen(true);
  }

  function openEdit(record: EmployeeCertificate) {
    setCurrentCertificate(record);
    setOpen(true);
  }

  async function handleFinish(values: CertificateFormValues): Promise<boolean> {
    const payload = {
      employee_id: values.employee_id!,
      certificate_type_id: values.certificate_type_id!,
      certificate_no: optionalText(values.certificate_no),
      holder_name: values.holder_name!.trim(),
      issuing_authority: optionalText(values.issuing_authority),
      issue_date: formatDateValue(values.issue_date),
      valid_from: formatDateValue(values.valid_from),
      valid_to: formatDateValue(values.valid_to),
      review_date: formatDateValue(values.review_date),
      status: values.status || 'ACTIVE',
      confirmed_by: optionalText(values.confirmed_by),
    };

    try {
      if (currentCertificate) {
        await updateResource<EmployeeCertificate, typeof payload>(`/certificates/${currentCertificate.id}`, payload);
        message.success('持证记录已更新');
      } else {
        await createResource<EmployeeCertificate, typeof payload>('/certificates', payload);
        message.success('持证记录已创建');
      }
      actionRef.current?.reload();
      return true;
    } catch (error) {
      message.error(error instanceof Error ? error.message : '持证记录保存失败');
      return false;
    }
  }

  async function exportCertificates() {
    try {
      await downloadCsv('/certificates/export.csv', lastSearchParamsRef.current, 'employee-certificates.csv');
      message.success('持证记录已开始导出');
    } catch (error) {
      message.error(error instanceof Error ? error.message : '持证记录导出失败');
    }
  }

  async function openTrace(record: EmployeeCertificate) {
    setTraceOpen(true);
    setTraceLoading(true);
    setCurrentTrace(undefined);
    try {
      const trace = await getResource<EmployeeCertificateTrace>(`/certificates/${record.id}/trace`);
      setCurrentTrace(trace);
    } catch (error) {
      message.error(error instanceof Error ? error.message : '追溯链路加载失败');
    } finally {
      setTraceLoading(false);
    }
  }

  const columns: ProColumns<EmployeeCertificate>[] = [
    {
      title: '员工',
      dataIndex: 'employee_id',
      width: 180,
      renderText: (value) => employeeNameById.get(value) || value,
      valueType: 'select',
      fieldProps: {
        showSearch: true,
        options: employees.map(employeeSelectOption),
      },
    },
    {
      title: '证书类型',
      dataIndex: 'certificate_type_id',
      width: 180,
      renderText: (value) => certificateTypeNameById.get(value) || value,
      valueType: 'select',
      fieldProps: {
        showSearch: true,
        options: certificateTypes.map((certificateType) => ({
          label: certificateType.name,
          value: certificateType.id,
        })),
      },
    },
    { title: '持证人', dataIndex: 'holder_name', width: 140 },
    { title: '证书编号', dataIndex: 'certificate_no', width: 180 },
    { title: '发证机构', dataIndex: 'issuing_authority' },
    { title: '发证日期', dataIndex: 'issue_date', valueType: 'date', width: 130, search: false },
    { title: '到期日期', dataIndex: 'valid_to', valueType: 'date', width: 130, search: false },
    {
      title: '到期区间',
      dataIndex: 'valid_to_range',
      valueType: 'dateRange',
      hideInTable: true,
      search: {
        transform: (value) => ({
          valid_to_from: value?.[0],
          valid_to_to: value?.[1],
        }),
      },
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 130,
      valueType: 'select',
      valueEnum: certificateStatusValueEnum,
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
    <PageContainer title="持证记录">
      {loadError ? (
        <Alert
          type="error"
          showIcon
          title="持证记录加载失败"
          description={loadError}
          style={{ marginBottom: 16 }}
          closable={{ onClose: () => setLoadError(undefined) }}
        />
      ) : null}
      <ProTable<EmployeeCertificate>
        actionRef={actionRef}
        rowKey="id"
        columns={columns}
        params={urlFilters}
        request={async (params) => {
          try {
            const { current, pageSize, ...searchParams } = params;
            const nextSearchParams = { ...searchParams };
            delete nextSearchParams.valid_to_range;
            lastSearchParamsRef.current = nextSearchParams;
            const result = await pageResource<EmployeeCertificate>('/certificates/page', {
              ...nextSearchParams,
              current,
              page_size: pageSize,
            });
            setLoadError(undefined);
            return { data: result.data, total: result.total, success: true };
          } catch (error) {
            const description = error instanceof Error ? error.message : '持证记录加载失败';
            setLoadError(description);
            message.error(description);
            return { data: [], success: false };
          }
        }}
        locale={{ emptyText: emptyTableText('暂无持证记录，请先上传识别或手动新增') }}
        toolbar={{
          title: '当前与历史持证记录',
          actions: [
            <Button key="export" onClick={exportCertificates}>
              导出当前筛选
            </Button>,
            <Button key="create" type="primary" onClick={openCreate}>
              新增持证记录
            </Button>,
          ],
        }}
        pagination={{ defaultPageSize: 20, showSizeChanger: true }}
        search={{ labelWidth: 88 }}
      />

      <DrawerForm<CertificateFormValues>
        key={currentCertificate?.id ?? 'create'}
        title={currentCertificate ? '编辑持证记录' : '新增持证记录'}
        open={open}
        onOpenChange={setOpen}
        drawerProps={{ destroyOnHidden: true, mask: { closable: false } }}
        layout="horizontal"
        labelCol={{ span: 5 }}
        width={640}
        initialValues={
          currentCertificate
            ? {
                employee_id: currentCertificate.employee_id,
                certificate_type_id: currentCertificate.certificate_type_id,
                certificate_no: currentCertificate.certificate_no,
                holder_name: currentCertificate.holder_name,
                issuing_authority: currentCertificate.issuing_authority,
                issue_date: currentCertificate.issue_date,
                valid_from: currentCertificate.valid_from,
                valid_to: currentCertificate.valid_to,
                review_date: currentCertificate.review_date,
                status: currentCertificate.status,
                confirmed_by: currentCertificate.confirmed_by,
              }
            : { status: 'ACTIVE' as CertificateStatus }
        }
        onFinish={handleFinish}
      >
        <ProFormSelect
          name="employee_id"
          label="员工"
          rules={[{ required: true, message: '请选择员工' }]}
          request={employeeSelectRequest}
          showSearch
        />
        <ProFormSelect
          name="certificate_type_id"
          label="证书类型"
          rules={[{ required: true, message: '请选择证书类型' }]}
          request={certificateTypeSelectRequest}
          showSearch
        />
        <ProFormText name="holder_name" label="持证人" rules={[{ required: true, message: '请输入持证人' }]} />
        <ProFormText name="certificate_no" label="证书编号" />
        <ProFormText name="issuing_authority" label="发证机构" />
        <ProFormDatePicker name="issue_date" label="发证日期" />
        <ProFormDatePicker name="valid_from" label="有效开始" />
        <ProFormDatePicker name="valid_to" label="有效截止" />
        <ProFormDatePicker name="review_date" label="复审日期" />
        <ProFormSelect
          name="status"
          label="状态"
          rules={[{ required: true, message: '请选择状态' }]}
          options={certificateStatusOptions}
        />
        <ProFormText name="confirmed_by" label="确认人" />
      </DrawerForm>

      <Drawer
        title="持证记录全链路追溯"
        open={traceOpen}
        onClose={() => setTraceOpen(false)}
        size={840}
        loading={traceLoading}
      >
        {currentTrace ? (
          <Space orientation="vertical" size={16} style={{ width: '100%' }}>
            <ProCard title="正式持证记录">
              <Descriptions column={2} size="small">
                <Descriptions.Item label="持证人">{currentTrace.certificate.holder_name}</Descriptions.Item>
                <Descriptions.Item label="证书编号">
                  {currentTrace.certificate.certificate_no || '-'}
                </Descriptions.Item>
                <Descriptions.Item label="状态">
                  {certificateStatusLabel(currentTrace.certificate.status)}
                </Descriptions.Item>
                <Descriptions.Item label="确认人">
                  {currentTrace.certificate.confirmed_by || '-'}
                </Descriptions.Item>
                <Descriptions.Item label="确认时间">
                  {currentTrace.certificate.confirmed_at || '-'}
                </Descriptions.Item>
                <Descriptions.Item label="到期日期">{currentTrace.certificate.valid_to || '-'}</Descriptions.Item>
              </Descriptions>
            </ProCard>

            <ProCard title="人员与证书类型">
              <Descriptions column={2} size="small">
                <Descriptions.Item label="员工">
                  {currentTrace.employee
                    ? `${currentTrace.employee.name}（${currentTrace.employee.employee_no}）`
                    : '-'}
                </Descriptions.Item>
                <Descriptions.Item label="部门">{currentTrace.employee?.department || '-'}</Descriptions.Item>
                <Descriptions.Item label="证书类型">
                  {currentTrace.certificate_type
                    ? `${currentTrace.certificate_type.name}（${currentTrace.certificate_type.code}）`
                    : '-'}
                </Descriptions.Item>
                <Descriptions.Item label="发证机构">
                  {currentTrace.certificate_type?.issuing_authority || currentTrace.certificate.issuing_authority || '-'}
                </Descriptions.Item>
              </Descriptions>
            </ProCard>

            <ProCard title="源文件与 AI 识别">
              {currentTrace.source_document ? (
                <Descriptions column={1} size="small">
                  <Descriptions.Item label="文件名">
                    {currentTrace.source_document.original_filename}
                  </Descriptions.Item>
                  <Descriptions.Item label="文件状态">
                    {documentStatusLabel(currentTrace.source_document.status)}
                  </Descriptions.Item>
                  <Descriptions.Item label="对象 Key">{currentTrace.source_document.storage_key}</Descriptions.Item>
                  <Descriptions.Item label="SHA256">{currentTrace.source_document.sha256 || '-'}</Descriptions.Item>
                  <Descriptions.Item label="失败原因">
                    {currentTrace.source_document.failure_reason || '-'}
                  </Descriptions.Item>
                </Descriptions>
              ) : (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有关联源文件" />
              )}
              <Collapse
                style={{ marginTop: 12 }}
                items={currentTrace.ai_results.map((result, index) => ({
                  key: result.id,
                  label: `AI 结果 ${index + 1}：${result.model_name || result.id}`,
                  children: (
                    <Typography.Paragraph copyable style={{ whiteSpace: 'pre-wrap' }}>
                      {traceValue(result.output_json)}
                    </Typography.Paragraph>
                  ),
                }))}
              />
            </ProCard>

            <ProCard title="复核、提醒与反馈">
              <Collapse
                items={[
                  {
                    key: 'reviews',
                    label: `复核任务（${currentTrace.review_tasks.length}）`,
                    children:
                      currentTrace.review_tasks.length > 0 ? (
                        <Timeline
                          items={currentTrace.review_tasks.map((task) => ({
                            content: `${reviewStatusLabel(task.status)} / ${task.reviewed_by || '未复核'} / ${
                              task.reviewed_at || task.created_at
                            }`,
                          }))}
                        />
                      ) : (
                        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无复核任务" />
                      ),
                  },
                  {
                    key: 'reminders',
                    label: `提醒任务（${currentTrace.reminder_tasks.length}）`,
                    children:
                      currentTrace.reminder_tasks.length > 0 ? (
                        <Timeline
                          items={currentTrace.reminder_tasks.map((task) => ({
                            content: `${reminderStatusLabel(task.status)} / 触发 ${task.trigger_date} / 截止 ${
                              task.due_date || '-'
                            }`,
                          }))}
                        />
                      ) : (
                        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无提醒任务" />
                      ),
                  },
                  {
                    key: 'feedback',
                    label: `反馈记录（${currentTrace.feedback_items.length}）`,
                    children:
                      currentTrace.feedback_items.length > 0 ? (
                        <Timeline
                          items={currentTrace.feedback_items.map((feedback) => ({
                            content: `${feedbackStatusLabel(feedback.status)} / ${feedback.created_by} / ${
                              feedback.content || '-'
                            }`,
                          }))}
                        />
                      ) : (
                        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无反馈记录" />
                      ),
                  },
                ]}
              />
            </ProCard>

            <ProCard title="审计摘要">
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
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="请选择一条持证记录查看追溯链路" />
        )}
      </Drawer>
    </PageContainer>
  );
}
