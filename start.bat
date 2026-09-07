@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   工业缺陷检测系统
echo ============================================
echo.

rem 优先使用装有 PyTorch + 依赖 的解释器：
rem   1) 本机常见位置的 pytorch 环境
rem   2) 兜底使用 PATH 里的 python
set "PY="
if exist "D:\miniconda\envs\pytorch\python.exe" set "PY=D:\miniconda\envs\pytorch\python.exe"
if exist "%LOCALAPPDATA%\miniconda\envs\pytorch\python.exe" set "PY=%LOCALAPPDATA%\miniconda\envs\pytorch\python.exe"
if not defined PY (
    where python >nul 2>nul && set "PY=python"
)
if not defined PY (
    echo [错误] 未找到 python，请先安装 Python 3.10 或更高版本
    pause
    exit /b 1
)

echo 正在启动（首次启动会花几秒钟拉起后端服务）...
"%PY%" -m client.main

if errorlevel 1 (
    echo.
    echo 启动失败，请检查上面的错误信息。
    echo 提示：请先 pip install -r requirements.txt 并安装 OEGT-CP。
    pause
)
