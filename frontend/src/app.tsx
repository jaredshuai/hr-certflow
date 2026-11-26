import { ProConfigProvider, zhCNIntl } from '@ant-design/pro-components';
import type { RequestConfig, RunTimeLayoutConfig } from '@umijs/max';
import { App as AntdApp, ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import type { ThemeConfig } from 'antd';
import 'dayjs/locale/zh-cn';
import type { ReactNode } from 'react';

import { AuthGate } from '@/components/AuthGate';
import { CurrentOperator } from '@/components/CurrentOperator';
import { ErrorBoundary } from '@/components/ErrorBoundary';
import { actorProvider } from '@/utils/actorProvider';
import { isAuthError } from '@/utils/apiErrors';
import { initGlitchtip } from '@/utils/glitchtip';
import { resolveAppBase } from '@/utils/loginRedirect';
import { setMessageInstance } from '@/utils/messageApi';
import { buildRequestHeaders, buildRequestId } from '@/utils/requestHeaders';

// 错误监控在应用渲染前最早期接线：glitchtip-config.js 已先于主 bundle 执行，
// 这里有 DSN 才初始化，未注入的环境完全静默、零副作用（Item #51）。
initGlitchtip();

const appTheme: ThemeConfig = {
  cssVar: true as any,
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

  const appBase = resolveAppBase(window.location.pathname);
  return appBase ? `${appBase}/api/v1` : '/api/v1';
}

export const request: RequestConfig = {
  baseURL: resolveApiBasePath(),
  timeout: 30000,
  requestInterceptors: [
    (config: any) => ({
      ...config,
      headers: buildRequestHeaders(config.headers, buildRequestId(), config.method),
    }),
  ],
  errorConfig: {
    errorThrower: (response: any) => {
      const error: any = new Error(response?.data?.detail || '请求失败');
      error.name = 'BizError';
      error.info = response;
      throw error;
    },
    // 401/会话失效不弹业务错误：工作台等页面在鉴权完成前已不会挂载；这里再兜一层
    // 会话中途过期（30 分钟空闲）的情况，统一交给 actorProvider 只跳一次登录。
    // 非登录错误保持原契约：由具体页面的 catch 决定是否提示（umi 本身没有默认
    // errorHandler，不配置时错误也只是 reject 给调用方），这里不重复弹 toast。
    errorHandler: (error: unknown) => {
      if (isAuthError(error)) {
        actorProvider.handleAuthError(error);
      }
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
  // 全局鉴权闸门：/me 未返回前不挂载业务页面，避免工作台抢跑发请求并把 401
  // 渲染成「数据加载失败」红框（Item #48）。
  childrenRender: (children) => <AuthGate>{children}</AuthGate>,
});

function MessageInstaller() {
  const { message } = AntdApp.useApp();
  setMessageInstance(message);
  return null;
}

export function rootContainer(container: ReactNode) {
  return (
    <ErrorBoundary>
      <ConfigProvider locale={zhCN} theme={appTheme}>
        <AntdApp>
          <MessageInstaller />
          <ProConfigProvider intl={zhCNIntl}>{container}</ProConfigProvider>
        </AntdApp>
      </ConfigProvider>
    </ErrorBoundary>
  );
}
