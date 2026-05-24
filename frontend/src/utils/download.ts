import { request } from '@umijs/max';
import type { AxiosResponse } from '@umijs/max';

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
  const response = (await request<Blob>(url, {
    params,
    getResponse: true,
    responseType: 'blob',
  })) as AxiosResponse<Blob>;
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
