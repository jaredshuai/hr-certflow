import assert from 'node:assert/strict';
import { test } from 'node:test';

// ESM 静态导入在模块体执行前的链接阶段就完成解析，因此 '@umijs/max' 的 stub
// 注册（register-umijs-loader）生效后，src 模块必须用顶层 await 动态导入。
import './register-umijs-loader.mjs';
const { setRequestImpl, resetRequestImpl } = await import('./helpers/umijs-max-stub.mjs');
const { downloadCsv } = await import('../src/utils/download.ts');
const { apiErrorMessage, apiErrorStatus, tableRequestFailure } = await import('../src/utils/apiErrors.ts');
function blobAxiosError(status, payload) {
  const error = new Error(`Request failed with status code ${status}`);
  error.name = 'AxiosError';
  error.response = {
    status,
    data: new Blob([typeof payload === 'string' ? payload : JSON.stringify(payload)], { type: 'application/json' }),
  };
  return error;
}

test('downloadCsv 导出失败走 blob 解码后映射 403 中文授权提示（真接线）', async () => {
  // 若 downloadCsv 删掉 normalizeBlobError 调用，detail 留在 Blob 里读不出来，
  // 下面的断言立即失败——这里覆盖的是生产代码的真实导出接线。
  setRequestImpl(async () => {
    throw blobAxiosError(403, { detail: { code: 'FORBIDDEN' } });
  });
  try {
    await assert.rejects(
      downloadCsv('/certificates/export.csv', {}, 'employee-certificates.csv'),
      (error) => {
        assert.equal(tableRequestFailure(error, '持证记录导出失败'), '没有执行此操作的权限，请联系管理员授权。');
        assert.ok(!apiErrorMessage(error, '').includes('Request failed with status code'), '不得展示 axios 英文原文');
        return true;
      },
    );
  } finally {
    resetRequestImpl();
  }
});

test('downloadCsv 字符串 detail 业务错误解码后原样展示', async () => {
  setRequestImpl(async () => {
    throw blobAxiosError(422, { detail: '导出筛选范围过大' });
  });
  try {
    await assert.rejects(downloadCsv('/certificates/export.csv', {}, 'x.csv'), (error) => {
      assert.equal(apiErrorMessage(error, '导出失败'), '导出筛选范围过大');
      return true;
    });
  } finally {
    resetRequestImpl();
  }
});

test('downloadCsv 非 JSON 错误体（网关 text/plain）原样透传、文案走中文兜底', async () => {
  setRequestImpl(async () => {
    const error = blobAxiosError(403, 'Forbidden');
    error.response.data = new Blob(['Forbidden'], { type: 'text/plain' });
    throw error;
  });
  try {
    await assert.rejects(downloadCsv('/certificates/export.csv', {}, 'x.csv'), (error) => {
      assert.equal(apiErrorStatus(error), 403);
      assert.equal(apiErrorMessage(error, '持证记录导出失败'), '持证记录导出失败');
      return true;
    });
  } finally {
    resetRequestImpl();
  }
});

test('downloadCsv 非 blob 错误不做包装、原样透传', async () => {
  const plain = new Error('Network Error');
  plain.name = 'AxiosError';
  plain.response = { status: 0, data: undefined };
  setRequestImpl(async () => {
    throw plain;
  });
  try {
    await assert.rejects(downloadCsv('/certificates/export.csv', {}, 'x.csv'), (error) => {
      assert.equal(error, plain);
      return true;
    });
  } finally {
    resetRequestImpl();
  }
});
