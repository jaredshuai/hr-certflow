import { message as staticMessage } from 'antd';

type ContentLike = Parameters<typeof staticMessage.success>[0];

interface MinimalMessageApi {
  success: (content: ContentLike) => unknown;
  error: (content: ContentLike) => unknown;
  warning: (content: ContentLike) => unknown;
  info: (content: ContentLike) => unknown;
}

let instance: MinimalMessageApi = {
  success: (content) => staticMessage.success(content),
  error: (content) => staticMessage.error(content),
  warning: (content) => staticMessage.warning(content),
  info: (content) => staticMessage.info(content),
};

export function setMessageInstance(api: MinimalMessageApi): void {
  instance = api;
}

export const message: MinimalMessageApi = {
  success: (content) => instance.success(content),
  error: (content) => instance.error(content),
  warning: (content) => instance.warning(content),
  info: (content) => instance.info(content),
};
