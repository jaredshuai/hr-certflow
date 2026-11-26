// node 模块注册钩子：把 '@umijs/max' 重定向到 tests/helpers/umijs-max-stub.mjs。
// 通过 tests/register-umijs-loader.mjs 的 module.register 生效。
import { pathToFileURL } from 'node:url';
import { resolve as resolvePath } from 'node:path';
import { fileURLToPath } from 'node:url';

const stubUrl = pathToFileURL(resolvePath(fileURLToPath(import.meta.url), '../umijs-max-stub.mjs')).href;

export async function resolve(specifier, context, nextResolve) {
  if (specifier === '@umijs/max') {
    return { url: stubUrl, shortCircuit: true };
  }
  return nextResolve(specifier, context);
}
