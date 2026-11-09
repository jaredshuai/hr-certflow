import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  buildLoginUrl,
  loginUrlForLocation,
  resolveAppBase,
  safeReturnPath,
} from '../src/utils/loginRedirect.ts';

test('app base matches the same gateway prefixes as the API base path', () => {
  assert.equal(resolveAppBase('/hr-certflow/'), '/hr-certflow');
  assert.equal(resolveAppBase('/hr-certflow'), '/hr-certflow');
  assert.equal(resolveAppBase('/hr-certflow/reviews/1'), '/hr-certflow');
  assert.equal(resolveAppBase('/hr-certflow-dev/x'), '/hr-certflow-dev');
  assert.equal(resolveAppBase('/'), undefined);
  assert.equal(resolveAppBase('/reviews'), undefined);
  assert.equal(resolveAppBase('/hr-certflowx/'), undefined);
});

test('login URL keeps the current path, query and hash as rd', () => {
  assert.equal(
    loginUrlForLocation({ pathname: '/hr-certflow/reviews', search: '?id=3&tab=a', hash: '#top' }),
    `/hr-certflow/oauth2/start?rd=${encodeURIComponent('/hr-certflow/reviews?id=3&tab=a#top')}`,
  );
  assert.equal(
    loginUrlForLocation({ pathname: '/hr-certflow/', search: '', hash: '' }),
    '/hr-certflow/oauth2/start?rd=%2Fhr-certflow%2F',
  );
});

test('no redirect outside the gateway prefix (local / direct access)', () => {
  assert.equal(loginUrlForLocation({ pathname: '/', search: '', hash: '' }), undefined);
});

test('dev and retired prefixes never redirect to login', () => {
  assert.equal(loginUrlForLocation({ pathname: '/hr-certflow-dev/', search: '', hash: '' }), undefined);
  assert.equal(loginUrlForLocation({ pathname: '/hr-certflow-release/', search: '', hash: '' }), undefined);
});

test('rd only allows same-origin paths under the app base', () => {
  assert.equal(safeReturnPath('/hr-certflow', '/hr-certflow/a?b=1'), '/hr-certflow/a?b=1');
  assert.equal(safeReturnPath('/hr-certflow', '/hr-certflow'), '/hr-certflow');
  for (const bad of ['//evil.example/hr-certflow', 'https://evil.example/', '/other', '/hr-certflowx', '/hr-certflow\\..']) {
    assert.equal(safeReturnPath('/hr-certflow', bad), '/hr-certflow/');
  }
  assert.equal(buildLoginUrl('/hr-certflow', '/other'), '/hr-certflow/oauth2/start?rd=%2Fhr-certflow%2F');
});
