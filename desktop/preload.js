/**
 * Electron 预加载脚本
 *
 * 通过 contextBridge 安全地向渲染进程暴露桌面端配置。
 * 前端通过 window.__AUDIT_CONFIG__ 读取。
 */

const { contextBridge } = require('electron');

// 从主进程传入的配置（通过 webPreferences.preload 的环境变量）
const apiPort = process.env.AUDIT_API_PORT || '18000';
const dataDir = process.env.AUDIT_DATA_DIR || '';
const desktopMode = process.env.AUDIT_DESKTOP_MODE === 'true';

contextBridge.exposeInMainWorld('__AUDIT_CONFIG__', {
  apiBaseUrl: `http://127.0.0.1:${apiPort}`,
  desktopMode: desktopMode,
  dataDir: dataDir,
});
