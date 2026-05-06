import type { RequestConfig, RunTimeLayoutConfig } from '@umijs/max';

function resolveApiBasePath(): string {
  if (process.env.API_BASE_PATH) {
    return process.env.API_BASE_PATH;
  }

  if (typeof window === 'undefined') {
    return '/api/v1';
  }

  const match = window.location.pathname.match(/^\/(hr-certflow(?:-dev|-release)?)(\/|$)/);
  if (!match) {
    return '/api/v1';
  }

  return `/${match[1]}/api/v1`;
}

export const request: RequestConfig = {
  baseURL: resolveApiBasePath(),
  timeout: 30000,
  errorConfig: {
    errorThrower: (response: any) => {
      const error: any = new Error(response?.data?.detail || 'Request failed');
      error.name = 'BizError';
      error.info = response;
      throw error;
    },
  },
};

export const layout: RunTimeLayoutConfig = () => ({
  title: 'HR CertFlow',
  layout: 'mix',
  navTheme: 'light',
  contentWidth: 'Fluid',
  fixedHeader: true,
  fixSiderbar: true,
  token: {
    header: {
      colorBgHeader: '#ffffff',
    },
    sider: {
      colorMenuBackground: '#f7f8fa',
      colorTextMenuSelected: '#1f5f5b',
      colorBgMenuItemSelected: '#e6f2ef',
    },
  },
});
