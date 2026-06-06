export function parseDaysBeforeExpiryText(value: string | undefined): number[] {
  const days = (value || '')
    .split(/[,\s，]+/)
    .map((item) => item.trim())
    .filter(Boolean)
    .map((item) => Number(item));
  if (days.length === 0 || days.some((item) => !Number.isInteger(item) || item < 0)) {
    throw new Error('提前提醒天数必须是非负整数，可用逗号分隔');
  }
  return [...new Set(days)].sort((left, right) => right - left);
}

export function formatDaysBeforeExpiryText(value: number[] | undefined): string {
  return value && value.length > 0 ? value.join(',') : '60,30,7';
}
