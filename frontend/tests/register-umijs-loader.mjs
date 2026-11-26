// 在任何导入 src 里 '@umijs/max' 的测试文件之前 import 本模块：
// node 的模块定制钩子把 '@umijs/max' 解析到 tests/helpers/umijs-max-stub.mjs，
// 测试再经 setRequestImpl 注入 request 行为，端到端覆盖 src 真实接线。
import { register } from 'node:module';

register('./helpers/loader-hooks.mjs', import.meta.url);
