const OPERATOR_STORAGE_KEY = 'hr-certflow.operator';

export function getCurrentOperator(): string | undefined {
  if (typeof window === 'undefined') return undefined;
  const value = window.localStorage.getItem(OPERATOR_STORAGE_KEY)?.trim();
  return value || undefined;
}

export function setCurrentOperator(value: string): void {
  if (typeof window === 'undefined') return;
  const trimmed = value.trim();
  if (trimmed) {
    window.localStorage.setItem(OPERATOR_STORAGE_KEY, trimmed);
  } else {
    window.localStorage.removeItem(OPERATOR_STORAGE_KEY);
  }
}

export function encodeOperatorHeader(value: string): string {
  return encodeURIComponent(value.trim());
}

export function buildRequestId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}
