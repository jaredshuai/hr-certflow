import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  boundaryMessage,
  DEFAULT_BOUNDARY_MESSAGE,
  errorBoundaryStateFromError,
  initialErrorBoundaryState,
} from '../src/utils/errorBoundaryState.ts';

test('a thrown Error keeps its message', () => {
  assert.equal(boundaryMessage(new Error('Cannot read properties of undefined')), 'Cannot read properties of undefined');
});

test('unreadable throwables use the fixed fallback instead of [object Object]', () => {
  for (const value of [undefined, null, {}, [], '', '   ', new Error('   '), new Error('[object Object]')]) {
    assert.equal(boundaryMessage(value), DEFAULT_BOUNDARY_MESSAGE);
  }
  assert.equal(boundaryMessage('render failed'), 'render failed');
});

test('getDerivedStateFromError marks the boundary as failed with a readable message', () => {
  assert.equal(errorBoundaryStateFromError(new Error('boom')).hasError, true);
  assert.equal(errorBoundaryStateFromError(new Error('boom')).message, 'boom');
  assert.equal(initialErrorBoundaryState.hasError, false);
});
