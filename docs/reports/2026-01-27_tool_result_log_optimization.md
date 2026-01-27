# ツール出力のログ保存最適化レポート (2026-01-27)

## 概要
ツール実行結果（生データ）がそのまま会話ログに保存されることによるトークン消費の肥大化と、それに伴うAPIコストの増大を抑制するため、ログ保存ロジックの最適化を実施しました。

## 課題
- AIがファイルを読み取ったり（`read_project_file`）、RAG検索を実行したりする際、数千〜数万文字のデータが `log.txt` に書き込まれていた。
- これにより、次のターンで AIに送信される過去の履歴（コンテキスト）が急激に膨れ上がり、コスト増と記憶の想起精度低下を招いていた。

## 対策
システム定数 `constants.TOOLS_SAVE_ANNOUNCEMENT_ONLY` を活用し、高ボリュームなツール出力を「実行事実のアナウンス」のみの保存に切り替えました。
※ AIは実行したターンの内側ではフルデータを参照できるため、性能への悪影響はありません。

### 最適化対象に追加したツール (12種類)
1.  `read_project_file`
2.  `list_project_files`
3.  `read_main_memory`
4.  `read_secret_diary`
5.  `read_creative_notes`
6.  `read_research_notes`
7.  `read_full_notepad`
8.  `read_world_settings`
9.  `read_memory_context`
10. `search_memory`
11. `search_knowledge_base`
12. `read_url_tool`

## 検証結果
- **ログのダイエット**: ツール実行後の `log.txt` に生データが記録されず、アナウンスのみが残ることを確認。
- **AIの応答性**: ツール実行直後のターンでは、AIが取得したデータを正しく認識して返答できていることを確認。
- **整合性**: `alarm_manager.py` や `timers.py` における出力処理も `constants.py` の設定を正しく参照していることを確認。

## 結論
本改修により、長期的な会話におけるコンテキスト消費効率が劇的に改善されました。特に開発支援機能やRAG検索を多用する環境において、大きなコスト削減効果が期待できます。
