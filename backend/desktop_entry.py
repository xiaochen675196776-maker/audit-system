"""PyInstaller 桌面端启动入口

此文件是 PyInstaller 打包时的主入口脚本。
启动时强制开启桌面模式，由 app.core.desktop.run_desktop() 驱动完整启动流程。

用法：
    python desktop_entry.py
    desktop_entry.exe  （PyInstaller 打包后）
"""

import os
import sys

# 确保 backend 目录在 sys.path 中（PyInstaller onedir 模式需要）
_current_dir = os.path.dirname(os.path.abspath(__file__))
if _current_dir not in sys.path:
    sys.path.insert(0, _current_dir)

# 强制桌面模式
os.environ["AUDIT_DESKTOP_MODE"] = "true"

if __name__ == "__main__":
    from app.core.desktop import run_desktop

    run_desktop()
