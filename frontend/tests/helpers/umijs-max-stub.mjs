// node --test 无法解析 '@umijs/max'（umi 运行时别名）。tests/register-umijs-loader.mjs
// 把该 specifier 重定向到这里；测试用 setRequestImpl 注入 request 行为，
// 从而端到端驱动 src 代码（如 downloadCsv）的真实接线。
let requestImpl = async () => {
  throw new Error('tests: @umijs/max request stub not configured — call setRequestImpl first');
};

export function setRequestImpl(impl) {
  requestImpl = impl;
}

export function resetRequestImpl() {
  requestImpl = async () => {
    throw new Error('tests: @umijs/max request stub not configured — call setRequestImpl first');
  };
}

export async function request(...args) {
  return requestImpl(...args);
}

export function useLocation() {
  throw new Error('tests: useLocation stub is not implemented');
}
