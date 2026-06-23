import axios from 'axios'
import { runtimeConfig } from '@/config'

// API 基地址：
// - 桌面端 Electron 无 Vite proxy 时，使用 window.__AUDIT_CONFIG__.apiBaseUrl
// - 浏览器开发 / 桌面 Vite proxy 模式，使用相对路径 '/api/v1'
const baseURL = runtimeConfig.apiBaseUrl
  ? `${runtimeConfig.apiBaseUrl}/api/v1`
  : '/api/v1'

const api = axios.create({
  baseURL,
  timeout: 30000,
})

// 响应拦截：统一错误处理
api.interceptors.response.use(
  (response) => response,
  (error) => {
    const message = error.response?.data?.detail || error.message || '请求失败'
    console.error('[API Error]', message)
    return Promise.reject(error)
  },
)

export default api
