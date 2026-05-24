import { request } from '@umijs/max';

export interface PageResult<T> {
  data: T[];
  total: number;
}

export async function listResource<T>(url: string): Promise<T[]> {
  return request<T[]>(url);
}

export async function getResource<T>(url: string): Promise<T> {
  return request<T>(url);
}

export async function pageResource<T>(
  url: string,
  params?: Record<string, unknown>,
): Promise<PageResult<T>> {
  return request<PageResult<T>>(url, { params });
}

export async function createResource<T, P>(url: string, data: P): Promise<T> {
  return request<T>(url, {
    method: 'POST',
    data,
  });
}

export async function updateResource<T, P>(url: string, data: P): Promise<T> {
  return request<T>(url, {
    method: 'PATCH',
    data,
  });
}

export async function postResource<T, P = unknown>(url: string, data?: P): Promise<T> {
  return request<T>(url, {
    method: 'POST',
    data,
  });
}

export async function uploadResource<T>(url: string, data: FormData): Promise<T> {
  return request<T>(url, {
    method: 'POST',
    data,
  });
}
