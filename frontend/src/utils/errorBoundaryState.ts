// 本文件不引用任何其它模块，便于 tests/ 下用 node --test 直接运行。

export const DEFAULT_BOUNDARY_MESSAGE = '页面渲染出错，请重试。';

const UNUSABLE_MESSAGE = '[object Object]';

export interface ErrorBoundaryState {
  hasError: boolean;
  message: string;
}

export const initialErrorBoundaryState: ErrorBoundaryState = {
  hasError: false,
  message: '',
};

function usableMessage(value: string): string | undefined {
  const message = value.trim();
  return message && message !== UNUSABLE_MESSAGE ? message : undefined;
}

/** 从任意抛出物里取一条可读信息；拿不到时用固定文案，绝不把 `[object Object]` 给用户看。 */
export function boundaryMessage(error: unknown): string {
  if (error instanceof Error) return usableMessage(error.message) ?? DEFAULT_BOUNDARY_MESSAGE;
  if (typeof error === 'string') return usableMessage(error) ?? DEFAULT_BOUNDARY_MESSAGE;
  return DEFAULT_BOUNDARY_MESSAGE;
}

/** React ErrorBoundary 的 `getDerivedStateFromError`：只记录状态，不在渲染期做副作用。 */
export function errorBoundaryStateFromError(error: unknown): ErrorBoundaryState {
  return { hasError: true, message: boundaryMessage(error) };
}
