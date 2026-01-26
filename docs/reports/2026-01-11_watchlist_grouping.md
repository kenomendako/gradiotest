# ウォッチリスト グループ化 & AI自動リスト作成機能

**日付:** 2026-01-11  
**ブランチ:** `feat/watchlist-grouping`  
**ステータス:** ✅ 完了

---

## 問題の概要

ウォッチリストに登録した複数サイトの巡回時刻を個別に変更するのが煩雑だったため、グループ化して一括管理できる機能を追加。さらに、ジャンル指定でサイトを自動収集するAI機能を実装。

---

## 修正内容

### 1. グループ管理機能
- `watchlist.json` v2へのマイグレーション
- グループCRUD操作（作成/更新/削除）
- エントリーのグループ移動時に時刻自動継承
- AIツール3種追加: `create_watchlist_group`, `add_entry_to_group`, `update_group_schedule`

### 2. AI自動リスト作成機能
- ジャンル入力 → Web検索で候補収集 → CheckboxGroupでプレビュー
- 選択したサイトをウォッチリストに一括追加（グループ指定可能）
- Tavily/DuckDuckGo/Google検索を順次使用

### 3. バグ修正
- グループ作成後のドロップダウン更新（`gr.update()`形式に修正）
- TavilySearchパラメータ名（`api_key` → `tavily_api_key`）
- RESEARCH_ANALYSIS_PROMPTのツール名（`edit_research_notes` → `plan_research_notes_edit`）

---

## 変更したファイル

| ファイル | 変更内容 |
|----------|----------|
| `watchlist_manager.py` | グループCRUD操作、v2マイグレーション、時刻自動継承 |
| `ui_handlers.py` | グループ管理ハンドラ、AI検索ハンドラ追加 |
| `nexus_ark.py` | グループ管理タブ、AI自動リスト作成UI追加 |
| `tools/watchlist_tools.py` | 3つのAIツール追加 |
| `tools/web_tools.py` | TavilySearchパラメータ名修正 |
| `agent/prompts.py` | RESEARCH_ANALYSIS_PROMPTのツール名修正 |

---

## 検証結果

- [x] 構文チェック成功
- [x] validate_wiring.py実行済み（エラーなし）
- [x] グループ作成・移動・時刻変更の動作確認
- [x] AI自動リスト作成の動作確認
- [x] Tavily検索バグ修正
- [x] 研究ノートプロンプト修正

---

## 残課題

なし
