/**
 * 前端运行时配置
 *
 * 支持两种配置来源（优先级从高到低）：
 * 1. window.__AUDIT_CONFIG__   — Electron 预加载脚本注入（桌面端）
 * 2. 内置默认值               — 浏览器开发模式
 */

export interface AuditConfig {
  /** API 基地址（绝对 URL），桌面端由 Electron 注入 */
  apiBaseUrl: string
  /** 是否为桌面模式 */
  desktopMode: boolean
  /** 用户数据目录路径（桌面端） */
  dataDir: string
}

declare global {
  interface Window {
    __AUDIT_CONFIG__?: Partial<AuditConfig>
  }
}

function getConfig(): AuditConfig {
  const injected = window.__AUDIT_CONFIG__ || {}

  return {
    apiBaseUrl: injected.apiBaseUrl || '',
    desktopMode: injected.desktopMode || false,
    dataDir: injected.dataDir || '',
  }
}

/** 单例运行时配置 */
export const runtimeConfig = getConfig()
