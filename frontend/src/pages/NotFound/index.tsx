import { PageContainer } from '@ant-design/pro-components';
import { history } from '@umijs/max';
import { Button, Result } from 'antd';

export default function NotFoundPage() {
  return (
    <PageContainer title={false}>
      <Result
        status="404"
        title="页面不存在"
        subTitle="当前地址没有对应的功能页面。请从左侧导航进入业务模块。"
        extra={
          <Button type="primary" onClick={() => history.push('/dashboard')}>
            返回工作台
          </Button>
        }
      />
    </PageContainer>
  );
}
