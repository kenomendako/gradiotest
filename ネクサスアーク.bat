@echo off
chcp 65001 > nul
set PYTHONIOENCODING=utf-8
title Nexus Ark

echo Nexus Ark を起動しています...
echo.
echo このウィンドウはアプリケーションの動作中、開いたままにしておいてください。
echo アプリケーションを終了するには、このウィンドウを閉じてください。
echo.

REM --- Pythonの実行ファイルを探す ---
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [エラー] Pythonが見つかりません。
    echo Python 3.10以降をインストールし、PATHが通っていることを確認してください。
    pause
    exit /b
)

REM --- メインのPythonスクリプトを実行 ---
python nexus_ark.py

echo.
echo アプリケーションが終了しました。
pause