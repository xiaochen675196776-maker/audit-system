/**
 * Electron 主进程入口
 *
 * 启动流程：
 * 1. 启动 FastAPI 后端（Python 子进程）
 * 2. 启动 Vite dev server（前端）
 * 3. 创建 BrowserWindow 加载前端
 * 4. 窗口关闭时优雅终止所有子进程
 */

// 必须在 require('electron') 和创建窗口前设置：
// preload.js 在渲染进程的隔离上下文中读取 process.env.AUDIT_DESKTOP_MODE，
// 该值继承自主进程环境。这里显式置为 'true'，确保：
//   1. 子进程（Python 后端、Vite）继承到桌面模式
//   2. preload 注入到前端的 window.__AUDIT_CONFIG__.desktopMode 为 true
process.env.AUDIT_DESKTOP_MODE = 'true';

const { app, BrowserWindow } = require('electron');
const path = require('path');
const { startBackendWithFallback, stopBackend } = require('./backend');
const { spawn } = require('child_process');

/** 前端 Vite dev server 子进程引用 */
let viteProcess = null;
/** 后端子进程引用 */
let backendProcess = null;
/** 后端实际端口 */
let backendPort = null;
/** 主窗口引用 */
let mainWindow = null;

/** 启动 Vite dev server */
function startViteDev(apiPort) {
  return new Promise((resolve, reject) => {
    const frontendDir = path.join(__dirname, '..', 'frontend');
    // 直接用 node 运行 vite 的 JS 入口，跨平台且不依赖 shell。
    // 之前用 spawn('node_modules/.bin/vite', ..., { shell: true })，在 Windows 上
    // 因 .bin/vite 是无扩展名的 sh 脚本，shell 无法执行，报 "'node_modules' 不是内部或外部命令"。
    const viteEntry = path.join(frontendDir, 'node_modules', 'vite', 'bin', 'vite.js');
    const env = {
      ...process.env,
      VITE_API_TARGET: `http://127.0.0.1:${apiPort}`,
    };

    console.log(`[desktop] 启动 Vite dev server，API target: ${env.VITE_API_TARGET}`);

    // --host 127.0.0.1：强制 Vite 绑定 IPv4。
    // Node 17+ 默认把 'localhost' 解析为 IPv6 [::1]，Vite 因此只监听 [::1]:5173，
    // 而 Electron 的 loadURL('localhost') 在 Windows 上优先解析为 127.0.0.1，
    // 二者不匹配导致窗口 ERR_CONNECTION_REFUSED。显式绑定 127.0.0.1 并让窗口用同一地址。
    const proc = spawn(process.execPath, [viteEntry, '--host', '127.0.0.1', '--port', '5173', '--strictPort'], {
      cwd: frontendDir,
      env,
      stdio: ['ignore', 'pipe', 'pipe'],
    });

    proc.stdout.on('data', (data) => {
      const text = data.toString();
      console.log(`[vite] ${text.trim()}`);
      // Vite 就绪标志
      if (text.includes('Local:') && text.includes('5173')) {
        resolve(proc);
      }
    });

    proc.stderr.on('data', (data) => {
      console.error(`[vite:err] ${data.toString().trim()}`);
    });

    proc.on('error', (err) => {
      reject(new Error(`无法启动 Vite: ${err.message}`));
    });

    // 超时 30 秒
    setTimeout(() => {
      resolve(proc); // 即使没检测到就绪标志也继续
    }, 30000);
  });
}

/** 创建主窗口 */
function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1200,
    minHeight: 800,
    title: '审计系统',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
    show: false, // 等 ready-to-show 再显示
  });

  // 隐藏默认菜单栏
  mainWindow.setMenuBarVisibility(false);

  // 用 127.0.0.1 而非 localhost：与上方 Vite 的 --host 127.0.0.1 绑定地址一致，
  // 避免 Windows 下 localhost 优先解析为 IPv4 而 Vite 监听 IPv6 导致连接被拒。
  mainWindow.loadURL('http://127.0.0.1:5173');

  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });

  // 打开 DevTools（开发模式）
  if (process.env.AUDIT_DEVTOOLS !== 'false') {
    mainWindow.webContents.openDevTools({ mode: 'bottom' });
  }
}

/** 清理所有子进程 */
async function cleanup() {
  console.log('[desktop] 正在清理子进程...');

  if (viteProcess && !viteProcess.killed) {
    viteProcess.kill();
  }

  if (backendProcess) {
    await stopBackend(backendProcess);
  }

  console.log('[desktop] 清理完成');
}

// ============================================================
// Electron 应用生命周期
// ============================================================

app.whenReady().then(async () => {
  try {
    // 1. 启动后端
    const backend = await startBackendWithFallback({
      port: 18000,
      backendDir: path.join(__dirname, '..', 'backend'),
    });
    backendProcess = backend.process;
    backendPort = backend.port;

    // 将端口和数据目录注入 preload 环境变量
    process.env.AUDIT_API_PORT = String(backendPort);
    process.env.AUDIT_DATA_DIR = backend.dataDir || '';

    // 2. 启动 Vite dev server
    viteProcess = await startViteDev(backendPort);

    // 3. 创建窗口
    createWindow();

    console.log(`[desktop] 桌面端启动完成，后端端口: ${backendPort}`);
  } catch (err) {
    console.error('[desktop] 启动失败:', err.message);
    await cleanup();
    app.quit();
  }
});

app.on('window-all-closed', async () => {
  await cleanup();
  app.quit();
});

app.on('before-quit', async () => {
  await cleanup();
});

app.on('activate', () => {
  // macOS: 点击 dock 图标重新创建窗口
  if (mainWindow === null) {
    createWindow();
  }
});
