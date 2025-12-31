# Nexus Ark RAGシステム仕様書 (Log Integration Ver.)

## 1. 概要
本システムは、ユーザーがアップロードした知識ドキュメント（Knowledge）だけでなく、**過去の膨大な会話ログ（Archives）**も統合的に検索可能にするためのRAG（Retrieval-Augmented Generation）基盤である。

## 2. エンベディング・エンジン

本システムは、テキストをベクトル化するエンベディング・エンジンとして、以下の2つのモードを選択できる。

- **Gemini API (Online)**: GoogleのAPIを使用。高精度で高性能だが、APIコストとネットワーク環境が必要。
- **Local (Offline)**: `sentence-transformers` モデルを使用してローカルでベクトル化。無料かつプライバシーが守られ、ネットワークなしでも動作する。

設定はルームごとの「記憶」タブにある「エンベディング設定」から切り替えることができる。

- **静的インデックス (`rag_data/faiss_index_static`)**: 
    - 過去ログアーカイブ (`log_archives/*.txt`)
    - エピソード記憶 (`memory/episodic_memory.txt`)
    - 夢日記 (`memory/dream_diary.txt`)
    - **日記ファイル (`memory/memory_main.txt`, `memory/memory_archived_*.txt`)** [2025-12-31 追加]
- **動的インデックス (`rag_data/faiss_index_dynamic`)**: 
    - 知識ベース (`knowledge/*.txt`)
    - 現行ログ (`log.txt`)

### インデックスの選定理由
- 日記や過去ログは量が多く、一度書き込まれた内容は頻繁には変わらないため、差分更新が可能な「静的インデックス」で管理します。
- 知識ベースや現在進行中のログは、内容の変更や削除が即座に反映される必要があるため、毎回再構築する「動的インデックス」で管理します。

## 3. ファイル構成と責務

### `rag_manager.py`
RAG機能の全権を担う司令塔クラス。
*   **`create_or_update_index()`:** 上記のハイブリッドロジックに基づき、インデックスを構築・更新する。
*   **`search(query)`:** 静的・動的の両方のインデックスを検索し、結果を統合して返す。

### フォルダ構造 (`characters/{room_name}/`)
```text
rag_data/
├── faiss_index_static/       # 過去ログ用の巨大なインデックス
├── faiss_index_dynamic/      # 知識・現行ログ用の軽量インデックス
└── processed_static_files.json # 静的インデックスに取り込み済みのファイルリスト
```

## 4. 検索ツールの挙動

### `search_knowledge_base`
*   ユーザーの質問に対して、知識ベース（マニュアル）と過去ログの両方から回答を探す。
*   RAG Manager経由でベクトル検索を行う。
*   **2024-12-28更新**: `retrieval_node`での自動検索では、本ツール（RAG検索）のみを使用するようになった。

### `search_past_conversations` (廃止)

> [!CAUTION]
> **2024-12-28 廃止**: 本ツールはAIのツール一覧から除外されました。

*   **廃止理由**: キーワードマッチ方式はノイズが多く、RAG検索（ベクトル検索）がログアーカイブをカバーしているため冗長でした。
*   **代替手段**: 過去の会話を検索したい場合は `search_knowledge_base` を使用してください。RAGシステムが過去ログを意味的に検索します。
*   **コードの残存**: `tools/memory_tools.py` にコードは残存していますが、AIからは呼び出せません。

## 5. 運用ルール
*   **過去ログの追加:** ファイル名に規則性は不要。`log_archives/` に `.txt` を置くだけでよい。
*   **インデックス更新:** 任意のタイミングでUIの「索引を作成 / 更新」ボタンを押すことで、最新の状態が反映される。

---
**最終更新**: 2024-12-28 (コンテキスト最適化に伴う更新)