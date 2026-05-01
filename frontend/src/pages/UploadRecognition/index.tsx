import { InboxOutlined, RobotOutlined, SaveOutlined } from '@ant-design/icons';
import { PageContainer, ProCard, ProDescriptions, ProForm, ProFormDatePicker, ProFormText } from '@ant-design/pro-components';
import { Button, Divider, Space, Tag, Upload, message } from 'antd';

export default function UploadRecognitionPage() {
  return (
    <PageContainer title="上传识别">
      <div className="certflow-upload-grid">
        <ProCard title="证书原件" bordered>
          <Upload.Dragger
            multiple={false}
            beforeUpload={() => {
              message.info('已选择文件，等待上传');
              return false;
            }}
          >
            <p className="ant-upload-drag-icon">
              <InboxOutlined />
            </p>
            <p className="ant-upload-text">拖拽证书图片或 PDF 到这里</p>
            <p className="ant-upload-hint">支持证书原图、扫描件、PDF 文件</p>
          </Upload.Dragger>

          <Divider />

          <ProDescriptions
            size="small"
            column={1}
            dataSource={{
              status: 'PENDING_REVIEW',
              file: '未上传',
              ai: '未识别',
            }}
            columns={[
              { title: '状态', dataIndex: 'status', render: (text) => <Tag color="blue">{text}</Tag> },
              { title: '当前文件', dataIndex: 'file' },
              { title: '识别结果', dataIndex: 'ai' },
            ]}
          />
        </ProCard>

        <ProCard
          title="AI 预填与人工确认"
          bordered
          extra={
            <Space>
              <Button icon={<RobotOutlined />}>重新识别</Button>
              <Button type="primary" icon={<SaveOutlined />}>
                确认为正式证书
              </Button>
            </Space>
          }
        >
          <ProForm submitter={false} layout="horizontal" labelCol={{ span: 5 }}>
            <ProFormText name="holder_name" label="持证人" placeholder="AI 识别姓名" />
            <ProFormText name="certificate_name" label="证书名称" placeholder="匹配证书类型" />
            <ProFormText name="certificate_no" label="证书编号" />
            <ProFormText name="issuing_authority" label="发证机构" />
            <ProFormDatePicker name="issue_date" label="发证日期" />
            <ProFormDatePicker name="valid_from" label="有效开始" />
            <ProFormDatePicker name="valid_to" label="有效截止" />
            <ProFormDatePicker name="review_date" label="复审日期" />
          </ProForm>
        </ProCard>
      </div>
    </PageContainer>
  );
}
