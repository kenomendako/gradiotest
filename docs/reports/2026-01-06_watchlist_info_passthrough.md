# ウォッチリスト巡回情報伝達問題の修正

**日付**: 2026-01-06  
**ブランチ**: `fix/watchlist-info-passthrough`  
**ステータス**: ✅ 完了

---

## 問題の概要

定期巡回ツールがウォッチリストの更新を検知した後、ペルソナ（AI）が `check_watchlist` ツールを呼び出しても「変更なし」と返される問題。

### 根本原因
1. スケジューラ（`check_watchlist_scheduled`）がコンテンツを取得し、`manager.check_and_update()` でキャッシュを更新
2. `trigger_research_analysis()` でペルソナに通知
3. ペルソナが通知に基づき `check_watchlist` ツールを呼び出す
4. **キャッシュは既に更新済みのため、差分が検出されず「変更なし」**

---

## 修正内容

### 1. コンテンツ要約機能の追加 (`alarm_manager.py`)
- 新関数 `_summarize_watchlist_content()` を追加
- 軽量モデル（`gemini-2.5-flash-lite`）を使用してコンテンツを要約
- APIコスト削減と効率的な情報伝達を実現

### 2. 定期巡回の修正 (`check_watchlist_scheduled`)
- 変更検出時にコンテンツ要約を生成
- 詳細情報（サイト名、URL、差分サマリー、コンテンツ要約）を辞書形式で保存
- `trigger_research_analysis()` に詳細情報を渡す

### 3. 文脈分析プロンプトの改善 (`trigger_research_analysis`)
- ウォッチリスト更新時のプロンプトを改善
- コンテンツ要約を含めて渡す
- ペルソナにツール再実行不要と明示

### 4. 全件チェック機能の修正 (`ui_handlers.py`)
- `handle_watchlist_check_all` を定期巡回と同様に修正
- 手動チェックでもペルソナに分析を依頼可能に
- 開始時のフィードバック通知を追加

### 5. 初回取得時の動作修正 (`watchlist_manager.py`)
- キャッシュがない場合（初回取得）も「変更あり」として扱うよう修正
- キャッシュ削除によるテストが可能に

---

## 変更したファイル

| ファイル | 変更内容 |
|----------|----------|
| `alarm_manager.py` | `_summarize_watchlist_content()` 追加、`check_watchlist_scheduled` と `trigger_research_analysis` の修正 |
| `ui_handlers.py` | `handle_watchlist_check_all` の修正 |
| `watchlist_manager.py` | `detect_changes` で初回取得時も変更ありとして扱う |
| `CHANGELOG.md` | 変更内容を追記 |
| `docs/INBOX.md` | タスクを整理済みに移動 |

---

## 検証結果

1. キャッシュを削除して全件チェックを実行
2. 「初回取得（新規コンテンツ）」として変更検出
3. 軽量モデルによるコンテンツ要約が生成
4. ペルソナに分析が依頼され、チャットログに分析結果が出力

---

## 残課題

- なし（通知問題は `RESEARCH_ANALYSIS_PROMPT` でペルソナの判断に委ねる設計）
