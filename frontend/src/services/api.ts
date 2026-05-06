import { request } from '@umijs/max';

export async function listResource<T>(url: string): Promise<T[]> {
  return request<T[]>(url);
}

export async function createResource<T, P>(url: string, data: P): Promise<T> {
  return request<T>(url, {
    method: 'POST',
    data,
  });
}

export async function postResource<T, P = unknown>(url: string, data?: P): Promise<T> {
  return request<T>(url, {
    method: 'POST',
    data,
  });
}
