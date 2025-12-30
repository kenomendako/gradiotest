# アバター表情差分システム 仕様書

**最終更新**: 2025-12-30  
**ステータス**: 実装完了（v1.0）

---

## 概要

AIの応答内容に応じて、キャラクターのアバター表情を自動で切り替える機能。静止画モードと動画モードの両方で統一されたインターフェースを提供する。

---

## ファイル構成

### ルームごとのファイル

```
rooms/{room_name}/
├── avatar/
│   ├── idle.png / idle.mp4      # 待機状態（必須）
│   ├── thinking.mp4             # 思考中（オプション）
│   ├── happy.png / happy.mp4    # 嬉しい（オプション）
│   ├── sad.png / sad.mp4        # 悲しい（オプション）
│   └── ...                      # その他の表情
├── profile.png                  # フォールバック用プロフィール画像
└── expressions.json             # 表情設定ファイル
```

### expressions.json の構造

```json
{
  "expressions": ["idle", "thinking", "happy", "sad", "angry", "surprised", "embarrassed"],
  "default_expression": "idle",
  "keywords": {
    "happy": ["嬉しい", "楽しい", "♪", "(*´▽｀*)"],
    "sad": ["悲しい", "残念", "辛い"],
    "angry": ["怒", "許せない", "💢"],
    "surprised": ["驚", "びっくり", "！？"],
    "embarrassed": ["恥ずかしい", "照れ", "///"]
  }
}
```

---

## 表情の検出方法

### 優先順位

1. **タグ検出**: 応答内の `【表情】…{expression_name}…` タグを解析
2. **キーワードマッチング**: `expressions.json` の `keywords` に基づいて応答本文を検索
3. **デフォルト**: 上記で検出できない場合は `idle` を使用

### タグ形式

```
【表情】…happy…
```

- 正規表現パターン: `r'【表情】…([^…]+)…'`
- 応答の末尾に付けることを推奨（AIへの指示として）

### システムプロンプト例

```
【表情について】
応答の最後に【表情】…表情名… を付けてください。
例: 今日はいい天気ですね【表情】…happy…
使用可能な表情: idle, happy, sad, angry, surprised, embarrassed
```

---

## フォールバック機構

表情ファイルが見つからない場合の優先順位:

1. 指定された表情ファイル（例: `avatar/happy.png`）
2. `idle` ファイル（`avatar/idle.png` / `avatar/idle.mp4`）
3. `profile.png`（従来のプロフィール画像）

```
happy.png → idle.png → profile.png
     ↓           ↓           ↓
   見つからない  見つからない  最終フォールバック
```

---

## アバターモード

### 静止画モード (`static`)
- `avatar/{state}.png` を検索
- 見つからなければ `idle.png` → `profile.png` へフォールバック

### 動画モード (`video`)
- `avatar/{state}.mp4 / .webm / .gif` を検索
- 見つからなければ `idle.mp4` へフォールバック
- 動画が一切ない場合は `profile.png` へフォールバック

---

## UI仕様

### 表情管理UIの場所

```
右サイドバー → 「アバターを変更」アコーディオン → 「🎭 表情差分の管理」アコーディオン
```

### UI構成

1. **説明文**: システムプロンプトへの記載方法を案内
2. **表情リスト (DataFrame)**
   - 列: 表情名 / キーワード / ファイル
   - 読み取り専用
3. **追加フォーム**
   - 表情名入力欄
   - キーワード入力欄（カンマ区切り）
   - ファイルアップロードボタン
4. **操作ボタン**
   - 「表情を追加」ボタン
   - 「選択した表情を削除」ボタン（未実装）

---

## 関連コード

| ファイル | 関数/セクション | 説明 |
|---------|----------------|------|
| `constants.py` | `EXPRESSION_*` | 表情関連の定数 |
| `room_manager.py` | `get_expressions_config()` | 表情設定の読み込み |
| `room_manager.py` | `save_expressions_config()` | 表情設定の保存 |
| `room_manager.py` | `get_available_expression_files()` | 利用可能な表情ファイル一覧 |
| `ui_handlers.py` | `get_avatar_html()` | アバターHTML生成 |
| `ui_handlers.py` | `extract_expression_from_response()` | 応答からの表情抽出 |
| `ui_handlers.py` | `refresh_expressions_list()` | UI用表情リスト更新 |
| `ui_handlers.py` | `handle_add_expression()` | 表情追加ハンドラ |
| `ui_handlers.py` | `handle_expression_file_upload()` | ファイルアップロードハンドラ |
| `nexus_ark.py` | 表情管理アコーディオン | UI定義 |

---

## 今後の拡張予定（未実装）

- [ ] 表情の削除UI（DataFrame選択 + 削除ボタン）
- [ ] 表情プレビュー機能
- [ ] 表情ファイルの一括アップロード
- [ ] 表情の優先順位設定
- [ ] 複数表情の同時検出（例: 嬉しいけど照れてる）
- [ ] 表情の持続時間設定（一定時間後にidleに戻る）

---

## 変更履歴

| 日付 | バージョン | 変更内容 |
|------|-----------|---------|
| 2025-12-30 | v1.0 | 初版作成。基本機能の実装完了。 |
