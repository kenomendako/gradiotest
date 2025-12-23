# Gemini 3 Flash 設定ガイド

> **最終更新**: 2025-12-23
> **対象モデル**: `gemini-3-flash-preview`

## 概要

Gemini 3 Flash Preview は高速で高性能なモデルですが、正しいパラメータ設定なしでは**281秒の遅延や空の応答**が発生します。このドキュメントは、調査で判明した必須設定と注意事項をまとめたものです。

---

## 必須パラメータ

### 1. `thinking_level`（必須）

Gemini 3 Flash では `thinking_level` パラメータが**必須**です。渡さない場合、モデルは正常に動作しません。

```python
# 利用可能な値（Gemini 3 Flash）
thinking_level = "minimal"  # 最小思考、低レイテンシ（推奨）
thinking_level = "low"       # 低思考
thinking_level = "medium"    # 中程度の思考
thinking_level = "high"      # 深い思考（遅延増加）
```

> ⚠️ **重要**: `minimal` は「思考なし」に近いですが、**完全にオフにはなりません**。
> 公式ドキュメント: "minimal does not guarantee that thinking is off."

### 2. `temperature`（推奨: 1.0）

`thinking_level` を設定する場合、温度は **1.0** が推奨されます。低い温度（0や0.8など）では遅延や空応答が発生する可能性があります。

### 3. `include_thoughts`（渡さない）

Gemini 3 Flash は `include_thoughts=True` を**サポートしていません**。思考トークンは返されません。
このパラメータを渡すと不安定な挙動を引き起こす可能性があるため、**渡さないでください**。

---

## 署名（Thought Signatures）

### 概要

Gemini 3 は「署名」と呼ばれる暗号化された思考状態を返します。これはマルチターン会話で文脈を維持するために**必須**です。

### 必須条件

> "Circulation of thought signatures is required even when set to minimal for Gemini Flash 3."

- **ファンクションコール使用時**: 署名がないと `400 エラー` が発生
- **通常のテキスト生成**: 署名がないと推論能力が大幅に低下

### 自動管理

LangChain SDK (`langchain-google-genai`) を使用している場合、署名の管理は**自動的に**行われます。
手動で REST API を使用する場合は、署名を完全に保持して返送する必要があります。

---

## 長い会話履歴の処理

### 問題

Gemini 3 Flash は長いメッセージリスト（10往復以上）で不安定になります：
- 英語思考のみで会話テキストが生成されない
- `MALFORMED_FUNCTION_CALL` エラー
- 空の応答

### 解決策: 履歴平坦化

古い会話履歴をシステムプロンプトにテキストとして埋め込み、メッセージリストを短く保ちます。

```python
# 現在の設定（agent/graph.py）
GEMINI3_KEEP_RECENT = 2   # メッセージリストに残す件数
GEMINI3_FLATTEN_MAX = 0   # システムプロンプトに埋め込む件数（0=なし）
```

> ⚠️ **注意**: 平坦化されたテキストをシステムプロンプトに追加すると問題が発生することがあります。
> 現時点では `GEMINI3_FLATTEN_MAX = 0`（破棄のみ）が安定しています。

---

## 推奨設定

### Nexus Ark での設定

| 設定項目 | 推奨値 | 備考 |
|---------|--------|------|
| 思考レベル | `high` | 複雑なペルソナには必須。`auto` は内部で `high` に変換 |
| 温度 | 1.0 | 自動設定される |
| APIへの履歴送信 | 任意 | 内部で最新2件に制限 |


### コードでの設定

```python
llm = ChatGoogleGenerativeAI(
    model="gemini-3-flash-preview",
    thinking_level="minimal",  # 必須
    temperature=1.0,           # 推奨
    # include_thoughts は渡さない
)
```

---

## Gemini 3 Pro との違い

| 機能 | Gemini 3 Flash | Gemini 3 Pro |
|------|----------------|--------------|
| `include_thoughts` | ❌ 非対応 | ✅ 対応 |
| `thinking_level` | 必須 | 必須 |
| 思考トークン返却 | ❌ なし | ✅ あり |
| 速度 | 高速 | 低速（深い推論） |

---

## トラブルシューティング

### 281秒遅延 + 空の応答

**原因**: `thinking_level` パラメータが渡されていない

**解決**: `thinking_level="minimal"` を必ず設定

### 英語の思考のみ、会話テキストなし

**原因**: 
1. 長すぎる会話履歴
2. SDK内部Thinkingが英語で出力されている

**解決**:
1. 履歴を制限（最新2件程度）
2. `thinking_level="low"` または `"minimal"` を使用

### `MALFORMED_FUNCTION_CALL` エラー

**原因**: 長い履歴でツール使用時に発生

**解決**: 履歴平坦化を有効にするか、履歴を短く保つ

### 400 エラー（署名関連）

**原因**: ファンクションコール時に署名が欠落

**解決**: LangChain SDKを使用している場合は自動管理されるはず。
手動管理の場合は、`additional_kwargs` 内の署名を完全に保持して返送。

### 同じ設定でも成功/失敗がランダム

**原因**: Gemini 3 Flash Preview API の不安定性

- これは**既知の問題**として広く報告されている
- 同じプロンプト、同じ設定でも成功したり失敗したりする
- `finish_reason: STOP` で正常終了しつつも空のテキストを返すことがある
- API側の問題であり、アプリケーション側での対処には限界がある

**対策**:
1. 空応答が続く場合はUIから履歴送信件数を減らす
2. 安定性が必要な場合は `gemini-2.5-flash-preview-05-20 (Thinking)` を使用
3. APIの安定化を待つ（Preview モデルのため改善される可能性あり）

### 署名ファイルのリセット

**症状**: 過去のセッションの署名状態が原因で不安定になっている可能性がある

**署名ファイルの場所**:
```
characters/<ルーム名>/private/thought_signatures.json
```

**解決**: 上記ファイルを削除してセッションをリセット（新しいセッションとして開始）

---

## 参考リンク

- [Gemini Thinking 公式ドキュメント](https://ai.google.dev/gemini-api/docs/thinking)
- [Thought Signatures ドキュメント](https://ai.google.dev/gemini-api/docs/thought-signatures)
- [LangChain Google GenAI](https://python.langchain.com/docs/integrations/chat/google_generative_ai)

---

## 変更履歴

- **2025-12-23**: 初版作成。Gemini 3 Flash の必須パラメータと設定を文書化。
