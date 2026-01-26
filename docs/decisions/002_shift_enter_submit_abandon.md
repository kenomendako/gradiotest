# Shift+Enter送信無効化の断念

**日付**: 2025-12-22  
**ステータス**: 断念

## 背景

チャット入力欄での誤送信を防ぐため、Shift+Enterでの送信を無効化し、Ctrl+Enterでの送信に変更したいという要望があった。コーディングエディタと操作が異なるため、誤送信が頻発していた。

## 試行した方法

1. **カスタムJavaScript（`custom_js`）によるキーイベント制御**
   - `document.addEventListener('keydown', ...)` でEnterキーイベントをインターセプト
   - `e.stopPropagation()` や `e.preventDefault()` で送信を阻止しようとした
   - **結果**: JavaScriptが期待通りに動作せず、Gradioのイベントハンドリングを上書きできなかった

2. **`submit_btn=False` による内蔵送信ボタンの無効化**
   - Gradioのドキュメントによると、`submit_btn=False`でEnterキー送信も無効化されるはず
   - 別途送信ボタンを設置してクリックイベントで送信する設計に変更
   - **結果**: Shift+Enterでの送信は依然として有効だった

3. **`submit_btn="送信"` によるカスタムテキストボタン**
   - 送信ボタンのテキストをカスタマイズ
   - **結果**: 送信動作に変化なし

## 結論

Gradioの`MultimodalTextbox`コンポーネントは、Shift+Enterでの送信動作がハードコードされており、JavaScript やパラメータ変更では無効化できないことが判明した。

## 代替案

- **今後のGradioバージョンアップで対応される可能性を待つ**
- **Gradioのソースコードを直接パッチする**（保守性の観点から非推奨）
- **別のUIフレームワークへの移行**（コスト大）

## 影響

現状のShift+Enter送信動作を維持する。ユーザーは引き続き誤送信に注意が必要。

## 参照

- Gradio MultimodalTextboxドキュメント
- [TASK_LIST.md](../plans/TASK_LIST.md) のUI改善タスク
