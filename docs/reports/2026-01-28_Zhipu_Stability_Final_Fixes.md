# Zhipu AI / OpenAI パラメータフィルタリングの強化と不具合修正

**日付:** 2026-01-28  
**ブランチ:** `fix/zhipu-param-filtering`, `fix/tool-provider-mismatch`  
**ステータス:** ✅ 完了

---

## 問題の概要

Zhipu AI (GLM-4) および OpenAI 互換プロバイダにおいて、以下の安定性に関する問題が発生していました。
1. **Error 404 (Not Found)**: ツール実行時にルーム別のプロバイダ設定が無視され、Zhipu AI 設定時に誤って Google API (Gemini) が呼び出される。
2. **Error 1210 (API 调用参数有誤)**: Google 固有の安全性設定（safety_settings）などが Zhipu AI に送信されてエラーになる。
3. **TypeError (unexpected keyword argument)**: アプリ固有の設定（`topic_cluster_min_size` 等）が `model_kwargs` を通じて API に送信され、Python クライアント側でエラーが発生する。

---

## 修正内容

### 1. プロバイダ判定の修正 (`agent/graph.py`)
- `safe_tool_executor` において、`LLMFactory.create_chat_model` に `room_name` を渡すように修正し、ツール実行時もルーム個別のプロバイダ設定が正しく適用されるようにしました。

### 2. パラメータフィルタリングのホワイトリスト化 (`llm_factory.py`)
- Zhipu AI および汎用 OpenAI プロバイダにおいて、従来の「除外リスト（ブラックリスト）」方式から「許可リスト（ホワイトリスト）」方式に変更しました。
- `presence_penalty`, `seed`, `user` など、OpenAI 規格でサポートされている主要パラメータのみを送信するように制限し、想定外のパラメータによる `TypeError` を排除しました。

### 3. Zhipu AI モデル (`glm-4.7-flash`) への最適化
- `glm-4.7-flash` 使用時に、メーカー推奨値である `temperature=0.7`, `top_p=1.0` を自動適用するようにしました。
- メッセージ履歴の先頭でのシステムプロンプト重複を排除しました。
- Zhipu AI 使用時の並列ツール呼び出し（Parallel Tool Calls）を無効化し、ツールの確実な動作を保証しました。

---

## 変更したファイル

- `nexus_ark/agent/graph.py` - ツール実行時のプロバイダ判定、メッセージ履歴のクリーンアップ、並列ツール呼び出しの制御。
- `nexus_ark/llm_factory.py` - ホワイトリスト方式のパラメータフィルタリングの実装、および Zhipu AI 向け最適化。
- `nexus_ark/config_manager.py` - Zhipu プロバイダの有効化とモデル取得ロジックの修正。

---

## 検証結果

- [x] Zhipu AI (`glm-4.7-flash`) での会話ストリーミング確認
- [x] Zhipu AI でのツール実行（メモ帳更新プラン等）の正常動作確認
- [x] 不正なパラメータ注入時のフィルタリング動作確認（再現用スクリプトにて確認）
- [x] 既存の Google (Gemini) モデルへの副作用がないことを確認

---

## 残課題（あれば）

なし。
Zhipu AI の最新モデルを Nexus Ark の全機能で安定して利用できる環境が整いました。
