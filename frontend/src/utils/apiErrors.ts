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

function axiosResponseDetail(error: unknown): unknown {
  if (!error || typeof error !== 'object' || !('response' in error)) return undefined;
  const data = (error as { response?: { data?: unknown } }).response?.data;
  return data && typeof data === 'object' ? (data as { detail?: unknown }).detail : undefined;
}

// jxccs-access（dev 登录/会话/授权）返回 {detail: {code}}，按固定 code 给出中文提示。
const ACCESS_ERROR_MESSAGES: Record<string, string> = {
  UNAUTHENTICATED: '登录已失效，请重新登录。',
  SESSION_EXPIRED: '登录已失效，请重新登录。',
  FORBIDDEN: '没有执行此操作的权限，请联系管理员授权。',
  IDENTITY_NOT_ELIGIBLE: '当前账号不可使用本系统，请联系管理员。',
  CSRF_TOKEN_INVALID: '页面已过期，请刷新后重试。',
  DEPENDENCY_UNAVAILABLE: '权限服务暂时不可用，请稍后重试。',
};

function accessErrorMessage(detail: unknown): string | undefined {
  if (!detail || typeof detail !== 'object') return undefined;
  const code = (detail as { code?: unknown }).code;
  return typeof code === 'string' ? ACCESS_ERROR_MESSAGES[code] : undefined;
}

export function apiErrorMessage(error: unknown, fallback: string): string {
  const detail = errorInfo(error)?.data?.detail ?? axiosResponseDetail(error);
  if (typeof detail === 'string' && detail.trim()) return detail;
  const accessMessage = accessErrorMessage(detail);
  if (accessMessage) return accessMessage;
  if (error instanceof Error && error.message.trim()) return error.message;
  return fallback;
}

// umi request 对 HTTP 非 2xx 抛 AxiosError（状态在 error.response.status），
// errorThrower 抛的 BizError 状态在 error.info.response.status / error.info.status。
function axiosResponseStatus(error: unknown): number | undefined {
  if (!error || typeof error !== 'object' || !('response' in error)) return undefined;
  const status = (error as { response?: { status?: unknown } }).response?.status;
  return typeof status === 'number' ? status : undefined;
}

export function apiErrorStatus(error: unknown): number | undefined {
  const info = errorInfo(error);
  return axiosResponseStatus(error) ?? info?.response?.status ?? info?.status;
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
