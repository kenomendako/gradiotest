# レポート: Web巡回ツールのリスト削除エラー修正 (2026-01-17)

## 概要
Web巡回ツールのウォッチリストからエントリを削除しようとすると、`ValueError: The truth value of a DataFrame is ambiguous` が発生してクラッシュする問題を修正しました。

## 修正内容
`nexus_ark.py` の `delete_selected_wrapper` 関数において、Gradioの `gr.Dataframe` から渡される `df_data` の真偽値判定（`if df_data:`）が原因でエラーが発生していました。この判定を `if df_data is not None:` に変更し、さらに `df_data` がリスト型か Pandas DataFrame 型かを判定して適切に行を検索するロジックに改善しました。

### 修正コード（抜粋）
```python
            if df_data is not None:
                import pandas as pd
                if isinstance(df_data, pd.DataFrame):
                    for _, row in df_data.iterrows():
                        if str(row.iloc[0]) == selected_id:
                            selected_row = row.tolist()
                            break
                elif isinstance(df_data, list):
                    for row in df_data:
                        if str(row[0]) == selected_id:
                            selected_row = row
                            break
```

## 検証結果
検証スクリプト `reproduce_df_issue.py` を作成し、以下のケースで正しく動作することを確認しました。
- リスト形式のデータ入力
- Pandas DataFrame形式のデータ入力（以前はここでクラッシュ）
- None 入力

## 影響範囲
Web巡回ツールのウォッチリスト削除機能のみに限定されており、他への影響はありません。
