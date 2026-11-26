type ApiErrorInfo = {
  data?: {
    detail?: unknown;
  };
  response?: {
    status?: number;
    data?: {
      detail?: unknown;
    };
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

/** `detail` 可能是字符串（业务错误）或对象（jxccs-access 的 `{code, loginUrl}`）。 */
function errorDetail(error: unknown): unknown {
  const info = errorInfo(error);
  return info?.data?.detail ?? info?.response?.data?.detail ?? axiosResponseDetail(error);
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
  return typeof code === 'string' && Object.prototype.hasOwnProperty.call(ACCESS_ERROR_MESSAGES, code)
    ? ACCESS_ERROR_MESSAGES[code]
    : undefined;
}

export function apiErrorMessage(error: unknown, fallback: string): string {
  const detail = errorDetail(error);
  if (typeof detail === 'string' && detail.trim()) return detail;
  const accessMessage = accessErrorMessage(detail);
  if (accessMessage) return accessMessage;
  if (error instanceof Error && error.message.trim()) return error.message;
  return fallback;
}

/**
 * 后端 401 body 里的 `detail.loginUrl`（jxccs-access 登录入口）。
 *
 * 前端据此跳转而不是写死 `/oauth2/start` 或 `/auth/login`：登录路径属于部署侧
 * 契约，换了网关/前缀时不应再让浏览器落到一个不存在的路径上（那会白屏）。
 */
export function apiErrorLoginUrl(error: unknown): string | undefined {
  const detail = errorDetail(error);
  if (!detail || typeof detail !== 'object') return undefined;
  const loginUrl = (detail as { loginUrl?: unknown }).loginUrl;
  return typeof loginUrl === 'string' && loginUrl.trim() ? loginUrl.trim() : undefined;
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

// 登录态失效的两种来源：中间件无会话（UNAUTHENTICATED）与授权中心判定会话过期
// （SESSION_EXPIRED）；两者都必须交给登录跳转，不能渲染成页面业务错误。
const AUTH_ERROR_CODES = new Set(['UNAUTHENTICATED', 'SESSION_EXPIRED']);

/**
 * 是否为「登录态失效」错误。
 *
 * 页面加载/提交收到这类错误时不应展示红框或业务 toast（那是把登录问题误报成数据
 * 问题，且会在跳转登录前闪一下）；统一由全局鉴权闸门与 `handleAuthError` 接管。
 */
export function isAuthError(error: unknown): boolean {
  if (apiErrorStatus(error) === 401) return true;
  const detail = errorDetail(error);
  if (!detail || typeof detail !== 'object') return false;
  const code = (detail as { code?: unknown }).code;
  return typeof code === 'string' && AUTH_ERROR_CODES.has(code);
}

export interface LoadFailureState<T> {
  data: T;
  loadError: string;
}

/**
 * 页面加载失败时的完整状态：登录态失效返回 null，页面保持原状（不清零、不报错）；
 * 其他失败退回 `empty` 数据并给出提示文案。工作台等页面直接使用这个结果，
 * 单测因此覆盖的是页面真正执行的同一条路径。
 */
export function loadFailureState<T>(error: unknown, fallback: string, empty: T): LoadFailureState<T> | null {
  if (isAuthError(error)) return null;
  return { data: empty, loadError: apiErrorMessage(error, fallback) };
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
