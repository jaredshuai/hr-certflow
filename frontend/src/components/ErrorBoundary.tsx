import { Component, type ErrorInfo, type ReactNode } from 'react';

import { errorBoundaryStateFromError } from '@/utils/errorBoundaryState';
import { reportErrorToGlitchtip } from '@/utils/glitchtip';

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
  message: string;
}

/**
 * 全站渲染兜底。
 *
 * 放在 `rootContainer` 最外层：任何页面组件在 render/lifecycle 抛错时，React 19 会
 * 卸载整棵组件树；没有边界时用户看到的是纯白页（本次 release 白屏事故的放大器）。
 * 这里改用不依赖 antd 的内联样式错误页，即使主题/组件库本身出错也能正常显示。
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { hasError: false, message: '' };

  static getDerivedStateFromError(error: unknown): ErrorBoundaryState {
    // 复用同一份实现，测试覆盖的就是生产行为。
    return errorBoundaryStateFromError(error);
  }

  componentDidCatch(error: unknown, info: ErrorInfo) {
    console.error('[hr-certflow] 页面渲染出错', error, info.componentStack);
    // 监控未启用（无 DSN 注入）时这是 no-op；componentStack 在 glitchtip.ts
    // 内收进 contexts.react 并走同一套脱敏规则。
    void reportErrorToGlitchtip(error, { componentStack: info.componentStack ?? undefined });
  }

  private handleReload = () => {
    window.location.reload();
  };

  render() {
    if (!this.state.hasError) {
      return this.props.children;
    }

    return (
      <div
        role="alert"
        style={{
          alignItems: 'center',
          background: '#f7faf9',
          color: '#001e2b',
          display: 'flex',
          flexDirection: 'column',
          fontFamily: '"PingFang SC", "Microsoft YaHei", "Noto Sans SC", sans-serif',
          gap: 12,
          justifyContent: 'center',
          minHeight: '100vh',
          padding: 24,
          textAlign: 'center',
        }}
      >
        <h1 style={{ fontSize: 22, fontWeight: 650, margin: 0 }}>页面出错</h1>
        <p style={{ color: '#31524d', margin: 0 }}>页面渲染出错，已阻止整页白屏。请重试；若持续出现，请联系管理员。</p>
        <p style={{ color: '#6b7f7a', fontSize: 13, margin: 0, maxWidth: 720, wordBreak: 'break-word' }}>
          错误信息：{this.state.message}
        </p>
        <button
          type="button"
          onClick={this.handleReload}
          style={{
            background: '#00684a',
            border: 'none',
            borderRadius: 999,
            color: '#fff',
            cursor: 'pointer',
            fontSize: 14,
            marginTop: 8,
            padding: '10px 24px',
          }}
        >
          重试
        </button>
      </div>
    );
  }
}
