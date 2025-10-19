# **Nexus Ark 配布用パッケージ作成手順書 (v2.3: 最終確定版)**

## 1. はじめに

本文書は、Python/Gradioアプリケーション「Nexus Ark」のWindowsユーザー向け配布パッケージを作成するための、**最新版の公式手順書**です。

この手順は、ユーザーのPC環境に一切依存せず、追加のインストール作業を要求しない**「完全事前パッケージング方式」**を採用しています。開発者の手元で必要なライブラリを全てインストール済みのPython環境を同梱することで、絶対的な動作の信頼性を確保することを目的とします。

**本ガイドの対象バージョン:**
- RAG（知識ベース）機能を含みます。
- 知識グラフ構築機能（`spacy`, `networkx`等に依存）は含みません。
- `docs/` フォルダは開発用資料のため、配布パッケージと公開リポジトリには含みません。

---

## 2. フェーズ1：公開用リポジトリの更新

まず、開発リポジトリ (`gradiotest`) から、公開に必要なファイルのみを、公開用リポジトリ (`Nexus-Ark`) にコピーします。

### **手順1-1: 公開用ファイルの選別**

開発リポジトリ（`gradiotest`）から、以下の**ファイルとフォルダのみ**を、ローカルPC上の公開用リポジトリのフォルダにコピー（上書き）します。

```
- agent/
- assets/
- tools/
- alarm_manager.py
- audio_manager.py
- chatgpt_importer.py
- claude_importer.py
- config_manager.py
- constants.py
- gemini_api.py
- generic_importer.py
- memory_manager.py
- nexus_ark.py
- README.md
- requirements.txt
- room_manager.py
- timers.py
- ui_handlers.py
- utils.py
- world_builder.py
- .gitignore
```

**【重要】コピーしてはいけないファイル/フォルダ:**
*   `.github/` (開発用設定)
*   `docs/` (開発ドキュメント)
*   `batch_importer.py`, `soul_injector.py`, `retry_importer.py`, `visualize_graph.py`, `run_load_config.py` (開発用・知識グラフ関連)
*   `ネクサスアーク.bat` (開発リポジトリのものは開発専用のため、コピーしない)
*   `characters/` (個人データ)
*   `config.json`, `alarms.json`,`redaction_rules.json` (個人設定)
*   その他、`.venv`, `__pycache__`, `.idea/`, `.vscode/` などの一時ファイル

### **手順1-2: 公開リポジトリへのプッシュ**

コピーが完了したら、ローカルの公開用リポジトリで以下のGitコマンドを実行し、変更をGitHubにアップロードします。

```bash
# 1. 変更されたファイル全てをステージングします
git add .

# 2. コミットメッセージを付けて変更を記録します
# (例: v0.1.0 のリリースの場合)
git commit -m "chore: Release v0.1.0"

# 3. GitHub上のmainブランチに変更をプッシュします
git push origin main
```

---

## 3. フェーズ2：パッケージング作業

次に、ユーザーに配布するZIPファイルを作成します。

### **手順2-1: 作業フォルダと `app` フォルダの準備**

1.  デスクトップなど、分かりやすい場所に配布用の新しいフォルダを作成します。（例: `Nexus-Ark-Release-v0.1.0`）
2.  そのフォルダの中に、**`app`** という名前の新しいフォルダを作成します。

### **手順2-2: 配布用ファイルの配置**

1.  **公開リポジトリ (`Nexus-Ark`)** からダウンロード、あるいはローカルコピーしたファイル群の中から、`README.md` と `.gitignore` を**除いた**、すべてのファイルとフォルダ（`nexus_ark.py`, `agent/`, `assets/` など）を、先ほど作成した **`app` フォルダの中に** コピーします。
2.  `README.md` と `.gitignore` は、`app` フォルダの**外（ルート）**にコピーします。

最終的なフォルダ構成は以下のようになります。
```
Nexus-Ark-Release-v0.1.0/
├── app/
│   ├── agent/
│   ├── assets/
│   ├── tools/
│   ├── nexus_ark.py  (※自己位置解決コードが追加された最新版)
│   ├── utils.py
│   ├── requirements.txt
│   └── ... (その他の全ソースファイル)
├── python/                  (※この後で作成)
├── README.md
├── .gitignore
└── ネクサスアーク.bat       (※この後で作成)
```

### **手順2-3: 配布用バッチファイルの作成**

*   作業フォルダの**ルート**（`app`フォルダの外）に `ネクサスアーク.bat` という名前で**新しいファイルを作成**し、以下の内容を貼り付けます。
*   **重要:** メモ帳で保存する際は、文字コードを**「ANSI」**に指定してください。

```bat
@echo off
rem --- Nexus Ark Launcher (v2: for 'app' directory structure) ---
chcp 65001 > nul
set PYTHONIOENCODING=utf-8
title Nexus Ark

echo Starting Nexus Ark...
echo If the browser does not open automatically, please open it and navigate to: http://127.0.0.1:7860
echo Please keep this window open while the application is running.

rem --- Change directory to the script's own location (the root) ---
cd /d "%~dp0"

rem --- Execute python from the embedded environment, targeting the script inside 'app' ---
python\python.exe app\nexus_ark.py

echo.
echo The application has been closed. You can now close this window.
pause
```

---

## 4. フェーズ3：スタンドアロン環境の構築

### **手順3-1: 埋め込みPythonのセットアップ**

1.  **ダウンロード:**
    *   [Python 3.11.9 のダウンロードページ](https://www.python.org/downloads/release/python-3119/)にアクセスし、「Files」セクションから`Windows embeddable package (64-bit)`（`python-3.11.9-embed-amd64.zip`）をダウンロードします。

2.  **展開と配置:**
    *   ダウンロードしたzipを作業フォルダの**ルート**に展開し、フォルダ名を`python`にリネームします。

3.  **`.pth`ファイルの最終修正:**
    *   `python`フォルダ内にある`python311._pth`をメモ帳で開きます。
    *   **ファイルの中身を、以下の正しい順番の3行で完全に置き換えてください。** この順番が極めて重要です。
    ```
    python311.zip
    import site
    .
    ```

### **手順3-2: ライブラリの事前インストール**

1.  **`get-pip.py`の配置:**
    *   [https://bootstrap.pypa.io/get-pip.py](https://bootstrap.pypa.io/get-pip.py) から`get-pip.py`をダウンロードし、作業フォルダの**直下（ルート）**に配置します。

2.  **コマンドプロンプトでのインストール:**
    *   コマンドプロンプトを起動し、`cd`コマンドで作業フォルダに移動します。
    *   以下のコマンドを**1行ずつ、順番に実行**します。

    ```cmd
    :: 1. pipをインストール
    python\python.exe get-pip.py

    :: 2. 基本ツールをアップグレード
    python\python.exe -m pip install --upgrade pip setuptools wheel

    :: 3. 'app'フォルダ内のrequirements.txtを元に全てのライブラリをインストール
    python\python.exe -m pip install -r app\requirements.txt
    ```

---

## 5. フェーズ4：最終化とパッケージング

### **手順4-1: 不要ファイルのクリーンアップ**

パッケージサイズを削減し、配布物をクリーンにするため、以下のファイルを削除します。

*   作業フォルダ直下の `get-pip.py`
*   `python`フォルダや`app`フォルダ内に自動生成された `__pycache__` という名前のフォルダ全て (存在する場合)

### **手順4-2: 最終テストとZIP圧縮**

1.  **最終起動テスト:**
    *   作業フォルダにある`ネクサスアーク.bat`をダブルクリックし、アプリケーションが正常に起動することを確認します。

2.  **配布用ZIPの作成:**
    *   テストに問題がなければ、作業フォルダ全体（`app`, `python`, `README.md`, `.bat`ファイルなどが含まれるフォルダ）をZIP形式で圧縮します。

**これで、ユーザーに配布する最終的なパッケージが完成です。**