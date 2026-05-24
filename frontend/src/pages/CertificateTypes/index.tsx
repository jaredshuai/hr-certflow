import {
  ModalForm,
  PageContainer,
  ProFormDigit,
  ProFormSwitch,
  ProFormText,
  ProFormTextArea,
  ProTable,
  type ActionType,
  type ProColumns,
} from '@ant-design/pro-components';
import { UploadOutlined } from '@ant-design/icons';
import { Alert, Button, Modal, Table, Upload } from 'antd';
import type { UploadProps } from 'antd';
import { useRef, useState } from 'react';

import { createResource, pageResource, updateResource, uploadResource } from '@/services/api';
import type { CertificateType } from '@/types/domain';
import { emptyTableText } from '@/utils/emptyStates';
import { forceManualReviewValueEnum } from '@/utils/displayLabels';
import { message } from '@/utils/messageApi';
import { downloadCsv } from '@/utils/download';

interface CertificateTypeFormValues {
  code?: string;
  name?: string;
  issuing_authority?: string;
  default_validity_months?: number;
  force_manual_review?: boolean;
  description?: string;
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

export default function CertificateTypesPage() {
  const actionRef = useRef<ActionType>();
  const lastSearchParamsRef = useRef<Record<string, unknown>>({});
  const [open, setOpen] = useState(false);
  const [currentType, setCurrentType] = useState<CertificateType>();
  const [loadError, setLoadError] = useState<string>();
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState<CertificateTypeImportResult>();

  function openCreate() {
    setCurrentType(undefined);
    setOpen(true);
  }

  function openEdit(record: CertificateType) {
    setCurrentType(record);
    setOpen(true);
  }

  async function handleFinish(values: CertificateTypeFormValues): Promise<boolean> {
    const payload = {
      code: values.code?.trim(),
      name: values.name?.trim(),
      issuing_authority: optionalText(values.issuing_authority),
      default_validity_months: values.default_validity_months,
      force_manual_review: values.force_manual_review ?? true,
      description: optionalText(values.description),
    };

    try {
      if (currentType) {
        await updateResource<CertificateType, Omit<typeof payload, 'code'>>(`/certificate-types/${currentType.id}`, {
          name: payload.name,
          issuing_authority: payload.issuing_authority,
          default_validity_months: payload.default_validity_months,
          force_manual_review: payload.force_manual_review,
          description: payload.description,
        });
        message.success('证书类型已更新');
      } else {
        await createResource<CertificateType, typeof payload>('/certificate-types', payload);
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
      width: 100,
      render: (_, record) => (
        <Button type="link" size="small" onClick={() => openEdit(record)}>
          编辑
        </Button>
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
        initialValues={
          currentType
            ? {
                code: currentType.code,
                name: currentType.name,
                issuing_authority: currentType.issuing_authority,
                default_validity_months: currentType.default_validity_months,
                force_manual_review: currentType.force_manual_review,
                description: currentType.description,
              }
            : { force_manual_review: true }
        }
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
        <ProFormSwitch name="force_manual_review" label="强制复核" />
        <ProFormTextArea name="description" label="说明" />
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
              message={`共处理 ${importResult.total} 行，新增 ${importResult.created} 项，更新 ${importResult.updated} 项，失败 ${importResult.failed} 行`}
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
    </PageContainer>
  );
}
