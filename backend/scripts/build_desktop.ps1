# PyInstaller 桌面端后端打包脚本
# 用法：.\scripts\build_desktop.ps1

$ErrorActionPreference = "Stop"

Write-Host "=== 审计系统后端 PyInstaller 打包 ===" -ForegroundColor Cyan

# Python 解释器路径（与项目一致）
$PythonPath = "D:\python\python.exe"

if (-not (Test-Path $PythonPath)) {
    Write-Host "错误: Python 未找到: $PythonPath" -ForegroundColor Red
    exit 1
}

# 切换到 backend 目录
Push-Location $PSScriptRoot\..
try {
    $BackendDir = Get-Location
    Write-Host "后端目录: $BackendDir" -ForegroundColor Gray

    # 1. 编译检查
    Write-Host "`n[1/5] 编译检查..." -ForegroundColor Yellow
    & $PythonPath -m compileall app
    if ($LASTEXITCODE -ne 0) {
        Write-Host "编译检查失败，退出" -ForegroundColor Red
        exit $LASTEXITCODE
    }
    Write-Host "  编译检查通过" -ForegroundColor Green

    # 2. 清理旧构建
    Write-Host "`n[2/5] 清理旧构建产物..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force dist\audit-backend -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force build -ErrorAction SilentlyContinue
    Write-Host "  清理完成" -ForegroundColor Green

    # 3. 安装/确认 PyInstaller
    Write-Host "`n[3/5] 确认 PyInstaller 已安装..." -ForegroundColor Yellow
    & $PythonPath -m pip install pyinstaller --quiet
    if ($LASTEXITCODE -ne 0) {
        Write-Host "PyInstaller 安装失败，退出" -ForegroundColor Red
        exit $LASTEXITCODE
    }
    Write-Host "  PyInstaller 就绪" -ForegroundColor Green

    # 4. 使用 spec 文件打包
    Write-Host "`n[4/5] PyInstaller 打包中（可能需要几分钟）..." -ForegroundColor Yellow
    & $PythonPath -m PyInstaller --clean --noconfirm pyinstaller.spec
    if ($LASTEXITCODE -ne 0) {
        Write-Host "打包失败，退出" -ForegroundColor Red
        exit $LASTEXITCODE
    }
    Write-Host "  打包完成" -ForegroundColor Green

    # 5. 验证输出
    Write-Host "`n[5/5] 验证输出..." -ForegroundColor Yellow
    $ExePath = "$BackendDir\dist\audit-backend\audit-backend.exe"
    if (Test-Path $ExePath) {
        $SizeMB = [math]::Round((Get-Item $ExePath).Length / 1MB, 2)
        Write-Host "  输出: $ExePath" -ForegroundColor Green
        Write-Host "  大小: ${SizeMB}MB" -ForegroundColor Green
    } else {
        Write-Host "  .exe 未找到，检查 dist/ 目录" -ForegroundColor Red
        Get-ChildItem -Recurse dist\ -Name
        exit 1
    }

    Write-Host "`n=== 打包成功 ===" -ForegroundColor Cyan
    Write-Host "  可执行文件: $ExePath" -ForegroundColor Cyan
    Write-Host "  数据目录将在首次启动时创建于 %APPDATA%\审计系统\" -ForegroundColor Cyan
} finally {
    Pop-Location
}
