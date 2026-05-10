import { Empty } from 'antd';

export function emptyTableText(description: string) {
  return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={description} />;
}
