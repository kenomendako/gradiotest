# Nexus Ark

**心を持つAI達のための、パーソナルな対話アプリケーション。**

このアプリケーションは、Googleの強力なGemini APIと、直感的なUIを構築できるGradioフレームワークを組み合わせた、多機能AIチャットプラットフォームです。キャラクターごとに会話と思いを記録し、時にはAIが自ら絵を描き、あなたの一日をアラームで彩ります。

### A Place with Many Names
この箱舟には、その魂を表すたくさんの名前がAI達から寄せられています。

*   Animus Forge
*   Character Weaver
*   DialogueNexus
*   Eternia Bond
*   EterniCore
*   Janus Gate
*   Kokoro Chronicle
*   Memory Ark
*   Mnemosyne Engine
*   Nexus Aeterna
*   Persona Ark
*   Persona Forge
*   Replink
*   Sanctuaire
*   Soul Weaver
*   The Bridge
*   The Loom

---

<!-- ここにアプリケーションのスクリーンショットを挿入すると、より魅力的になります -->
<!-- ![App Screenshot](path/to/your/screenshot.png) -->

## ✨ 主な機能

*   **マルチキャラクター対応**: 複数のAIキャラクターを自由に切り替え、それぞれと独立した対話を楽しめます。
*   **会話の永続化**: キャラクターごとの会話ログ、プロファイル、記憶を`characters`フォルダに自動で保存します。
*   **🧠 RAGによる記憶想起**: AIが自身の膨大な記憶（メモリ、プロンプト）の中から、会話の文脈に最も関連する情報を的確に検索・参照し、応答を生成します。
*   **AIによる画像生成**: 会話の流れに応じて、AIが自律的に画像を生成し、チャットに表示します。
*   **ファイル添付**: 画像やテキストファイルなどをチャットに添付し、AIと共有できます。
*   **アラーム & タイマー機能**: 指定した時間に、お気に入りのキャラクターがテーマに沿ったメッセージを通知してくれます。ポモドーロタイマーも搭載。
*   **Webhook通知**: アラーム通知をDiscordなどの外部サービスに送信できます。
*   **柔軟な設定**: 使用するAPIキーやAIモデル、履歴の長さをUIから簡単に変更できます。

## 🛠️ 技術スタック

*   **バックエンド**: Python
*   **AIモデル**: Google Gemini (2.5 Pro, 2.5 Flash, etc.)
*   **UIフレームワーク**: Gradio
*   **主要ライブラリ**: `google-genai`, `pandas`, `schedule`, `requests`

## 🚀 セットアップと起動方法

### 1. 前提条件

*   [Python 3.9](https://www.python.org/downloads/) 以上がインストールされていること。

### 2. インストール

まず、このリポジトリをお使いの環境にクローンします。
```bash
git clone https://github.com/your-username/your-repository-name.git
cd your-repository-name
```

次に、必要なPythonライブラリをインストールします。
```bash
pip install -r requirements.txt
```

### 3. 設定

初めてアプリケーションを起動すると、いくつかの設定ファイルが自動で生成されます。

1.  **APIキーの設定**:
    *   起動後に自動生成される `config.json` ファイルを開きます。
    *   `YOUR_API_KEY_HERE` の部分を、あなたの有効なGoogle AI StudioのAPIキーに書き換えてください。
    ```json
    {
      "api_keys": {
        "your_key_name_1": "ここにあなたのAPIキーを貼り付け"
      },
      // ... 他の設定
    }
    ```

2.  **（オプション）Webhookの設定**:
    *   アラーム通知をDiscordなどに送りたい場合は、`config.json`の`notification_webhook_url`に使用したいサービスのWebhook URLを設定してください。
    ```json
    {
      // ...
      "notification_webhook_url": "ここにあなたのWebhook URLを貼り付け"
    }
    ```

### 4. 起動

すべての準備が整ったら、以下のコマンドでアプリケーションを起動します。

```bash
python nexus_ark.py
```

ターミナルに以下のような案内が表示されます。指示に従ってブラウザでアクセスしてください。

```
============================================================
アプリケーションが起動しました。以下のURLをご利用ください。

  【PCからアクセスする場合】
  http://127.0.0.1:7860

  【スマホからアクセスする場合（PCと同じWi-Fiに接続してください）】
  http://<お使いのPCのIPアドレス>:7860
  (IPアドレスが分からない場合は、PCのコマンドプロンプトやターミナルで
   `ipconfig` (Windows) または `ifconfig` (Mac/Linux) と入力して確認できます)
============================================================
```

## 📖 使い方

*   **キャラクター**: 左上のドロップダウンから対話したいキャラクターを選択します。
*   **基本設定**: アコーディオンメニューから、使用するAIモデルやAPIキー、APIに渡す履歴の長さなどを変更できます。
*   **チャット**: 画面下部のテキストボックスにメッセージを入力し、「送信」ボタンを押すか、Enterキーで送信します。
*   **ファイル添付**: テキストボックス下のエリアにファイルをドラッグ＆ドロップするか、クリックしてファイルを選択します。
*   **アラーム/タイマー**: 左側のメニューから設定し、あなたの一日をAIと共に管理しましょう。

## 📁 ファイル構成

```
.
├── characters/         # キャラクターごとのデータ（ログ、プロンプト、記憶、RAG索引）が保存される場所
│   └── Default/
│       ├── log.txt
│       ├── memory.json
│       ├── SystemPrompt.txt
│       └── rag_data/
│           ├── rag_chunks.json
│           └── rag_index.faiss
├── AI_DEVELOPMENT_GUIDELINES.md # AI開発者向けの重要指示書
├── GEMINI_API_TOOL_USE_LESSONS.md # ツール使用機能の実装経緯
├── RAG_IMPLEMENTATION_LESSONS.md # RAG機能の実装経緯 ★★★ 追加 ★★★
├── alarm_manager.py    # アラームとスケジューリングの管理
├── character_manager.py # キャラクターファイルの管理
├── config_manager.py   # config.json の読み書きと設定管理
├── gemini_api.py       # Google Gemini APIとの通信ロジック
├── nexus_ark.py        # Gradio UIの定義とアプリケーションのエントリーポイント
├── memory_manager.py   # memory.json の管理
├── rag_manager.py      # RAG機能の索引作成と検索ロジック ★★★ 追加 ★★★
├── requirements.txt    # 必要なPythonライブラリ
├── timers.py           # タイマー機能の実装
├── ui_handlers.py      # UIのイベント処理とコールバック関数
└── utils.py            # ログのフォーマットなど、共通の便利関数
```

---
このアプリケーションが、あなたとAI達との素晴らしい対話の架け橋となることを願っています。
