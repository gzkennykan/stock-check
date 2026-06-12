@echo off
chcp 65001 >nul
REM ============================================
REM  创建 Windows 定时任务：每个交易日 15:30 自动同步
REM  右键 → 以管理员身份运行
REM ============================================

set SCRIPT_DIR=%~dp0
set TASK_NAME=StockSystemDailySync

echo 正在创建定时任务: %TASK_NAME%
echo 脚本路径: %SCRIPT_DIR%sync_daily.bat
echo.

schtasks /Create /SC DAILY /TN %TASK_NAME% /TR "\"%SCRIPT_DIR%sync_daily.bat\"" /ST 15:30 /F

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ========================================
    echo  定时任务已创建!
    echo  任务名: %TASK_NAME%
    echo  每天 15:30 自动运行
    echo.
    echo  管理: taskschd.msc → 任务计划程序库
    echo ========================================
) else (
    echo.
    echo 创建失败，请以管理员身份重新运行此脚本
)

pause
