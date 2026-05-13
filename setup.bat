@echo off
chcp 65001 >nul
title Stock Check - 一键部署
echo.
echo  ╔══════════════════════════════════════╗
echo  ║   Stock Check 股票分析平台 - 部署  ║
echo  ╚══════════════════════════════════════╝
echo.

:: ── 1. 检查/安装 Python ──────────────────────────
echo [1/4] 检查 Python 环境...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo   Python 未安装，正在通过 winget 安装...
    winget install Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
    if %errorlevel% neq 0 (
        echo   ❌ winget 安装失败，请手动安装 Python:
        echo   https://www.python.org/downloads/
        echo   安装时务必勾选 "Add Python to PATH"
        pause
        exit /b 1
    )
    echo   ✅ Python 安装完成，请重新运行 setup.bat
    pause
    exit /b 0
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do echo   ✅ Python %%v

:: ── 2. 安装依赖包 ───────────────────────────────
echo.
echo [2/4] 安装依赖包...
cd /d "%~dp0"
python -m pip install --upgrade pip --quiet
python -m pip install -r requirements.txt --quiet
if %errorlevel% neq 0 (
    echo   ❌ 依赖安装失败，请检查网络连接后重试
    pause
    exit /b 1
)
echo   ✅ 依赖包安装完成

:: ── 3. 创建桌面快捷方式 ──────────────────────────
echo.
echo [3/4] 创建桌面快捷方式...

set SCRIPT_DIR=%~dp0
set BAT_PATH=%SCRIPT_DIR%start.bat

powershell -NoProfile -Command "
    $ws = New-Object -ComObject WScript.Shell
    $sc = $ws.CreateShortcut([Environment]::GetFolderPath('Desktop') + '\StockCheck.lnk')
    $sc.TargetPath = '%BAT_PATH%'
    $sc.WorkingDirectory = '%SCRIPT_DIR%'
    $sc.IconLocation = 'shell32.dll,13'
    $sc.Description = 'Stock Check'
    $sc.Save()
" 2>nul

if exist "%USERPROFILE%\Desktop\StockCheck.lnk" (
    echo   ✅ 桌面快捷方式已创建
) else if exist "%USERPROFILE%\OneDrive\Desktop\StockCheck.lnk" (
    echo   ✅ 桌面快捷方式已创建
) else (
    echo   ⚠️  快捷方式创建失败，可手动右键 start.bat 发送到桌面
)

:: ── 4. 测试运行 ───────────────────────────────────
echo.
echo [4/4] 启动应用...
echo   🌐 浏览器将打开 http://localhost:8501
echo   📌 关闭此窗口即停止服务
echo.
start "" http://localhost:8501
streamlit run app.py --server.port 8501 --server.headless true --browser.gatherUsageStats false
pause
