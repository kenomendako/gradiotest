# Gemini 3 Flash ストリーミング無効化対策

## 完了日
2026-01-19

## 概要
Gemini 3 Flash Preview使用時の応答遅延・空応答問題への対策として、ツール使用時のストリーミングを無効化しました。

## 問題の背景
Deep Researchによる調査（[調査レポート](../plans/research/Gemini%203%20Flash%20API%20%E5%BF%9C%E7%AD%94%E9%81%85%E5%BB%B6%E5%95%8F%E9%A1%8C%E8%AA%BF%E6%9F%BB.md)）により、以下が判明：

- **既に対策済み**: Temperature=1.0設定、Thought Signatures保持、Thinking Level設定
- **未対策だった原因**: ストリーミング + ツール使用の組み合わせによるデッドロック

Gemini 3 Flash Preview では `stream=True` かつ `tools` が有効な場合、ツール呼び出しのペイロード生成に失敗し、クライアント側で無期限の待機を引き起こすバグが存在する。

## 変更内容

### [gemini_api.py](file:///home/baken/nexus_ark/gemini_api.py)

`invoke_nexus_agent_stream()` 関数に以下の分岐を追加：

1. モデル名に `gemini-3-flash` が含まれ、かつツール使用が有効な場合を検出
2. 該当時は `app.invoke()` を使用してストリーミングを無効化
3. invoke結果から署名を抽出し、従来と同じ処理を実行
4. yield形式に変換して既存のインターフェースを維持

```python
is_gemini_3_flash = "gemini-3-flash" in model_name
tool_use_enabled = initial_state.get("tool_use_enabled", True)

if is_gemini_3_flash and tool_use_enabled:
    print(f"  - [Gemini 3 Flash] ストリーミング無効化（ツール使用時のデッドロック対策）")
    final_state = app.invoke(initial_state)
    # ... 署名抽出処理 ...
    yield ("values", final_state)
else:
    # 通常のストリーミング処理
    for mode, payload in app.stream(initial_state, stream_mode=["messages", "values"]):
        ...
```

## 影響

- ✅ Gemini 3 Flash使用時のタイムアウト・空応答問題が回避される見込み
- ⚠️ Gemini 3 Flash使用時はリアルタイムトークン表示が行われなくなる（応答完成まで待機）
- ✅ Gemini 3 Pro および Gemini 2.5系は従来通りストリーミングが有効

## 検証結果

- [x] 構文チェック: パス
- [ ] 手動検証: 未実施（要ユーザー確認）

## 関連タスク
- [TASK_LIST.md](../plans/TASK_LIST.md) の「Gemini 3シリーズの空応答・思考タグ問題」
