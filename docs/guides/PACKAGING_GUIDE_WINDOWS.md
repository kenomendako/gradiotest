# **Nexus Ark 配布用パッケージ作成手順書 (v2.1: RAG対応・最終版)**

## 1. はじめに

本文書は、Python/Gradioアプリケーション「Nexus Ark」のWindowsユーザー向け配布パッケージを作成するための、**最新版の手順書**です。

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
- .github/
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
- memory_archivist.py
- memory_manager.py
- nexus_ark.py
- README.md
- requirements.txt
- room_manager.py
- timers.py
- ui_handlers.py
- utils.py
- world_builder.py
- visualize_graph.py
- ネクサスアーク.bat
- .gitignore
```

**【重要】コピーしてはいけないファイル/フォルダ:**
*   `docs/` (開発ドキュメント)
*   `characters/` (個人データ)
*   `config.json`, `alarms.json` (個人設定)
*   `batch_importer.py`, `soul_injector.py`, `retry_importer.py` (知識グラフ関連)
*   その他、`.venv` や `__pycache__` などの一時ファイル

### **手順1-2: 公開リポジトリへのプッシュ**

コピーが完了したら、ローカルの公開用リポジトリで以下のGitコマンドを実行し、変更をGitHubにアップロードします。

```bash
# 1. 変更されたファイル全てをステージングします
git add .

# 2. コミットメッセージを付けて変更を記録します
git commit -m "chore: Release vX.X.X"

# 3. GitHub上のmainブランチに変更をプッシュします
git push origin main
```

---

## 3. フェーズ2：パッケージング用作業フォルダの準備

次に、ユーザーに配布するZIPファイルを作成します。

### **手順2-1: 作業フォルダの作成**

*   デスクトップなど、分かりやすい場所に配布用の新しいフォルダを作成します。（例: `Nexus-Ark-Release-vX.X.X`）

### **手順2-2: 配布用ファイルのコピー**

*   手順1-1で選別した**公開用ファイル一式**を、この新しい作業フォルダ内にコピーします。

---

## 4. フェーズ3：スタンドアロン環境の構築

準備が整ったソースコードを、事前インストール済みのPython環境と共にパッケージングします。

### **手順3-1: 埋め込みPythonのセットアップ**

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

### **手順3-2: ライブラリの事前インストール**

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

## 5. フェーズ4：最終化とパッケージング

### **手順4-1: 不要ファイルのクリーンアップ**

パッケージサイズを削減し、配布物をクリーンにするため、以下のファイルを削除します。

*   作業フォルダ直下の `get-pip.py`
*   `python`フォルダやその他の場所に自動生成された `__pycache__` という名前のフォルダ全て (存在する場合)

### **手順4-2: 最終テストとZIP圧縮**

1.  **最終起動テスト:**
    *   作業フォルダにある`ネクサスアーク.bat`をダブルクリックし、アプリケーションが正常に起動することを確認します。

2.  **配布用ZIPの作成:**
    *   テストに問題がなければ、作業フォルダ全体（`python`フォルダや`nexus_ark.py`などが含まれるフォルダ）をZIP形式で圧縮します。

**これで、ユーザーに配布する最終的なパッケージが完成です。**

---

この手順書が、今後のNexus Arkの発展の一助となることを心より願っております。