import { defineConfig } from '@umijs/max';

export default defineConfig({
  npmClient: 'npm',
  antd: {},
  esbuildMinifyIIFE: true,
  request: {},
  history: { type: 'hash' },
  // dev 与 release 共用同一份前端镜像，分别挂在 /hr-certflow-dev/ 与 /hr-certflow/。
  // 必须保持相对路径：写死任一前缀都会让另一环境加载不到 umi.js。
  publicPath: process.env.NODE_ENV === 'production' ? './' : '/',
  // GlitchTip 运行时注入的占位配置，必须在主 bundle 之前加载。
  // 相对路径保证在 /hr-certflow/ 与 /hr-certflow-dev/ 子路径部署下都能命中
  // 站点根的 glitchtip-config.js；未挂载 ConfigMap 时是空占位文件，永不 404，
  // 也绝不会被 SPA fallback 当作 HTML 执行。
  headScripts: [{ src: './glitchtip-config.js' }],
  layout: {
    title: '人力证书管理',
    locale: false,
  },
  routes: [
    { path: '/', redirect: '/dashboard' },
    { name: '工作台', path: '/dashboard', component: './Dashboard' },
    { name: '人员管理', path: '/employees', component: './Employees' },
    { name: '证书类型', path: '/certificate-types', component: './CertificateTypes' },
    { name: '持证记录', path: '/certificates', component: './Certificates' },
    { name: '文件台账', path: '/documents', component: './Documents' },
    { name: '统计报表', path: '/reports', component: './Reports' },
    { name: '上传识别', path: '/upload-recognition', component: './UploadRecognition' },
    { name: '待复核队列', path: '/review-queue', component: './ReviewQueue' },
    { name: '提醒任务', path: '/reminders', component: './Reminders' },
    { name: '审计日志', path: '/audit-logs', component: './AuditLog' },
    { path: '*', component: './NotFound' },
  ],
  proxy: {
    '/api/v1': {
      target: process.env.API_BASE_URL || 'http://localhost:8000',
      changeOrigin: true,
    },
  },
});
