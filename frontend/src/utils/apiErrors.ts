type ApiErrorInfo = {
  data?: {
    detail?: unknown;
  };
  response?: {
    status?: number;
  };
  status?: number;
};

function errorInfo(error: unknown): ApiErrorInfo | undefined {
  if (!error || typeof error !== 'object' || !('info' in error)) return undefined;
  return (error as { info?: ApiErrorInfo }).info;
}

export function apiErrorMessage(error: unknown, fallback: string): string {
  const detail = errorInfo(error)?.data?.detail;
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (error instanceof Error && error.message.trim()) return error.message;
  return fallback;
}

export function apiErrorStatus(error: unknown): number | undefined {
  const info = errorInfo(error);
  return info?.response?.status ?? info?.status;
}

export function isReviewStaleActionError(error: unknown): boolean {
  const message = apiErrorMessage(error, '');
  const status = apiErrorStatus(error);
  const staleMessages = [
    'Review task has changed',
    'Review task is already closed',
    'Document is not pending review',
  ];
  return (status === undefined || status === 409) && staleMessages.some((item) => message.includes(item));
}

export function reviewStaleActionMessage(error: unknown): string {
  const message = apiErrorMessage(error, '复核任务状态已变化');
  if (message.includes('Review task has changed')) {
    return '复核任务已被其他操作人更新，请刷新队列后重新打开。';
  }
  if (message.includes('Review task is already closed')) {
    return '复核任务已关闭，当前操作不能继续，请刷新队列查看最新状态。';
  }
  if (message.includes('Document is not pending review')) {
    return '源文件已不处于待复核状态，请刷新队列查看最新状态。';
  }
  return `${message}，请刷新后重试。`;
}
