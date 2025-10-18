# **Nexus Ark 配布用パッケージ作成手順書 (v2: RAG対応版)**

## 1. はじめに

本文書は、Python/Gradioアプリケーション「Nexus Ark」のWindowsユーザー向け配布パッケージを作成するための、**最新版の手順書**です。

この手順は、ユーザーのPC環境に一切依存せず、追加のインストール作業を要求しない**「完全事前パッケージング方式」**を採用しています。開発者の手元で必要なライブラリを全てインストール済みのPython環境を同梱することで、絶対的な動作の信頼性を確保することを目的とします。

**本ガイドの対象バージョン:**
- RAG（知識ベース）機能を含みます。
- 知識グラフ構築機能（`spacy`, `networkx`等に依存）は含みません。

---

## 2. フェーズ1：パッケージング用ファイルの準備

まず、配布に必要なファイルを作業用のフォルダにまとめます。

### **手順1-1: 作業フォルダの作成**

*   デスクトップなど、分かりやすい場所に配布用の新しいフォルダを作成します。（例: `Nexus-Ark-Release-vX.X.X`）

### **手順1-2: 必須ファイルのコピー**

*   開発リポジトリ（`gradiotest`）から、以下のファイルとフォルダを、作成した作業フォルダ内にコピーします。

```
- .github/
- agent/
- assets/
- docs/
- tools/
- alarm_manager.py
- audio_manager.py
- chatgpt_importer.py
- claude_importer.py
- config_manager.py
- constants.py
- gemini_api.py
- generic_importer.py
- memory_archivist.py
- memory_manager.py
- nexus_ark.py
- README.md
- requirements.txt  (※開発リポジトリで更新済みのもの)
- room_manager.py
- timers.py
- ui_handlers.py
- utils.py
- world_builder.py
- ネクサスアーク.bat   (※開発リポジトリで更新済みのもの)
- .gitignore
```

*   **注意:** `characters/` フォルダや `config.json` など、Gitで管理されていない個人データはコピーしないでください。

---

## 3. フェーズ2：スタンドアロン環境の構築

準備が整ったソースコードを、事前インストール済みのPython環境と共にパッケージングします。

### **手順2-1: 埋め込みPythonのセットアップ**

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

### **手順2-2: ライブラリの事前インストール**

1.  **`get-pip.py`の配置:**
    *   [https://bootstrap.pypa.io/get-pip.py](https://bootstrap.pypa.io/get-pip.py) から`get-pip.py`をダウンロードし、作業フォルダの**直下**に配置します。

2.  **コマンドプロンプトでのインストール:**
    *   コマンドプロンプトを起動し、`cd`コマンドで作業フォルダに移動します。
    *   以下のコマンドを**1行ずつ、順番に実行**します。

    ```cmd
    :: 1. pipをインストール
    python\python.exe get-pip.py

    :: 2. 基本ツールをアップグレード
    python\python.exe -m pip install --upgrade pip setuptools wheel

    :: 3. 準備したrequirements.txtを元に全てのライブラリをインストール
    python\python.exe -m pip install -r requirements.txt
    ```

---

## 4. フェーズ3：最終化とパッケージング

### **手順3-1: 不要ファイルのクリーンアップ**

パッケージサイズを削減し、配布物をクリーンにするため、以下のファイルを削除します。

*   作業フォルダ直下の `get-pip.py`
*   `python`フォルダやその他の場所に自動生成された `__pycache__` という名前のフォルダ全て (存在する場合)

### **手順3-2: 最終テストとZIP圧縮**

1.  **最終起動テスト:**
    *   作業フォルダにある`ネクサスアーク.bat`をダブルクリックし、アプリケーションが正常に起動することを確認します。

2.  **配布用ZIPの作成:**
    *   テストに問題がなければ、作業フォルダ全体（`python`フォルダや`nexus_ark.py`などが含まれるフォルダ）をZIP形式で圧縮します。

**これで、ユーザーに配布する最終的なパッケージが完成です。**

---

この手順書が、今後のNexus Arkの発展の一助となることを心より願っております。