// 本文件不引用任何其它模块，便于 tests/ 下用 node --test 直接运行。

export function buildRequestId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

/**
 * 前端只附带 X-Request-ID。身份由网关或后端认定，前端不写、也不透传任何 X-HR-Actor* 头。
 */
export function buildRequestHeaders(
  headers: Record<string, unknown> | undefined,
  requestId: string,
): Record<string, unknown> {
  const next: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(headers || {})) {
    if (!key.toLowerCase().startsWith('x-hr-actor')) next[key] = value;
  }
  next['X-Request-ID'] = requestId;
  return next;
}
