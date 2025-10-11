# **Nexus Ark 配布用パッケージ作成手順書 (完全事前パッケージング方式)**

## 1. はじめに

本文書は、Python/Gradioアプリケーション「Nexus Ark」のWindowsユーザー向け配布パッケージを作成するための、**最終確定版の手順書**です。

この手順は、ユーザーのPC環境に一切依存せず、追加のインストール作業を要求しない**「完全事前パッケージング方式」**を採用しています。開発者の手元で必要なライブラリを全てインストール済みのPython環境を同梱することで、絶対的な動作の信頼性を確保することを目的とします。

## 2. フェーズ1：ソースコードの配布準備

アプリケーションをパッケージングする前に、配布に不要な機能への依存関係をコードレベルで完全に断ち切る必要があります。

### **手順1-1: 不要なライブラリの定義 (`requirements.txt`の最適化)**

`app`フォルダ内にある`requirements.txt`を、配布に必要なライブラリのみに限定します。これにより、最終的なパッケージサイズを削減します。

*   **目的:** 未完成の「知識グラフ管理」機能が依存する`spacy`, `networkx`等や、開発専用ツール(`ruff`等)をインストール対象から除外します。
*   **作業:** `app/requirements.txt`の中身を、以下の内容で**完全に上書き**してください。

```text
# Nexus Ark Distribution Requirements
# Last Updated: 2025-10-11 (Corrected Package Name)

# --- Core Frameworks ---
gradio==5.47.0
gradio_client==1.13.2
langchain==0.3.27
langchain-core==0.3.76
langchain-google-genai==2.1.12
langgraph==0.6.7
google-genai==1.38.0
pillow==11.3.0

# --- UI & Data Handling ---
pandas==2.3.2
beautifulsoup4==4.13.5
lxml==6.0.2

# --- Subprocess & Notifications ---
psutil==7.1.0
plyer==2.1.0
schedule==1.2.2
requests==2.3.2
pywin32==311; sys_platform == 'win32'

# --- File & System Utilities ---
filetype==1.2.0
python-dateutil==2.9.0.post0
pytz==2025.2
ijson==3.4.0
concurrent-log-handler==0.9.28

# --- LangChain/LangGraph Dependencies (Verified) ---
aiohttp==3.12.15
anyio==4.11.0
fastapi==0.117.1
httpx==0.28.1
numpy==2.3.3
orjson==3.11.3
pydantic==2.11.9
PyYAML==6.0.2
SQLAlchemy==2.0.43
tenacity==9.1.2

# --- Audio dependency ---
pydub==0.25.1
```

### **手順1-2: 不要な依存関係の外科的切除 (`agent/graph.py`の修正)**

`requirements.txt`からライブラリを除外しただけでは、プログラム起動時の`import`文でエラーが発生します。そのため、コード上から不要なライブラリへの参照を断ち切ります。

*   **目的:** `networkx`ライブラリを`import`している`tools/knowledge_tools.py`が、起動時に読み込まれないようにします。
*   **作業:** `app/agent/graph.py`ファイルに、以下の2点の修正を加えます。

    1.  **`import`文のコメントアウト:**
        ```python
        # from tools.knowledge_tools import search_knowledge_graph
        ```

    2.  **`all_tools`リストからの削除:**
        ```python
        all_tools = [
            # ... (他のツール) ...
            set_timer, set_pomodoro_timer,
            # search_knowledge_graph
        ]
        ```

### **手順1-3: 自己位置認識コードの追加 (`nexus_ark.py`の修正)**

埋め込み版Pythonが、`utils.py`などの自作モジュールを正しく見つけられるように、プログラム自身に自分の場所を教え込ませます。

*   **目的:** `ModuleNotFoundError`を根本的に解決し、あらゆる環境でモジュール検索パスが正しく設定されることを保証します。
*   **作業:** `app/nexus_ark.py`ファイルの**一番先頭**に、以下のコードブロックを追加してください。

```python
# === [CRITICAL FIX FOR EMBEDDED PYTHON] ===
# This block MUST be at the absolute top of the file.
import sys
import os

# Get the absolute path of the directory where this script is located.
# This ensures that even in an embedded environment, Python knows where to find other modules.
script_dir = os.path.dirname(os.path.abspath(__file__))

# Add the script's directory to Python's module search path.
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)
# === [END CRITICAL FIX] ===


# --- [ロギング設定の強制上書き] ---
# ... (既存のコードが続く) ...
```

---

## 3. フェーズ2：スタンドアロン環境の構築

準備が整ったソースコードを、事前インストール済みのPython環境と共にパッケージングします。

### **手順2-1: 作業フォルダの準備**

*   デスクトップなど、分かりやすい場所に配布用の新しいフォルダを作成します。（例: `Nexus-Ark-Release-vX.X.X`）

### **手順2-2: 必須ファイルのコピー**

*   フェーズ1で準備した`app`フォルダを作業フォルダ内にコピーします。
*   `README.md`を作業フォルダ内にコピーします。

### **手順2-3: 埋め込みPythonのセットアップ**

1.  **ダウンロード:**
    *   [Python 3.11.9 のダウンロードページ](https://www.python.org/downloads/release/python-3119/)にアクセスし、「Files」セクションから`Windows embeddable package (64-bit)`（`python-3.11.9-embed-amd64.zip`）をダウンロードします。

2.  **展開と配置:**
    *   ダウンロードしたzipを作業フォルダ内に展開し、フォルダ名を`python`にリネームします。

3.  **`.pth`ファイルの最終修正:**
    *   `python`フォルダ内にある`python311._pth`をメモ帳で開きます。
    *   **ファイルの中身を、以下の正しい順番の3行で完全に置き換えてください。** この順番が極めて重要です。
    ```
    python311.zip
    import site
    .
    ```

### **手順2-4: ライブラリの事前インストール**

1.  **`get-pip.py`の配置:**
    *   [https://bootstrap.pypa.io/get-pip.py](https://bootstrap.pypa.io/get-pip.py) から`get-pip.py`をダウンロードし、作業フォルダの**直下**に配置します。

2.  **コマンドプロンプトでのインストール:**
    *   コマンドプロンプトを起動し、`cd`コマンドで作業フォルダに移動します。
    *   以下のコマンドを**1行ずつ、順番に実行**します。

    ```cmd
    :: 1. pipをインストール
    python\python.exe get-pip.py

    :: 2. 基本ツールをインストール
    python\python.exe -m pip install --upgrade pip setuptools wheel

    :: 3. 準備したrequirements.txtを元に全てのライブラリをインストール
    python\python.exe -m pip install -r app\requirements.txt
    ```

---

## 4. フェーズ3：最終化とパッケージング

### **手順3-1: 不要ファイルのクリーンアップ**

パッケージサイズを削減し、配布物をクリーンにするため、以下のファイルを削除します。

*   **作業フォルダ直下の `get-pip.py`**
*   **`python`フォルダや`app`フォルダ内に自動生成された `__pycache__` という名前のフォルダ全て** (存在する場合)

### **手順3-2: 最終版 `ネクサスアーク.bat` の作成**

*   作業フォルダ内に`ネクサスアーク.bat`という名前で新しいファイルを作成し、以下の内容を貼り付けます。
*   **重要:** メモ帳で保存する際は、文字コードを**「ANSI」**に指定してください。

```bat
@echo off
rem --- Nexus Ark Launcher (The Ultimate Fix Version) ---
chcp 65001 > nul
set PYTHONIOENCODING=utf-8
title Nexus Ark

echo Starting Nexus Ark...
echo If the browser does not open automatically, please open it and navigate to: http://127.0.0.1:7860
echo Please keep this window open while the application is running.

rem --- Change directory TO the 'app' folder ---
cd /d "%~dp0app"

rem --- Execute python from the parent directory ---
..\python\python.exe nexus_ark.py

echo.
echo The application has been closed. You can now close this window.
pause
```

### **手順3-3: 最終テストとZIP圧縮**

1.  **最終起動テスト:**
    *   作成した`ネクサスアーク.bat`をダブルクリックし、アプリケーションが正常に起動することを確認します。

2.  **配布用ZIPの作成:**
    *   テストに問題がなければ、作業フォルダ全体（`app`, `python`, `README.md`, `.bat`ファイルが含まれるフォルダ）をZIP形式で圧縮します。

**これで、ユーザーに配布する最終的なパッケージが完成です。**

---

この長い道のり、本当にお疲れ様でした。この手順書が、今後のNexus Arkの発展の一助となることを心より願っております。
