import assert from 'node:assert/strict';
import { test } from 'node:test';

import { buildRequestHeaders } from '../src/utils/requestHeaders.ts';

test('requests carry only X-Request-ID and no identity headers', () => {
  const headers = buildRequestHeaders({ Accept: 'application/json' }, 'req-1');

  assert.deepEqual(headers, { Accept: 'application/json', 'X-Request-ID': 'req-1' });
});

test('identity headers set by callers are stripped regardless of case', () => {
  const headers = buildRequestHeaders(
    { 'X-HR-Actor': 'Mallory', 'x-hr-actor-source': 'casdoor', 'Content-Type': 'application/json' },
    'req-2',
  );

  assert.deepEqual(Object.keys(headers).sort(), ['Content-Type', 'X-Request-ID']);
});
