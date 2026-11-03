import assert from 'node:assert/strict';
import { test } from 'node:test';

import { actorStateFromErrorStatus, actorStateFromMe } from '../src/utils/actorState.ts';

test('authenticated /me shows the gateway identity', () => {
  assert.deepEqual(actorStateFromMe({ name: '张三', source: 'casdoor', authenticated: true }), {
    status: 'authenticated',
    name: '张三',
    source: 'casdoor',
  });
});

test('dev fixed operator is labelled, not shown as a logged-in person', () => {
  assert.deepEqual(
    actorStateFromMe({ name: 'dev-unauthenticated', source: 'dev-unauthenticated', authenticated: false }),
    { status: 'dev-operator', name: 'dev-unauthenticated' },
  );
});

test('missing identity never falls back to a mock actor', () => {
  for (const me of [null, undefined, { name: null, source: null, authenticated: false }]) {
    assert.deepEqual(actorStateFromMe(me), { status: 'unauthenticated' });
  }
  assert.deepEqual(actorStateFromMe({ name: 'HR 管理员', source: 'mock', authenticated: false }), {
    status: 'unauthenticated',
  });
});

test('401 from /me means unauthenticated; other failures are errors', () => {
  assert.deepEqual(actorStateFromErrorStatus(401), { status: 'unauthenticated' });
  assert.deepEqual(actorStateFromErrorStatus(500), { status: 'error' });
  assert.deepEqual(actorStateFromErrorStatus(undefined), { status: 'error' });
});
