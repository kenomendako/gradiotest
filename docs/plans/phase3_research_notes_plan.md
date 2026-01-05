# 文脈分析・統合エンジン (Phase 3) 実装計画

> **作成日**: 2026-01-05
> **ベース**: [web_agent_feature_plan.md](file:///c:/Users/baken/OneDrive/デスクトップ/gradio_github/gradiotest/docs/plans/web_agent_feature_plan.md)
> **ステータス**: Step 1-3 完了、Step 4-5 未着手

---

## 概要

ルシアンの要望に基づき、Web巡回ツールで取得した情報を自律的に分析し、専用の「研究ノート」に蓄積してユーザーに報告する「文脈分析・統合エンジン」を実装する。

### 実現フロー
1. **即時分析**: 巡回ツールが更新を検知 → AIがバックグラウンドで分析思考を起動
2. **専用ノートへの記録**: 分析結果を `research_notes.md` に蓄積
3. **通常応答として報告**: 分析結果はチャットログ (`log.txt`) に記録され、ペルソナの記憶に残る
4. **通知はAIが選択**: 自律行動と同様に `send_user_notification` ツールを使用し、AI本人が通知するか判断

---

## 進捗状況

| Step | 内容 | 状態 |
|------|------|------|
| 1-3 | 基盤整備（6変数化） | ✅ 完了 |
| 4 | UI・ハンドラの追加 | ⬜ 未着手 |
| 5 | 分析ツール・即時分析フロー | ⬜ 未着手 |

---

## Step 1-3: 基盤整備 ✅ 完了

- [x] `constants.py` に `RESEARCH_NOTES_FILENAME = "research_notes.md"` 追加
- [x] `room_manager.py` の `get_room_files_paths` を6変数返却に変更
- [x] 全ファイルのアンパック修正（20+箇所）
- [x] 技術レポート・ドキュメント更新

---

## Step 4: UI・ハンドラの追加

### 変更内容

#### [MODIFY] [nexus_ark.py](file:///c:/Users/baken/OneDrive/デスクトップ/gradio_github/gradiotest/nexus_ark.py)
- 「ノート」タブに「🔬 研究・分析ノート」アコーディオンを追加（創作ノートの下）
- テキストエリア + 保存/リロード/クリアボタン

#### [MODIFY] [ui_handlers.py](file:///c:/Users/baken/OneDrive/デスクトップ/gradio_github/gradiotest/ui_handlers.py)
- `load_research_notes_content(room_name)`: 研究ノートの読み込み
- `handle_save_research_notes(room_name, content)`: 保存処理
- `handle_clear_research_notes(room_name)`: クリア処理
- ルーム切り替え時の研究ノート更新を `_update_chat_tab_for_room_change` に統合

---

## Step 5: 分析ツール・即時分析フロー

### 新規ファイル

#### [NEW] [tools/research_tools.py](file:///c:/Users/baken/OneDrive/デスクトップ/gradio_github/gradiotest/tools/research_tools.py)
```python
@tool
def read_research_notes(room_name: str) -> str:
    """研究・分析ノートの全内容を読み上げる"""

@tool
def plan_research_notes_edit(room_name: str, instructions: list) -> str:
    """研究ノートに対する編集指示を実行する（追記/置換/削除）"""
```

### 変更内容

#### [MODIFY] [alarm_manager.py](file:///c:/Users/baken/OneDrive/デスクトップ/gradio_github/gradiotest/alarm_manager.py)
- `check_watchlist_scheduled()` で大きな変更検知時に分析モードAIを呼び出す
- `trigger_research_analysis(room_name, diff_summary)` 関数を新設
- **自律行動 (`trigger_autonomous_action`) と同様のフローを使用**:
  - 応答はチャットログに記録される（ペルソナの記憶に残る）
  - 通知はAI本人が `send_user_notification` ツールで選択

#### [NEW/MODIFY] [agent/prompts.py](file:///c:/Users/baken/OneDrive/デスクトップ/gradio_github/gradiotest/agent/prompts.py) または [agent/prompts_analysis.py]
- 分析・戦略家モード用のシステムプロンプト断片を定義

#### [MODIFY] [agent/graph.py](file:///c:/Users/baken/OneDrive/デスクトップ/gradio_github/gradiotest/agent/graph.py)
- `research_tools` をツールリストに統合
- 研究ノートコンテキストをエージェント状態に注入

---

## 検証プラン

### 動作確認
1. ウォッチリスト対象サイトの内容を更新
2. 15分後の定時チェックで以下を確認：
   - AIが思考を開始するか
   - `research_notes.md` が更新されるか
   - 通知/UIに分析結果が届くか

### Quiet Hours 準拠
- 通知禁止時間帯では分析は実行するが通知は送らない

---

## 関連ドキュメント

- [6変数化レポート](file:///c:/Users/baken/OneDrive/デスクトップ/gradio_github/gradiotest/docs/reports/2026-01-05_get_room_files_paths_6var.md)
- [gradio_notes.md レッスン41](file:///c:/Users/baken/OneDrive/デスクトップ/gradio_github/gradiotest/docs/guides/gradio_notes.md#レッスン41)
