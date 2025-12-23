# Gemini 3 ツール使用時の問題調査レポート

**作成日**: 2025-12-23
**ステータス**: 調査中（LangChain側の問題で一部未解決）

---

## 概要

Gemini 3 Flash Preview でツール使用を行う際、`MALFORMED_FUNCTION_CALL` エラーや空応答が発生する問題を調査した。

---

## 発見した事実

### 1. 思考署名（Thought Signature）の仕組み

Gemini 3 はツール呼び出し時に「思考署名」という暗号化された思考プロセスのトークンを返す。この署名は次のリクエストに含める必要があり、欠落すると 400 エラーが発生する。

| キー名 | 用途 |
|--------|------|
| `__gemini_function_call_thought_signatures__` | LangChainがGemini 3用に使用する正式キー |
| `thought_signature` | 古いモデル/旧バージョン用のキー |
| `extras.signature` | チャンク内に含まれる署名データ |

### 2. 発見した問題点

#### 問題A: 署名キーの不一致（修正済み）
- `gemini_api.py`: 古いキー `thought_signature` を使用
- `agent/graph.py`: 新しいキー `__gemini_function_call_thought_signatures__` を使用
- **対処**: 両方のファイルで新形式を優先し、後方互換性も維持するよう修正

#### 問題B: AIMessageの再作成（修正済み）
- 新しいAIMessageを作成すると、LangChainの内部状態（署名含む）が失われる
- **対処**: `merged_chunk` をそのまま使用し、`content` だけを上書きするよう修正

#### 問題C: LangChain内部の署名処理（未解決）
- 署名を `additional_kwargs` に注入しても、LangChainがAPIリクエストに正しく渡していない
- デバッグログでは `署名復元: 成功` と表示されるが、実際のAPIレスポンスには署名が含まれていない
- チャンク内には `extras.signature` として署名が存在するが、次のリクエストに反映されない

---

## テスト結果

| 条件 | 結果 | 備考 |
|------|------|------|
| 新規会話 + Gemini 3 + ツール + 思考オフ | ✅ 成功 | 1.38秒で応答 |
| 新規会話 + Gemini 3 + ツール + 思考オン | ✅ 成功 | ただし思考は英語 |
| 長い会話履歴(29件) + Gemini 3 + ツール + 思考オフ | ❌ 失敗 | 空応答/289秒タイムアウト |
| 長い会話履歴 + Gemini 3 + ツール + 思考オン | ❌ 失敗 | MALFORMED_FUNCTION_CALL |
| Gemini 2.5 + ツール | ✅ 成功 | 問題なし |

---

## コード変更履歴

### 1. `agent/graph.py`
- `merged_chunk.content` を上書きして再利用（新規AIMessage作成を廃止）
- 署名復元時に `__gemini_function_call_thought_signatures__` キーを使用
- Gemini 3 用デバッグログを追加

### 2. `gemini_api.py`
- 署名取得時に新形式を優先、古い形式にフォールバック
- 署名注入時に両方のキーを設定（新形式 + 後方互換）
- 署名抽出時に新形式を優先

### 3. `signature_manager.py`
- `gemini_function_call_thought_signatures` キーで署名を保存
- 後方互換性のため `last_signature` も維持

### 4. `config_manager.py`
- モデル名から `(Slow Response)` 注釈を削除

### 5. `requirements.txt`
- `langchain-google-genai` を `>=4.1.2` に更新

---

## 技術的詳細

### 署名が失われるフロー

```
1. AIがツールを呼び出す (1回目のAPI呼び出し)
   └─ レスポンスに __gemini_function_call_thought_signatures__ が含まれる ✅

2. ツールを実行し、結果をToolMessageとして追加

3. AIに再度リクエスト (2回目のAPI呼び出し)
   └─ messages_for_agent に署名を注入 ✅
   └─ しかし LangChain が API に渡す際に署名が欠落 ❌
   └─ API応答: 空テキスト / MALFORMED_FUNCTION_CALL
```

### LangChainドキュメントの参照

LangChainのドキュメントでは、AIMessageをそのまま履歴に追加することを推奨:

```python
ai_msg = model.invoke(messages)
messages.append(ai_msg)  # ← 再作成しない
tool_result = tool.invoke(tool_call)
messages.append(tool_result)
final_response = model.invoke(messages)
```

しかし、Nexus Arkはログベースの履歴再構築を行うため、この方式を完全に適用するのは困難。

---

## 現実的な対処オプション

### オプションA: Gemini 3 + ツール使用を非推奨
- ツール使用時は Gemini 2.5 を推奨
- UIに警告メッセージを表示
- **影響**: Gemini 3 の最新機能が使えなくなる

### オプションB: 会話履歴のリセット/制限
- 長い会話履歴で問題が発生するため、一定のターン数で履歴をリセット
- **影響**: Nexus Arkのコンセプト（永続的なAIパートナー）に反する

### オプションC: LangChainのアップデートを待つ
- LangChain-Google-GenAI の今後のバージョンで修正される可能性
- **影響**: いつ修正されるか不明

### オプションD: 会話履歴を完全にメモリ上で管理
- ログからの再構築を廃止し、セッション中はメモリ上のメッセージリストを維持
- **影響**: 大規模なアーキテクチャ変更が必要

---

## 参照情報

- [LangChain Google GenAI ドキュメント](https://python.langchain.com/docs/integrations/chat/google_generative_ai/)
- [Google AI Gemini 3 Thinking ドキュメント](https://ai.google.dev/gemini-api/docs/thinking)
- 現在のライブラリバージョン:
  - `langchain-google-genai`: 4.1.2
  - `langchain-core`: 1.2.4

---

## 結論

Gemini 3 + ツール使用の問題は、LangChain-Google-GenAI ライブラリの内部処理に起因する。短い会話（新規ルーム）では正常に動作するが、長い会話履歴では署名の不整合が生じる。

現時点では、ツール使用が必要な場合は **Gemini 2.5 を推奨** する。
