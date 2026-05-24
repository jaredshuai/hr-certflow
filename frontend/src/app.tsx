import { ProConfigProvider, zhCNIntl } from '@ant-design/pro-components';
import type { RequestConfig, RunTimeLayoutConfig } from '@umijs/max';
import { App as AntdApp, ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import type { ThemeConfig } from 'antd';
import 'dayjs/locale/zh-cn';
import type { ReactNode } from 'react';

import { CurrentOperator } from '@/components/CurrentOperator';
import { setMessageInstance } from '@/utils/messageApi';
import { buildRequestId, getCurrentOperator } from '@/utils/operatorContext';

const appTheme: ThemeConfig = {
  cssVar: true,
  token: {
    colorPrimary: '#00684a',
    colorSuccess: '#389e0d',
    colorWarning: '#d48806',
    colorError: '#cf1322',
    colorInfo: '#1677ff',
    colorTextBase: '#001e2b',
    colorBgBase: '#f7faf9',
    colorBgLayout: '#f7faf9',
    colorBgContainer: '#ffffff',
    colorBgElevated: '#ffffff',
    colorBorder: '#dfe8e5',
    colorBorderSecondary: '#edf2f0',
    colorLink: '#00684a',
    colorLinkHover: '#00855d',
    borderRadius: 8,
    borderRadiusLG: 12,
    borderRadiusSM: 6,
    fontFamily:
      '"Alibaba PuHuiTi 3.0", "PingFang SC", "Microsoft YaHei", "Noto Sans SC", sans-serif',
    controlHeight: 40,
    controlHeightSM: 28,
  },
  components: {
    Button: {
      borderRadius: 999,
      primaryShadow: '0 8px 18px rgba(0, 104, 74, 0.16)',
    },
    Card: {
      borderRadiusLG: 12,
      colorBorderSecondary: '#dfe8e5',
    },
    Modal: {
      borderRadiusLG: 12,
    },
    Table: {
      borderColor: '#edf2f0',
      headerBg: '#f1f6f4',
      headerColor: '#003d3a',
      headerSplitColor: '#dfe8e5',
      rowHoverBg: '#f7fbf9',
    },
    Tag: {
      borderRadiusSM: 999,
      defaultBg: '#f7faf9',
      defaultColor: '#003d3a',
    },
  },
};

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
  requestInterceptors: [
    (config) => {
      const operator = getCurrentOperator();
      const headers = {
        ...(config.headers || {}),
        'X-Request-ID': buildRequestId(),
        ...(operator ? { 'X-HR-Actor': operator } : {}),
      };
      return { ...config, headers };
    },
  ],
  errorConfig: {
    errorThrower: (response: any) => {
      const error: any = new Error(response?.data?.detail || '请求失败');
      error.name = 'BizError';
      error.info = response;
      throw error;
    },
  },
};

export const layout: RunTimeLayoutConfig = () => ({
  title: '人力证书管理',
  layout: 'mix',
  navTheme: 'light',
  contentWidth: 'Fluid',
  fixedHeader: true,
  fixSiderbar: true,
  token: {
    header: {
      colorBgHeader: '#ffffff',
      colorHeaderTitle: '#001e2b',
    },
    sider: {
      colorMenuBackground: '#f1f6f4',
      colorTextMenu: '#31524d',
      colorTextMenuActive: '#003d3a',
      colorTextMenuSelected: '#1f5f5b',
      colorBgMenuItemSelected: '#dff6e8',
      colorBgMenuItemHover: '#e8f3ef',
    },
  },
  actionsRender: () => [<CurrentOperator key="current-operator" />],
});

function MessageInstaller() {
  const { message } = AntdApp.useApp();
  setMessageInstance(message);
  return null;
}

export function rootContainer(container: ReactNode) {
  return (
    <ConfigProvider locale={zhCN} theme={appTheme}>
      <AntdApp>
        <MessageInstaller />
        <ProConfigProvider intl={zhCNIntl}>{container}</ProConfigProvider>
      </AntdApp>
    </ConfigProvider>
  );
}
