// GlitchTip 前端错误监控的运行时配置占位文件。
//
// 默认空对象 = 监控静默关闭：入口只在 window.__GLITCHTIP_CONFIG__.dsn 非空时
// 才加载并初始化 @sentry/browser，本仓库（公仓）绝不写入任何真实 DSN 或内网地址。
// 部署侧要启用监控时，用 ConfigMap 以 subPath 覆盖挂载本文件注入配置，例如：
//
//   window.__GLITCHTIP_CONFIG__ = {
//     dsn: '<由部署侧私有 values 注入的 DSN>',
//     environment: 'release',
//   };
//
// nginx 对本文件返回 Cache-Control: no-store，覆盖挂载后浏览器不会死缓存旧配置。
window.__GLITCHTIP_CONFIG__ = window.__GLITCHTIP_CONFIG__ || {};
