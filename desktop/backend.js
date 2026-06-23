/**
 * FastAPI 后端进程管理器
 *
 * 职责：
 * - 启动 Python 后端子进程（桌面模式）
 * - 从 stdout 解析端口号和数据目录
 * - 轮询 health 端点等待后端就绪
 * - 超时处理
 * - 退出时优雅终止子进程
 */

const { spawn } = require('child_process');
const http = require('http');
const path = require('path');
const os = require('os');

/** 解析后端 stdout 输出的键值对行，如 "AUDIT_PORT=18000" */
function parseBackendOutput(line) {
  const portMatch = line.match(/^AUDIT_PORT=(\d+)/);
  const dataDirMatch = line.match(/^AUDIT_DATA_DIR=(.+)/);
  return {
    port: portMatch ? parseInt(portMatch[1], 10) : null,
    dataDir: dataDirMatch ? dataDirMatch[1].trim() : null,
  };
}

/** 轮询 health 端点，最多等待 timeoutMs 毫秒 */
function waitForHealth(port, timeoutMs = 30000) {
  return new Promise((resolve, reject) => {
    const startTime = Date.now();
    const interval = setInterval(() => {
      const req = http.get(`http://127.0.0.1:${port}/api/v1/health`, (res) => {
        if (res.statusCode === 200) {
          clearInterval(interval);
          res.resume(); // 消费响应体
          resolve(true);
        }
      });
      req.on('error', () => {
        // 后端尚未就绪，继续等待
      });
      req.setTimeout(2000, () => {
        req.destroy();
      });

      if (Date.now() - startTime > timeoutMs) {
        clearInterval(interval);
        reject(new Error(`后端启动超时（${timeoutMs / 1000} 秒）`));
      }
    }, 500);
  });
}

/** 查找可用的 Python 解释器路径（返回候选列表） */
function getPythonCandidates() {
  return [
    process.env.AUDIT_PYTHON_PATH, // 环境变量覆盖
    'D:\\python\\python.exe',       // 项目指定 Python
    'python',
    'python3',
    'py',
  ].filter(Boolean);
}

/**
 * 尝试用候选 Python 启动后端进程
 * 如果某个候选启动失败（spawn error），继续尝试下一个
 * 所有候选失败时拒绝并给出清晰错误信息
 */
function startBackendWithFallback(options = {}) {
  const candidates = getPythonCandidates();
  const errors = [];

  function tryNext(index) {
    if (index >= candidates.length) {
      return Promise.reject(new Error(
        `无法启动 Python 后端进程，已尝试 ${candidates.length} 个候选：\n` +
        candidates.map((c, i) => `  ${i + 1}. ${c}${errors[i] ? ' — ' + errors[i] : ''}`).join('\n')
      ));
    }
    const python = candidates[index];
    console.log(`[desktop] 尝试 Python 候选 ${index + 1}/${candidates.length}: ${python}`);
    return startBackend({ ...options, pythonPath: python })
      .catch((err) => {
        errors[index] = err.message;
        console.warn(`[desktop] 候选 "${python}" 失败: ${err.message}`);
        return tryNext(index + 1);
      });
  }

  return tryNext(0);
}

/** 查找可用的 Python 解释器路径 */
function findPython() {
  // 按优先级尝试
  const candidates = [
    process.env.AUDIT_PYTHON_PATH, // 环境变量覆盖
    'D:\\python\\python.exe',       // 项目指定 Python
    'python',
    'python3',
    'py',
  ].filter(Boolean);

  return candidates[0]; // 返回第一个候选，spawn 会尝试
}

/**
 * 启动后端进程
 * @param {object} options
 * @param {number} options.port - 期望的后端端口（默认 18000）
 * @param {string} options.pythonPath - Python 解释器路径
 * @param {string} options.backendDir - 后端目录路径
 * @returns {Promise<{process: ChildProcess, port: number, dataDir: string}>}
 */
function startBackend(options = {}) {
  const {
    port: desiredPort = 18000,
    pythonPath,
    backendDir,
  } = options;

  const python = pythonPath || findPython();
  const cwd = backendDir || path.join(__dirname, '..', 'backend');

  // 设置环境变量，让 desktop.py 使用指定端口起始值
  const env = {
    ...process.env,
    AUDIT_DESKTOP_MODE: 'true',
    AUDIT_PORT: String(desiredPort),
    PYTHONUNBUFFERED: '1', // 确保 stdout 实时输出
    PYTHONIOENCODING: 'utf-8', // 确保 stdout 输出 UTF-8，解决中文 Windows 下 GBK 乱码
    PYTHONUTF8: '1', // Python 3.7+ UTF-8 模式，强制文本 I/O 使用 UTF-8
  };

  console.log(`[desktop] 启动后端: ${python} -m app.core.desktop`);
  console.log(`[desktop] 工作目录: ${cwd}`);

  const proc = spawn(python, ['-m', 'app.core.desktop'], {
    cwd,
    env,
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: false,
  });

  return new Promise((resolve, reject) => {
    let detectedPort = null;
    let detectedDataDir = '';

    proc.stdout.on('data', (data) => {
      const lines = data.toString().split('\n').filter(Boolean);
      for (const line of lines) {
        console.log(`[backend] ${line}`);
        const parsed = parseBackendOutput(line);
        if (parsed.port) {
          detectedPort = parsed.port;
        }
        if (parsed.dataDir) {
          detectedDataDir = parsed.dataDir;
        }
      }
    });

    proc.stderr.on('data', (data) => {
      console.error(`[backend:err] ${data.toString().trim()}`);
    });

    proc.on('error', (err) => {
      reject(new Error(`无法启动 Python 进程: ${err.message}`));
    });

    proc.on('exit', (code) => {
      if (!detectedPort) {
        reject(new Error(`后端进程异常退出，退出码: ${code}`));
      }
    });

    // 等待检测到端口后，轮询 health 端点
    const checkInterval = setInterval(async () => {
      if (!detectedPort) return;
      clearInterval(checkInterval);

      try {
        await waitForHealth(detectedPort);
        console.log(`[desktop] 后端就绪: http://127.0.0.1:${detectedPort}`);
        resolve({ process: proc, port: detectedPort, dataDir: detectedDataDir });
      } catch (err) {
        reject(err);
      }
    }, 200);

    // 总超时 60 秒
    setTimeout(() => {
      clearInterval(checkInterval);
      if (!detectedPort) {
        reject(new Error('后端启动超时（60 秒内未检测到端口输出）'));
      }
    }, 60000);
  });
}

/** 停止后端进程（优雅终止，超时强制 kill） */
function stopBackend(proc, timeoutMs = 5000) {
  return new Promise((resolve) => {
    if (!proc || proc.killed) {
      resolve();
      return;
    }

    console.log('[desktop] 正在终止后端进程...');

    // Windows 上 SIGTERM 不总是有效，直接用 taskkill
    if (process.platform === 'win32') {
      try {
        const { exec } = require('child_process');
        exec(`taskkill /pid ${proc.pid} /T /F`, () => resolve());
      } catch {
        proc.kill();
        resolve();
      }
      return;
    }

    proc.kill('SIGTERM');
    const forceKill = setTimeout(() => {
      proc.kill('SIGKILL');
      resolve();
    }, timeoutMs);

    proc.on('exit', () => {
      clearTimeout(forceKill);
      resolve();
    });
  });
}

module.exports = { startBackend, startBackendWithFallback, stopBackend };
