# UI実装パターンガイドライン

Nexus ArkのGradio UIにおける実装パターンと設計原則をまとめたガイドラインです。

---

## 1. 長時間処理のジェネレータパターン

### 問題
長時間処理（RAGインデックス作成など）を通常の関数で実装すると：
- 処理中にUIがフリーズしたように見える
- 途中でCtrl+Cすると全進捗が消失
- ユーザーが処理状況を把握できない

### 解決策: ジェネレータ版メソッド

**命名規則**: `{メソッド名}_with_progress`

**yieldの形式**: `(current_step, total_steps, status_message)`

```python
# rag_manager.py
def update_memory_index_with_progress(self):
    """進捗をyieldするジェネレーター版"""
    yield (0, 0, "開始中...")
    
    for i in range(total_items):
        # 処理...
        yield (i+1, total_items, f"処理中: {i+1}/{total_items}")
        
        # 途中保存（20バッチごと）
        if (i+1) % 20 == 0:
            self._safe_save_index(db, path)
    
    yield (total_items, total_items, "完了")
```

**UIハンドラー側**:
```python
# ui_handlers.py
def handle_memory_reindex(room_name, api_key_name):
    yield "開始中...", gr.update(interactive=False)
    
    for current, total, message in manager.update_memory_index_with_progress():
        yield message, gr.update(interactive=False)
    
    yield "完了", gr.update(interactive=True)
```

### 実装済み例
- `update_memory_index_with_progress` - 記憶索引
- `update_current_log_index_with_progress` - 現行ログ索引

---

## 2. 途中保存パターン

### 問題
大量データ処理中に中断すると、それまでの進捗が全て消失する。

### 解決策
- **20バッチごとに途中保存**（約40秒間隔）
- 処理記録（`processed_*.json`）も同時に更新

```python
SAVE_INTERVAL_BATCHES = 20

for batch_num in range(total_batches):
    # 処理...
    
    if batch_num % SAVE_INTERVAL_BATCHES == 0:
        self._safe_save_index(db, path)
        self._save_processed_record(processed_records)
```

---

## 3. 冪等性ガードパターン

> 詳細は [gradio_notes.md](file:///home/baken/nexus_ark/docs/guides/gradio_notes.md) の「冪等性ガード」セクションを参照

### 問題
UIの初期化時にイベントが複数回発火し、重複処理が発生する。

### 解決策
処理前に「変更があるか」を確認し、なければ早期リターン。

```python
def handle_settings_change(new_value):
    current_value = load_current_value()
    if current_value == new_value:
        return  # 変更なし、何もしない
    
    # 実際の処理...
```

---

## 4. チャンクフィルタリングパターン

### 問題
テキスト分割時に無意味なチャンク（マークダウン記号のみ等）が生成され、検索精度が低下する。

### 解決策
分割後にフィルタリング処理を挟む。

```python
def _filter_meaningful_chunks(self, splits):
    """10文字未満・マークダウン記号のみを除外"""
    MIN_LENGTH = 10
    MEANINGLESS = {'*', '-', '#', '**', '***'}
    
    return [doc for doc in splits 
            if len(doc.page_content.strip()) >= MIN_LENGTH 
            and doc.page_content.strip() not in MEANINGLESS]
```

---

## 5. エラーハンドリングパターン

### 基本形
```python
def handle_something(room_name, api_key_name):
    if not room_name or not api_key_name:
        gr.Warning("必須項目が未選択です。")
        return gr.update(), gr.update()
    
    try:
        # 処理...
        gr.Info("✅ 成功しました")
        return result, gr.update(interactive=True)
    except Exception as e:
        gr.Error(f"エラー: {e}")
        traceback.print_exc()
        return "エラーが発生しました", gr.update(interactive=True)
```

---

## 関連ドキュメント

- [gradio_notes.md](file:///home/baken/nexus_ark/docs/guides/gradio_notes.md) - Gradio固有の注意点
- [UI_LOGIC_INTEGRATION_LESSONS.md](file:///home/baken/nexus_ark/docs/journals/UI_LOGIC_INTEGRATION_LESSONS.md) - 過去の教訓
- [MEMORY_SYSTEM_SPECIFICATION.md](file:///home/baken/nexus_ark/docs/specifications/MEMORY_SYSTEM_SPECIFICATION.md) - 記憶システム仕様
