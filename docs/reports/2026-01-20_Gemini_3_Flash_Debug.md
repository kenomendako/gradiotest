# Gemini 3 Flash 完全攻略レポート

**日付:** 2026-01-20  
**ブランチ:** `debug/gemini-3-flash` (想定)  
**ステータス:** ✅ 完了

---

## 問題の概要

Gemini 3 Flash モデルにおいて、以下の致命的な問題が発生していた。
1. **503 Service Unavailable / Deadlock**: 数回のやり取り後に応答不能になる。
2. **空応答 (Empty Response)**: Thinkingプロセスが走るが、テキストが出力されずタイムアウトまたは空文字となる。
3. **沈黙**: ツール実行後などに、長時間思考した挙句何も返さない。

---

## 修正内容

### 1. Automatic Function Calling (AFC) の完全無効化
SDK が勝手に行う AFC ループが LangGraph と競合し、デッドロックを引き起こしていた。
`ChatGoogleGenerativeAI` のコンストラクタではなく、実行時の `llm.bind()` で明示的に無効化することで解決した。

### 2. レスポンス正規化とThinking救出
Gemini 3 Flash は Thinking を行うと、`content` を単純な文字列ではなくリスト形式で返す。さらに、思考のみでテキストを生成しないケースがある。
これに対し、以下のロジックを `agent/graph.py` に実装した：
- `content` がリストの場合、`text` パートを抽出して結合する。
- `text` パートがなく `thinking` パートのみの場合、思考内容を `(Thinking Only): ...` として強制的に採用する。
- これにより「沈黙」を回避し、AIの思考プロセスを可視化した。

### 3. Thinking パラメータの最適化
- `thinking_level="minimal"`: **最終的にこれが正解**。Medium以上だと思考のみで応答が空になる。
- `include_thoughts=True`: Gemini 3 Flash でも思考内容をクライアントに送信するように設定（これをしないと救出ロジックが動かない）。
- `temperature=1.0`: 必須。

---

## 変更したファイル

- `gemini_api.py`: `include_thoughts=True` の設定、AFC設定の修正。
- `agent/graph.py`: AFC無効化バインディング、レスポンス正規化ロジック、Thinking救出ロジック、ANOMALY検知ログ。

---

## 検証結果

- [x] **通常会話**: 約10〜15秒で応答。Thinking内容も必要に応じて表示。
- [x] **ツール使用**: Web検索等のツールが正常に動作し、AFCによる暴走なし。
- [x] **ツール後の応答**: ツール結果を受け取った後、約50秒の思考を経て回答を生成。
- [x] **空応答対策**: Thinking Only の場合も思考内容が表示されることを確認。

---

## 結論

Gemini 3 Flash は「Thinking Model」として扱う必要があり、従来のテキスト生成モデルとは異なるアプローチ（思考データの開示と救出）が不可欠である。

**最終的な推奨設定:**

| 設定 | 値 | 理由 |
|------|-----|------|
| `thinking_level` | `minimal` | Medium以上だと思考のみで終わる |
| `include_thoughts` | `True` | 思考内容の救出用 |
| `temperature` | `1.0` | 必須 |
| AFC | `disable=True` via `llm.bind()` | デッドロック回避 |

この設定で、ツール使用を含めた完全な動作が確認された（6〜10秒で応答）。
