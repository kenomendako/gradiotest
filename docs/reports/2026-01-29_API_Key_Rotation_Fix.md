# API Key Rotation & 429 Error Handling Implementation Report

**日付:** 2026-01-29  
**ブランチ:** `fix/api-quota-rotation`  
**ステータス:** ✅ 完了

---

## 問題の概要

Gemini APIにおいて、`429 RESOURCE_EXHAUSTED` エラーが発生した際に、APIキーのローテーションが行われずに処理が中断する問題が発生していました。特に、グラフ内のサブノード（`retrieval_node` や `generate_scenery_context`）で発生したエラーが握りつぶされていたり、システムが検知できない例外タイプであったりしたことが原因でした。
また、アラームやタイマーなどのバックグラウンドタスクにおいて、情景描写生成失敗がタスク全体の失敗に繋がる構造的脆弱性がありました。

---

## 修正内容

1.  **エラーハンドリングの強化 (`agent/graph.py`, `gemini_api.py`)**
    -   `gemini_api.py` のローテーションループで、`ResourceExhausted` に加えて `ChatGoogleGenerativeAIError` (LangChainラッパーエラー) もキャッチし、429エラーを判定できるようにしました。
    -   `retrieval_node` などのサブノードで発生した429エラーをキャッチし、握りつぶさずに再送出（re-raise）することで、上位のローテーションロジックに伝播させるようにしました。
    -   `AgentState` に `api_key_name` を追加し、実行中のAPIキー情報をステートとして保持・伝達できるようにしました。

2.  **情景生成の遅延実行とローテーション適用 (`agent/scenery_manager.py`, `gemini_api.py`)**
    -   情景描写の生成ロジックを `generate_scenery_context` として `agent/scenery_manager.py` に分離し、循環参照を解消しました。
    -   `alarm_manager.py` や `timers.py` での事前の情景生成を廃止し、`gemini_api.py` の `invoke_nexus_agent_stream` ループ内での「遅延生成（Lazy Generation）」に移行しました。
    -   これにより、情景生成時のAPIコールもローテーションロジックの保護下に入り、エラー発生時の自動リトライが可能になりました。

3.  **アラーム・タイマーの堅牢化 (`alarm_manager.py`, `timers.py`)**
    -   直接的なAPIキー取得と使用を廃止し、全て共通の `invoke_nexus_agent_stream` を経由するようにリファクタリングしました。
    -   ログファイルの取得ロジック（`log_f`）の誤削除を修正し、正常に機能するように復元しました。

---

## 変更したファイル

-   `gemini_api.py` - LangChainエラー対応、情景描写の遅延生成ロジック追加
-   `agent/graph.py` - Error re-raise処理、`AgentState`拡張、循環参照解消のためのimport変更
-   `agent/scenery_manager.py` - [NEW] 情景描写生成ロジックを分離
-   `alarm_manager.py` - 情景生成の廃止（遅延生成への委譲）、APIキー直接使用の廃止、ログ出力ロジックの修正
-   `timers.py` - 情景生成の廃止（遅延生成への委譲）、APIキー直接使用の廃止
-   `ui_handlers.py` - importパスの修正

---

## 検証結果

-   [x] **自動テスト**: `test_api_rotation_fix.py` を作成し、429エラー発生時にキーが枯渇としてマークされ、次のキーでリトライが成功することを確認しました。
-   [x] **バックグラウンドタスク**: アラームマネージャーのリファクタリングが正しく行われ、必要なコンテキスト（ログファイル、時間帯情報）が正しく渡されていることをコードレベルで確認しました。

---

## 残課題

-   なし
