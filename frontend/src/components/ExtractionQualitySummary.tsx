import { Alert, Space, Tag, Typography } from 'antd';
import { useMemo } from 'react';

const requiredFields = ['holder_name', 'certificate_name', 'certificate_no'] as const;
const dateFields = ['issue_date', 'valid_from', 'valid_to', 'review_date'] as const;

const fieldLabels: Record<string, string> = {
  holder_name: '持证人',
  certificate_name: '证书名',
  certificate_no: '证书编号',
  issue_date: '发证日期',
  valid_from: '有效开始',
  valid_to: '有效截止',
  review_date: '复审日期',
};

function hasValue(value: unknown): boolean {
  if (value === null || value === undefined) return false;
  if (typeof value === 'string') return value.trim().length > 0;
  if (Array.isArray(value)) return value.length > 0;
  return true;
}

export function outputText(output: Record<string, unknown> | undefined, key: string): string | undefined {
  const value = output?.[key];
  return typeof value === 'string' && value.trim() ? value : undefined;
}

export function extractionSuspiciousPoints(output: Record<string, unknown> | undefined): string[] {
  const value = output?.suspicious_points;
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === 'string' && item.trim().length > 0);
}

export function buildExtractionQuality(output: Record<string, unknown> | undefined) {
  const missingFields = requiredFields.filter((field) => !hasValue(output?.[field]));
  const presentDateFields = dateFields.filter((field) => hasValue(output?.[field]));
  const missingDateGroup = presentDateFields.length === 0;
  const suspiciousPoints = extractionSuspiciousPoints(output);
  const missingLabels = [
    ...missingFields.map((field) => fieldLabels[field]),
    ...(missingDateGroup ? ['至少一个日期'] : []),
  ];

  return {
    complete: missingLabels.length === 0,
    missingLabels,
    presentDateLabels: presentDateFields.map((field) => fieldLabels[field]),
    suspiciousPoints,
  };
}

interface ExtractionQualitySummaryProps {
  output?: Record<string, unknown>;
  compact?: boolean;
}

export function ExtractionQualitySummary({ output, compact = false }: ExtractionQualitySummaryProps) {
  const quality = useMemo(() => buildExtractionQuality(output), [output]);

  if (!output) {
    return <Tag>未识别</Tag>;
  }

  return (
    <Space direction="vertical" size={compact ? 4 : 8} style={{ width: '100%' }}>
      <Space wrap size={[4, 4]}>
        <Tag color={quality.complete ? 'green' : 'gold'}>{quality.complete ? '字段完整' : '待补字段'}</Tag>
        {quality.missingLabels.map((label) => (
          <Tag key={label} color="red">
            缺 {label}
          </Tag>
        ))}
        {quality.presentDateLabels.map((label) => (
          <Tag key={label} color="blue">
            {label}
          </Tag>
        ))}
      </Space>
      {quality.suspiciousPoints.length > 0 ? (
        compact ? (
          <Typography.Text type="warning" ellipsis>
            {quality.suspiciousPoints.join('；')}
          </Typography.Text>
        ) : (
          <Alert
            type="warning"
            showIcon
            message="识别疑点"
            description={quality.suspiciousPoints.join('；')}
          />
        )
      ) : null}
    </Space>
  );
}
