import { request } from '@umijs/max';
import type { AxiosResponse } from '@umijs/max';

import { normalizeBlobError } from '@/utils/apiErrors';

function buildFilename(response: AxiosResponse<Blob>, fallback: string): string {
  const disposition = response.headers['content-disposition'];
  const match = disposition?.match(/filename="?([^"]+)"?/i);
  return match?.[1] || fallback;
}

export async function downloadCsv(
  url: string,
  params: Record<string, unknown>,
  fallbackFilename: string,
): Promise<void> {
  let response: AxiosResponse<Blob>;
  try {
    response = (await request<Blob>(url, {
      params,
      getResponse: true,
      responseType: 'blob',
    })) as AxiosResponse<Blob>;
  } catch (error) {
    // blob 响应的错误体是 Blob，先解码成可读取 detail 的错误再抛给调用方，
    // 否则 apiErrorMessage 拿不到 {detail:{code}}，导出 403 会裸显英文 axios 文案。
    throw await normalizeBlobError(error);
  }
  const blob = response.data;
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = objectUrl;
  anchor.download = buildFilename(response, fallbackFilename);
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(objectUrl);
}
