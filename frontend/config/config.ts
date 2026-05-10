import { defineConfig } from '@umijs/max';

export default defineConfig({
  npmClient: 'npm',
  antd: {},
  esbuildMinifyIIFE: true,
  request: {},
  history: { type: 'hash' },
  publicPath: process.env.NODE_ENV === 'production' ? './' : '/',
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
