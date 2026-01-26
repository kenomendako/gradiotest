# 自動要約閾値スライダー保存バグ修正レポート

**日付**: 2026-01-05  
**対象**: 自動会話要約設定の閾値スライダー

---

## 問題の概要

自動要約設定のチェックボックスでは「個別設定を保存しました」通知が表示されるが、**閾値スライダーを変更しても通知が出ず、設定が保存されなかった**。

---

## 原因

`room_individual_settings_inputs`リストから`sleep_consolidation_extract_questions_cb`（未解決の問い抽出チェックボックス）が**欠落**していた。

これにより、`handle_save_room_settings`関数への引数が1つズレ、以下の状態になっていた：

| 関数の引数 | 実際に渡されていた値 |
|-----------|-------------------|
| `auto_summary_enabled` | `room_auto_summary_checkbox` ✅ |
| `auto_summary_threshold` | `room_auto_summary_checkbox` ❌ (bool値) |
| `silent` | `room_auto_summary_threshold_slider` ❌ |

結果として、`silent`引数にスライダーの値（整数）が渡され、Pythonの真偽判定で`True`と評価されるため、通知が抑制されていた。

---

## 修正内容

### 変更ファイル

#### `nexus_ark.py` (行2535-2539)

```diff
  sleep_consolidation_compress_cb,
+ sleep_consolidation_extract_questions_cb,  # 追加: 未解決の問い抽出
  room_auto_summary_checkbox,
  room_auto_summary_threshold_slider,
```

加えて、行2668-2690の自動要約イベント登録にも`.then()`で保存処理を連鎖させた。

---

## 検証結果

- ✅ 自動要約チェックボックス変更時に通知が表示される
- ✅ 閾値スライダー変更時に通知が表示される
- ✅ 設定がファイルに正しく保存される

---

## 教訓

- UIコンポーネントリストと関数シグネチャの引数順序は**厳密に一致させる**必要がある
- 新しいUIコンポーネントを追加する際は、関連する入力リストも必ず更新すること
