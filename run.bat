@echo off
chcp 65001 >nul
title 剪映字幕导出

where python >nul 2>nul
if errorlevel 1 (
    echo.
    echo 没找到 python。请先安装 Python 3.9 或更高版本，并勾选"Add to PATH"。
    echo 下载地址: https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

python "%~dp0jy_subtitle_extract.py" %*
echo.
pause
