import {
  PageContainer,
  ProForm,
  ProFormDigit,
  ProFormSwitch,
  ProFormText,
  ProFormTextArea,
  ProTable,
  type ActionType,
  type ProColumns,
} from '@ant-design/pro-components';
import { Button, Form, Modal, Tag, message } from 'antd';
import { useRef, useState } from 'react';

import { createResource, listResource, updateResource } from '@/services/api';
import type { CertificateType } from '@/types/domain';

interface CertificateTypeFormValues {
  code?: string;
  name?: string;
  issuing_authority?: string;
  default_validity_months?: number;
  force_manual_review?: boolean;
  description?: string;
}

function optionalText(value: string | undefined): string | undefined {
  const trimmed = value?.trim();
  return trimmed || undefined;
}

export default function CertificateTypesPage() {
  const actionRef = useRef<ActionType>();
  const [form] = Form.useForm<CertificateTypeFormValues>();
  const [modalOpen, setModalOpen] = useState(false);
  const [currentType, setCurrentType] = useState<CertificateType>();
  const [submitting, setSubmitting] = useState(false);

  function openCreateModal() {
    setCurrentType(undefined);
    form.resetFields();
    form.setFieldsValue({ force_manual_review: true });
    setModalOpen(true);
  }

  function openEditModal(record: CertificateType) {
    setCurrentType(record);
    form.setFieldsValue(record);
    setModalOpen(true);
  }

  async function submitCertificateType() {
    const values = await form.validateFields();
    const payload = {
      code: values.code?.trim(),
      name: values.name?.trim(),
      issuing_authority: optionalText(values.issuing_authority),
      default_validity_months: values.default_validity_months,
      force_manual_review: values.force_manual_review ?? true,
      description: optionalText(values.description),
    };

    setSubmitting(true);
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
      setModalOpen(false);
      actionRef.current?.reload();
    } catch (error) {
      message.error(error instanceof Error ? error.message : '证书类型保存失败');
    } finally {
      setSubmitting(false);
    }
  }

  const columns: ProColumns<CertificateType>[] = [
    { title: '编码', dataIndex: 'code', width: 140 },
    { title: '证书类型', dataIndex: 'name' },
    { title: '发证机构', dataIndex: 'issuing_authority' },
    { title: '默认有效期(月)', dataIndex: 'default_validity_months', valueType: 'digit', width: 140 },
    {
      title: '强制复核',
      dataIndex: 'force_manual_review',
      valueType: 'select',
      valueEnum: {
        true: { text: '是' },
        false: { text: '否' },
      },
      render: (_, record) => <Tag color={record.force_manual_review ? 'gold' : 'green'}>{record.force_manual_review ? '是' : '否'}</Tag>,
    },
    {
      title: '操作',
      valueType: 'option',
      width: 100,
      render: (_, record) => (
        <Button type="link" size="small" onClick={() => openEditModal(record)}>
          编辑
        </Button>
      ),
    },
  ];

  return (
    <PageContainer title="证书类型管理">
      <ProTable<CertificateType>
        actionRef={actionRef}
        rowKey="id"
        columns={columns}
        request={async () => ({
          data: await listResource<CertificateType>('/certificate-types'),
          success: true,
        })}
        locale={{ emptyText: '暂无证书类型，请先新增可管理的证书类型' }}
        toolbar={{
          title: '证书类型',
          actions: [
            <Button key="create" type="primary" onClick={openCreateModal}>
              新增证书类型
            </Button>,
          ],
        }}
        search={{ labelWidth: 96 }}
      />

      <Modal
        title={currentType ? '编辑证书类型' : '新增证书类型'}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={() => void submitCertificateType()}
        confirmLoading={submitting}
        destroyOnClose
        width={680}
      >
        <ProForm form={form} submitter={false} layout="horizontal" labelCol={{ span: 6 }}>
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
        </ProForm>
      </Modal>
    </PageContainer>
  );
}
