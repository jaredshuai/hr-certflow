
export function encodeOperatorHeader(value: string): string {
  return encodeURIComponent(value.trim());
}

export function buildRequestId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}
