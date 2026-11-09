// 本文件不引用任何其它模块，便于 tests/ 下用 node --test 直接运行。

export function buildRequestId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

const UNSAFE_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

let csrfToken: string | undefined;

/** jxccs-access 会话的 CSRF token（来自 GET /me）；release 网关模式下没有，保持 undefined。 */
export function setCsrfToken(token: string | null | undefined) {
  csrfToken = token || undefined;
}

/**
 * 前端只附带 X-Request-ID；有 jxccs-access 会话时写请求再附带 X-CSRF-Token。
 * 身份由网关或后端认定，前端不写、也不透传任何 X-HR-Actor* 头。
 */
export function buildRequestHeaders(
  headers: Record<string, unknown> | undefined,
  requestId: string,
  method?: string,
): Record<string, unknown> {
  const next: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(headers || {})) {
    const lower = key.toLowerCase();
    if (!lower.startsWith('x-hr-actor') && lower !== 'x-csrf-token') next[key] = value;
  }
  next['X-Request-ID'] = requestId;
  if (csrfToken && method && UNSAFE_METHODS.has(method.toUpperCase())) next['X-CSRF-Token'] = csrfToken;
  return next;
}
