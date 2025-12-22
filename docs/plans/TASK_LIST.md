# 📋 Nexus Ark タスクリスト

**目標**: 年内リリース  
**配布方式**: Portable Python同梱（[distribution_system_plan.md](file:///c:/Users/baken/OneDrive/%E3%83%87%E3%82%B9%E3%82%AF%E3%83%88%E3%83%83%E3%83%97/gradio_github/gradiotest/docs/plans/distribution_system_plan.md) 参照）

---

## 🔴 優先度: クリティカル（リリースブロッカー）

これらが解決しないとリリースできない

### バグ修正

- [x] **マルチモーダル添付の修正**
  - ✅ 複数画像添付: `file_count="multiple"` 追加
  - ✅ MP3音声認識: `{"type": "file", ...}` 形式で送信
  - ✅ AI応答二重表示: チャンク処理修正
  - ⚠️ MP4動画: API制限のため未対応（将来の課題）
  - レポート: [2025-12-20_multimodal_fix_report.md](file:///c:/Users/baken/OneDrive/%E3%83%87%E3%82%B9%E3%82%AF%E3%83%88%E3%83%83%E3%83%97/gradio_github/gradiotest/docs/reports/2025-12-20_multimodal_fix_report.md)

- [x] **自律行動の重複発火バグ**
  - ハイブリッド方式（タイムスタンプ＋メモリ内フラグ）で修正
  - レポート: [2025-12-21_autonomous_action_duplicate_fix.md](file:///c:/Users/baken/OneDrive/%E3%83%87%E3%82%B9%E3%82%AF%E3%83%88%E3%83%83%E3%83%97/gradio_github/gradiotest/docs/reports/2025-12-21_autonomous_action_duplicate_fix.md)

- [x] **タイムスタンプ二重付記バグ**
  - AIが日本語曜日形式でタイムスタンプを生成する問題を修正
  - 正規表現を日本語/英語両対応に拡張
  - レポート: [2025-12-21_timestamp_duplicate_fix.md](file:///c:/Users/baken/OneDrive/%E3%83%87%E3%82%B9%E3%82%AF%E3%83%88%E3%83%83%E3%83%97/gradio_github/gradiotest/docs/reports/2025-12-21_timestamp_duplicate_fix.md)

- [x] **モデル名付記バグ**
  - 個別設定でモデル変更後、古いモデル名がタイムスタンプに付記される問題を修正
  - さらにAI模倣タイムスタンプ問題（AIが過去の応答のタイムスタンプを模倣）を根本修正
  - レポート: [2025-12-22_ai_timestamp_mimicry_fix.md](file:///c:/Users/baken/OneDrive/デスクトップ/gradio_github/gradiotest/docs/reports/2025-12-22_ai_timestamp_mimicry_fix.md)

### 安定性

- [ ] **使用モデルリストの精査**
  - 動作確認済みモデルのみに絞る
  - Gemini 3 Flash Previewは応答遅延問題あり（[gradio_notes.md](file:///c:/Users/baken/OneDrive/%E3%83%87%E3%82%B9%E3%82%AF%E3%83%88%E3%83%83%E3%83%97/gradio_github/gradiotest/docs/guides/gradio_notes.md) レッスン33）
  - おすすめモデルだけのリストを作成

- [ ] **モデルリストのUI管理機能強化**
  - UI上からモデルの削除を可能にする
  - デフォルトモデルリストで上書きして初期状態に戻す機能

- [/] **Gemini 3シリーズの空応答・思考タグ問題**
  - 空応答が頻発（思考レベル変更で解消せず）
  - ツール使用のみ成功して応答テキストが空になるケースあり
  - `[THOUGHT]`タグを開始するが閉じタグがなく全文が思考ログ化
  - ⏸️ 様子見中: 現在は問題未再現、デバッグログ追加済み
  - レポート: [2025-12-21_gemini3_debug_log_addition.md](file:///c:/Users/baken/OneDrive/%E3%83%87%E3%82%B9%E3%82%AF%E3%83%88%E3%83%83%E3%83%97/gradio_github/gradiotest/docs/reports/2025-12-21_gemini3_debug_log_addition.md)

---

## 🟠 優先度: 高（リリース前に対応したい）

ユーザー体験に大きく影響

### 機能修正

- [ ] **ChatGPTエクスポートインポート機能の修正**
  - スレッド途中までしかインポートされない
  - memory（moonlight?）の内容を誤って読み込んでいる可能性
  - ZIP丸ごと受け取り対応

### コスト削減・効率化

- [ ] **送信コンテキストの最適化（APIコスト削減）**
  - コアメモリ作成を少ない文字数に
  - 記憶検索で渡す情報の見直し
  - ツール情報の整理
  - GeminiAPI無料枠制限対策として重要

- [ ] **話題クラスタのコンテキスト制御** 🆕
  - 「話題クラスタ」をAPI送信コンテキストに含めるかどうかを選択可能にする
  - コスト削減にも貢献

- [ ] **送信トークン数の表示機能** 🆕
  - 記憶情報等を付加した後のトータル送信量を表示
  - 送信後（送信コンテキスト確定後）に表示

### UI修正

- [x] **主観的記憶（日記）のスクロールバー**
  - `#memory_txt_editor_code textarea` として修正完了

- [x] **個別設定の即時保存（ポップアップあり）**
  - 共通設定に合わせてポップアップ通知を有効化完了

- [x] **空応答のシステムメッセージ化**
  - ロジック実装・表示形式の修正完了

- [x] **モデルリストの最終整理**
  - `gemini-1.5` 系の削除、順序調整、注釈対応完了

- [x] **システムメッセージから再生成時の挙動修正** ✅
  - SYSTEMメッセージもAGENTと同様に扱い、直前のユーザーメッセージから再生成するよう修正
  - システムメッセージを削除して直前のユーザーメッセージを再送信する処理にする

- [ ] **チャット発言のコピー/編集時にタイムスタンプ除外**
  - ヘッダーやフッター（タイムスタンプ）を除外したい

- [x] **チャット送信キーの変更** → [002_shift_enter_submit_abandon.md](file:///c:/Users/baken/OneDrive/デスクトップ/gradio_github/gradiotest/docs/decisions/002_shift_enter_submit_abandon.md)
  - ~Shift+EnterではなくCtrl+Enterで送信するように変更~
  - Gradioの仕様上、実現不可のため断念

- [ ] **ルーム個別設定の保存ボタン整理**
  - 基本は即時保存のため不要なボタンを削除
  - ボタンでの保存が必要な個所のみ個別に保存ボタンを設置

- [ ] **空応答時のチャットログヘッダー統一**
  - 「Nexus Ark」と「システム」が混在しているので統一
  - ルールをドキュメント化して今後の迷いを防止

- [x] **デバッグモードの絵文字削除** ✅ 完了
  - 共通設定のデバッグモードの「🐛」絵文字を削除
  - 䅋が苦手なユーザーへの配慮

---

## 🟡 優先度: 中（リリース後でも可、余裕があれば対応）

### 機能改善

- [ ] **グループ会話の司会役AI（Supervisor）の改善**
  - 不安定・処理が遅い
  - 参照: [supervisor_implementation.md](file:///c:/Users/baken/OneDrive/%E3%83%87%E3%82%B9%E3%82%AF%E3%83%88%E3%83%83%E3%83%97/gradio_github/gradiotest/docs/plans/supervisor_implementation.md)

- [ ] **話題クラスタ更新の改善**
  - 動作がよくわからない
  - 埋め込みモード同期は修正済み

- [ ] **Gradio起動時の外部接続設定UI**
  - ユーザー要望
  - `server_name="0.0.0.0"` のtrue/false切り替え
  - 参照: [gradio_notes.md](file:///c:/Users/baken/OneDrive/%E3%83%87%E3%82%B9%E3%82%AF%E3%83%88%E3%83%83%E3%83%97/gradio_github/gradiotest/docs/guides/gradio_notes.md) レッスン10

### アラーム・タイマー関連

- [ ] **アラームの日付指定・期間指定・祝日除外**
  - 単発アラームや期間限定、祝日を考慮した設定

- [ ] **タイマー・ポモドーロの一覧表示**
  - 複数仕掛けている時に便利なよう一覧できるように

---

## 🟢 優先度: 低（将来機能）

- [ ] **AIペルソナ「お出かけ」機能**
  - 人格データ+直近ログをコンパクトに吐き出し
  - 外部アプリ（Antigravity等）で会話
  - 会話ログをNexus Arkにインポート・合流（帰宅）
  - 設計が必要な大きな機能

---

## 📦 配布準備（並行作業）

[distribution_system_plan.md](file:///c:/Users/baken/OneDrive/%E3%83%87%E3%82%B9%E3%82%AF%E3%83%88%E3%83%83%E3%83%97/gradio_github/gradiotest/docs/plans/distribution_system_plan.md) に基づく実装

- [ ] `version.json` 作成
- [ ] `update_manager.py` 実装
- [ ] `初回セットアップ.bat` 作成
- [ ] [nexus_ark.py](file:///c:/Users/baken/OneDrive/%E3%83%87%E3%82%B9%E3%82%AF%E3%83%88%E3%83%83%E3%83%97/gradio_github/gradiotest/nexus_ark.py) にアップデート確認UI追加
- [ ] `ネクサスアーク.bat` 修正
- [ ] 手動検証とドキュメント作成

---

*最終更新: 2025-12-22*
