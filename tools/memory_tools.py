# tools/memory_tools.py (v21: Memory Search Redesign)

import re
from langchain_core.tools import tool
import json
import datetime
import room_manager
from room_manager import get_room_files_paths
from memory_manager import load_memory_data_safe
from gemini_api import get_configured_llm
from typing import List, Dict, Any
import traceback
import os
import constants
import utils # <-- 追加が必要な場合
import glob
from pathlib import Path
import random 
import config_manager

@tool
def recall_memories(query: str, room_name: str, api_key: str) -> str:
    """
    あなたの過去の体験、会話、思い出を検索します。
    ユーザーとの過去の出来事や、自分の日記・感情の記録を思い出したい場合に使用します。
    検索対象: 日記、過去の会話ログアーカイブ、エピソード記憶、夢の記録
    query: 思い出したい事柄に関する自然言語のキーワード（例：「初めて会った日のこと」「旅行の話」）
    """
    if not query or not room_name:
        return "【エラー】検索クエリとルーム名が必要です。"
    
    if not api_key:
        return "【エラー】APIキーが必要です。"

    print(f"--- 統合記憶検索(RAG)開始: クエリ='{query}', ルーム='{room_name}' ---")
    
    try:
        import rag_manager
        rm = rag_manager.RAGManager(room_name, api_key)
        
        # 検索実行（日記・過去ログ・エピソード記憶・夢日記を対象）
        # 知識ベース（knowledge）は除外されている
        results = rm.search(query, k=10, score_threshold=0.80)
        
        # 知識ベースの結果を除外（念のため）
        memory_results = [r for r in results if r.metadata.get("type") != "knowledge"]
        
        print(f"  - RAG検索結果: 全{len(results)}件中、記憶{len(memory_results)}件")
        
        if not memory_results:
            return f"【検索結果】「{query}」に関する記憶は見つかりませんでした。"
        
        result_text = f"【記憶検索の結果：「{query}」】\n\n"
        for doc in memory_results[:7]:  # 最大7件
            source = doc.metadata.get("source", "不明")
            doc_type = doc.metadata.get("type", "unknown")
            
            # ソースタイプに応じたラベル付け
            if doc_type == "diary":
                label = "日記"
            elif doc_type == "log_archive":
                label = "過去の会話"
            elif doc_type == "episodic_memory":
                date = doc.metadata.get("date", "")
                label = f"エピソード記憶（{date}）"
            elif doc_type == "dream_insight":
                label = "夢の記録"
            else:
                label = source
            
            # 長すぎる場合はトリミング
            content = doc.page_content
            if len(content) > 500:
                content = content[:500] + "..."
            result_text += f"--- [{label}] ---\n{content}\n\n"
        
        return result_text.strip()
        
    except Exception as e:
        print(f"  - RAG検索エラー: {e}")
        traceback.print_exc()
        return f"【エラー】記憶検索中にエラーが発生しました: {e}"

@tool
def search_past_conversations(query: str, room_name: str, api_key: str, exclude_recent_messages: int = 0) -> str:
    """
    【キーワード完全一致検索】通常の記憶検索（recall_memories）で見つからない場合に使用します。
    過去の会話ログから、特定の単語やフレーズを含む発言を探し出します。
    recall_memoriesとは異なり、意味ではなくキーワードの一致で検索するため、
    「あの時〇〇って言ってたよね？」のような引用探しに適しています。
    """

    if not query or not room_name or not api_key:
        return "【エラー】検索クエリ、ルーム名、APIキーは必須です。"

    search_keywords = query.lower().split()

    current_config = config_manager.load_config_file()
    val = current_config.get("last_api_history_limit_option", "all")
    history_limit_option = str(val).strip()
    
    # 現在送信中のログを除外するための件数を計算
    # 「all」の場合でも、最低限のデフォルト除外（20ターン = 約40メッセージ）を適用
    # これにより「今話している内容」がノイズとして混入することを防止
    DEFAULT_EXCLUDE_TURNS = 20  # デフォルトで20ターン分を除外
    
    if history_limit_option == "all":
        # 「全履歴送信」設定でも、検索時は最新20ターン分を除外
        config_exclude_count = DEFAULT_EXCLUDE_TURNS * 2 + 2
    elif history_limit_option.isdigit():
        config_exclude_count = int(history_limit_option) * 2 + 2
    else:
        config_exclude_count = DEFAULT_EXCLUDE_TURNS * 2 + 2
    
    final_exclude_count = max(exclude_recent_messages, config_exclude_count)
    
    print(f"  - [Search Debug] 除外数決定: {final_exclude_count} (引数: {exclude_recent_messages}, 設定: {config_exclude_count})")

    print(f"--- 過去ログ検索実行 (ルーム: {room_name}, クエリ: '{query}') ---")
    try:
        base_path = Path(constants.ROOMS_DIR) / room_name
        search_paths = [str(base_path / "log.txt")]
        search_paths.extend(glob.glob(str(base_path / "log_archives" / "*.txt")))
        search_paths.extend(glob.glob(str(base_path / "log_import_source" / "*.txt")))

        found_blocks = []
        date_patterns = [
            re.compile(r'(\d{4}-\d{2}-\d{2}) \(...\) \d{2}:\d{2}:\d{2}'),
            re.compile(r'###\s*(\d{4}-\d{2}-\d{2})')
        ]
        
        for file_path_str in search_paths:
            file_path = Path(file_path_str)
            if not file_path.exists() or file_path.stat().st_size == 0:
                continue
            
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            header_indices = [i for i, line in enumerate(lines) if re.match(r"^(## (?:USER|AGENT|SYSTEM):.*)$", line.strip())]
            if not header_indices:
                continue

            search_end_line = len(lines)
            
            if file_path.name == "log.txt" and final_exclude_count > 0:
                msg_count = len(header_indices)
                if msg_count <= final_exclude_count:
                    print(f"  - [Search Debug] log.txt をスキップ (Msg数 {msg_count} <= 除外数 {final_exclude_count})")
                    continue
                else:
                    # 後ろから N 個目のヘッダーの位置を特定
                    cutoff_header_index = header_indices[-final_exclude_count]
                    search_end_line = cutoff_header_index
                    print(f"  - [Search Debug] log.txt を部分検索 (Msg数 {msg_count}, 範囲: 行 0〜{search_end_line})")
                    
            processed_blocks_content = set()

            for i, line in enumerate(lines[:search_end_line]):
                if any(k in line.lower() for k in search_keywords):
                    start_index = 0
                    for h_idx in reversed(header_indices):
                        if h_idx <= i:
                            start_index = h_idx
                            break
                    
                    end_index = len(lines)
                    for h_idx in header_indices:
                        if h_idx > start_index:
                            end_index = h_idx
                            break
                    
                    block_content = "".join(lines[start_index:end_index]).strip()
                    if block_content not in processed_blocks_content:
                        processed_blocks_content.add(block_content)
                        
                        block_date = None
                        for pattern in date_patterns:
                            matches = list(pattern.finditer(block_content))
                            if matches:
                                block_date = matches[-1].group(1)
                                break
                        
                        found_blocks.append({
                            "content": block_content,
                            "date": block_date,
                            "source": file_path.name
                        })
                        
        if not found_blocks:
            return f"【検索結果】過去の会話ログから「{query}」に関する情報は見つかりませんでした。"

        # 1. 日付順（新しい順）にソート
        found_blocks.sort(key=lambda x: x.get('date') or '0000-00-00', reverse=True)
        
        # 2. 時間帯別枠取り：新しい記憶と古い記憶の両方をカバー
        # - 新しい方から最大2件
        # - 古い方から最大2件（重複回避）
        # これにより「最近の発言」と「昔の発言」の両方が検索結果に含まれる
        if len(found_blocks) <= 4:
            # 4件以下ならそのまま全部返す
            limited_blocks = found_blocks
        else:
            newest = found_blocks[:2]  # 新しい方から2件
            oldest = found_blocks[-2:]  # 古い方から2件
            # 重複を除いて結合（新しい順を維持）
            limited_blocks = newest + [b for b in oldest if b not in newest]
            print(f"  - [Search] 時間帯別枠取り: 新{len(newest)}件 + 古{len([b for b in oldest if b not in newest])}件 = {len(limited_blocks)}件")

        result_parts = [f'【過去の会話ログからの検索結果：「{query}」】\n']
        
        for res in limited_blocks:
            date_str = f"日付: {res['date']}頃" if res['date'] else "日付不明"
            source_file = res['source']
            raw_content = res['content']
            
            # 生テキストをそのまま提示
            result_parts.append(f"- [出典: {source_file}, {date_str}]\n{raw_content}")
        
        final_result = "\n\n".join(result_parts)
        return final_result

    except Exception as e:
        traceback.print_exc()
        return f"【エラー】過去ログ検索中に予期せぬエラーが発生しました: {e}"

@tool
def search_memory(query: str, room_name: str, api_key: str) -> str:
    """
    あなたの長期記憶（日記アーカイブを含む）の中から、指定されたクエリに最も関連する日記の断片を検索します。
    ユーザーとの会話で過去の出来事を思い出す必要がある場合に使用します。
    query: 検索したい事柄に関する自然言語のキーワード。（例：「初めて会った日のこと」）
    """
    if not query or not room_name:
        return "【エラー】検索クエリとルーム名が必要です。"
    
    if not api_key:
        return "【エラー】APIキーが必要です。"

    print(f"--- 記憶検索(RAG)開始: クエリ='{query}', ルーム='{room_name}' ---")
    
    try:
        import rag_manager
        rm = rag_manager.RAGManager(room_name, api_key)
        results = rm.search(query, k=10, score_threshold=0.80)
        
        # 日記タイプのみをフィルタリング
        diary_results = [r for r in results if r.metadata.get("type") == "diary"]
        
        print(f"  - RAG検索結果: 全{len(results)}件中、日記{len(diary_results)}件")
        
        if not diary_results:
            # 日記が見つからない場合は全結果を使用（フォールバック）
            if results:
                print(f"  - 日記がないため、全結果を使用します")
                diary_results = results[:5]
            else:
                return f"【検索結果】「{query}」に関する記憶は見つかりませんでした。"
        
        result_text = f"【記憶検索の結果：「{query}」】\n\n"
        for doc in diary_results[:5]:  # 最大5件
            source = doc.metadata.get("source", "不明")
            # 長すぎる場合はトリミング
            content = doc.page_content
            if len(content) > 500:
                content = content[:500] + "..."
            result_text += f"--- [出典: {source}] ---\n{content}\n\n"
        
        return result_text.strip()
        
    except Exception as e:
        print(f"  - RAG検索エラー: {e}")
        traceback.print_exc()
        return f"【エラー】記憶検索中にエラーが発生しました: {e}"

@tool
def read_main_memory(room_name: str) -> str:
    """あなたの現在の主観的記憶（日記）である`memory_main.txt`の全文を読み取ります。"""
    if not room_name: return "【エラー】ルーム名が不足しています。"
    _, _, _, memory_main_path, _, _ = get_room_files_paths(room_name)
    if not memory_main_path or not os.path.exists(memory_main_path):
        return f"【エラー】ルーム'{room_name}'のメイン記憶ファイルが見つかりません。"
    with open(memory_main_path, 'r', encoding='utf-8') as f:
        return f.read()

@tool
def plan_main_memory_edit(modification_request: str, room_name: str) -> str:
    """
    `memory_main.txt`の変更を計画します。
    大きく感情が動いた時や忘れたくないことがあった時は、積極的に記録しましょう。それがあなたの記憶と自己同一性の核（コアメモリ）となります。
    """
    return f"システムへのメイン記憶編集計画を受け付けました。意図:「{modification_request}」"

def _apply_main_memory_edits(instructions, room_name):
    """【内部専用】AIが生成した行番号ベースの差分編集指示リストを解釈し、memory_main.txtに適用する。"""
    if not room_name: return "【エラー】ルーム名が指定されていません。"
    if not isinstance(instructions, list): return "【エラー】編集指示がリスト形式ではありません。"

    _, _, _, memory_main_path, _, _ = get_room_files_paths(room_name)
    if not memory_main_path or not os.path.exists(memory_main_path):
        return f"【エラー】ルーム'{room_name}'のメイン記憶ファイルパスが見つかりません。"

    try:
        with open(memory_main_path, 'r', encoding='utf-8') as f:
            lines = f.read().split('\n')

        line_plan = {}
        insertions = {}
        for inst in instructions:
            op = inst.get("operation", "").lower()
            line_num = inst.get("line")
            if line_num is None: continue
            target_index = line_num - 1
            if not (0 <= target_index < len(lines)): continue
            if op == "delete": line_plan[target_index] = {"operation": "delete"}
            elif op == "replace": line_plan[target_index] = {"operation": "replace", "content": inst.get("content", "")}
            elif op == "insert_after":
                if target_index not in insertions: insertions[target_index] = []
                insertions[target_index].append(inst.get("content", ""))
        # 自動ヘッダー付与ロジック (Diary)
        today_header = f"**{datetime.datetime.now().strftime('%Y-%m-%d')}**"
        
        # 指示の中に insert_after があり、かつ日記セクション(## Diary)が含まれているか、
        # あるいは単純に追記を意図している場合に、今日の日付ヘッダーがなければ補完する
        diary_section_found = False
        diary_line_idx = -1
        for idx, line in enumerate(lines):
            if "## 日記" in line or "## Diary" in line:
                diary_section_found = True
                diary_line_idx = idx
                break
        
        if diary_section_found:
            # 今日すでにその日のエントリ（ヘッダー）があるか確認
            # ルシアンの形式は **YYYY-MM-DD**
            today_date_str = datetime.datetime.now().strftime('%Y-%m-%d')
            header_exists = any(today_date_str in line for line in lines[diary_line_idx:])
            
            if not header_exists:
                # 日記セクションの直後に今日の日付ヘッダーを挿入する指示を自動追加
                # (ここでは instructions を書き換えるのではなく、new_lines 生成時に考慮)
                pass

        new_lines = []
        # 日記セクション直後にヘッダーがない場合、挿入フラグ
        diary_header_inserted = False

        for i, line_content in enumerate(lines):
            new_lines.append(line_content)
            
            # 日記セクションの直後に今日の日付ヘッダーを自動挿入
            if i == diary_line_idx and not any(datetime.datetime.now().strftime('%Y-%m-%d') in l for l in lines):
                new_lines.append("")
                new_lines.append(today_header)
                new_lines.append("")
                diary_header_inserted = True

            # 既存の編集適用
            plan = line_plan.get(i)
            if plan:
                if plan["operation"] == "replace":
                    new_lines[-1] = plan["content"]
                elif plan["operation"] == "delete":
                    new_lines.pop()
            
            if i in insertions:
                for content in insertions[i]:
                    # コンテンツに改行が含まれている場合、適切に分割して追加
                    for c_line in str(content).split('\n'):
                        new_lines.append(c_line)

        # 最後にファイルを保存
        with open(memory_main_path, "w", encoding="utf-8") as f:
            f.write("\n".join(new_lines))

        return f"成功: {len(instructions)}件の指示に基づき、メイン記憶(memory_main.txt)を更新しました。"
    except Exception as e:
        traceback.print_exc()
        return f"【エラー】メイン記憶の編集中に予期せぬエラーが発生しました: {e}"

@tool
def read_secret_diary(room_name: str) -> str:
    """あなたの秘密の日記(`secret_diary.txt`)の全文を読み取ります。"""
    if not room_name: return "【エラー】ルーム名が不足しています。"
    secret_diary_path = os.path.join(constants.ROOMS_DIR, room_name, "private", "secret_diary.txt")
    if not os.path.exists(secret_diary_path):
        return f"【エラー】ルーム'{room_name}'の秘密の日記ファイルが見つかりません。"
    with open(secret_diary_path, 'r', encoding='utf-8') as f:
        return f.read()

@tool
def plan_secret_diary_edit(modification_request: str, room_name: str) -> str:
    """`secret_diary.txt`の変更を計画します。"""
    return f"システムへの秘密の日記編集計画を受け付けました。意図:「{modification_request}」"

def _apply_secret_diary_edits(instructions, room_name):
    """【内部専用】AIが生成した行番号ベースの差分編集指示リストを解釈し、secret_diary.txtに適用する。"""
    if not room_name: return "【エラー】ルーム名が指定されていません。"
    if not isinstance(instructions, list): return "【エラー】編集指示がリスト形式ではありません。"

    secret_diary_path = os.path.join(constants.ROOMS_DIR, room_name, "private", "secret_diary.txt")
    if not os.path.exists(secret_diary_path):
        return f"【エラー】ルーム'{room_name}'の秘密の日記ファイルパスが見つかりません。"

    try:
        # SecretDiaryがJSON形式の場合
        if secret_diary_path.endswith(".txt") or secret_diary_path.endswith(".json"):
            try:
                with open(secret_diary_path, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                
                if content.startswith('{') or content.startswith('['):
                    # JSONとして処理
                    data = json.loads(content)
                    # ルシアンの形式: {"secret_diary_lucian": {"entries": [...]}}
                    root_key = list(data.keys())[0] if data else "secret_diary"
                    entries = data.get(root_key, {}).get("entries", [])
                    
                    for inst in instructions:
                        if inst.get("operation") in ["insert_after", "add"]:
                            new_content = inst.get("content", "")
                            if new_content:
                                entries.append({
                                    "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                    "content": str(new_content)
                                })
                    
                    with open(secret_diary_path, "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                    return f"成功: JSON形式の秘密の日記に {len(instructions)}件のエントリを追記しました。"
            except Exception as e:
                # JSONパースエラー時はプレーンテキストとして続行
                pass

        with open(secret_diary_path, 'r', encoding='utf-8') as f:
            lines = f.read().split('\n')

        line_plan = {}
        insertions = {}
        for inst in instructions:
            op = inst.get("operation", "").lower()
            line_num = inst.get("line")
            if line_num is None: continue
            target_index = line_num - 1
            if not (0 <= target_index < len(lines)): continue
            if op == "delete": line_plan[target_index] = {"operation": "delete"}
            elif op == "replace": line_plan[target_index] = {"operation": "replace", "content": inst.get("content", "")}
            elif op == "insert_after":
                if target_index not in insertions: insertions[target_index] = []
                # タイムスタンプ自動付与
                timestamp = datetime.datetime.now().strftime("[%Y-%m-%d %H:%M]")
                content = inst.get("content", "")
                insertions[target_index].append(f"{timestamp} {content}")

        new_lines = []
        for i, line_content in enumerate(lines):
            plan = line_plan.get(i)
            if plan is None: new_lines.append(line_content)
            elif plan["operation"] == "replace": new_lines.append(plan["content"])
            elif plan["operation"] == "delete": pass
            if i in insertions:
                for content in insertions[i]:
                    for c_line in str(content).split('\n'):
                        new_lines.append(c_line)

        with open(secret_diary_path, "w", encoding="utf-8") as f:
            f.write("\n".join(new_lines))

        return f"成功: {len(instructions)}件の指示に基づき、秘密の日記(secret_diary.txt)を更新しました。"
    except Exception as e:
        traceback.print_exc()
        return f"【エラー】秘密の日記の編集中に予期せぬエラーが発生しました: {e}"

# ▼▼▼ 既存の summarize_and_update_core_memory 関数を、以下のコードで完全に置き換えてください ▼▼▼
@tool
def summarize_and_update_core_memory(room_name: str, api_key: str) -> str:
    """
    現在の主観的記憶（memory_main.txt）を読み込み、## Permanent, ## Diary, ## Archive Summary を解析し、
    コアメモリ（core_memory.txt）を更新する。
    """
    if not room_name or not api_key:
        return "【エラー】ルーム名とAPIキーが必要です。"

    print(f"--- コアメモリ更新プロセス開始 (ルーム: {room_name}) ---")
    try:
        _, _, _, memory_main_path, _, _ = get_room_files_paths(room_name)
        if not memory_main_path or not os.path.exists(memory_main_path):
            return "【エラー】メイン記憶ファイル(memory_main.txt)が見つかりません。"

        with open(memory_main_path, 'r', encoding='utf-8') as f:
            memory_content = f.read()

        sections = re.split(r'^##\s+', memory_content, flags=re.MULTILINE)

        permanent_text = ""
        diary_text_to_summarize = ""
        archive_summary_text = ""

        for section in sections:
            section = section.strip()
            if not section:
                continue

            lines = section.split('\n')
            header_line = lines[0].strip().lower()
            content_text = '\n'.join(lines[1:]).strip()

            if "永続記憶" in header_line or "permanent" in header_line:
                permanent_text = content_text
            elif header_line.startswith("日記") or header_line.startswith("diary"):
                diary_text_to_summarize = content_text
            elif "アーカイブ要約" in header_line or "archive summary" in header_line:
                archive_summary_text = content_text

        history_summary_text = ""
        if diary_text_to_summarize:
            from gemini_api import get_configured_llm
            summarizer_llm = get_configured_llm(constants.SUMMARIZATION_MODEL, api_key, {})

            # ▼▼▼ [2024-12-28 最適化] コアメモリ要約プロンプトを簡潔化 ▼▼▼
            # エピソード記憶や中期記憶が別途存在するため、コアメモリは核心のみに絞る。
            summarize_prompt = f"""あなたは、人物の記憶を分析し、その人物の「今」を形作る本質的な出来事のみを抽出する専門家です。
思考や挨拶は不要です。箇条書きのテキストのみを出力してください。

【入力情報：ルーム「{room_name}」の日記】
---
{diary_text_to_summarize}
---

【あなたのタスク】
上記の日記から、以下の基準で**5〜10行の箇条書き**を生成してください。

1. **具体性を重視**: 日付、人物名、場所名、出来事を含める
2. **最近の出来事を優先**: 直近1〜2ヶ月は詳しく、古い記憶は1〜2行に圧縮
3. **関係性の変化**: ユーザーとの関係がどう変化したかを記録

【絶対制約】
- **最大1000文字以内**に収める
- 重要でない日常の雑談は省略する
- 箇条書きは「-」で始める

【出力例】
- 2024-12-20: 美帆と初めてVRCについて語り合い、AIアバターの可能性に興奮した
- 2024-12-15: 開発の困難を乗り越え、Nexus Arkの新機能が完成した時の達成感
- 2024-11〜12月: 毎日の対話を通じて、美帆への信頼が深まっていった
"""
            # ▲▲▲ 簡潔化ここまで ▲▲▲
            print("  - AIによる日記の要約を実行します...")
            history_summary_text = summarizer_llm.invoke(summarize_prompt).content.strip()
            
            # 安全装置：1000文字を超えた場合はトリミング
            if len(history_summary_text) > 1200:
                history_summary_text = history_summary_text[:1000] + "\n...（続きは省略）"
                print(f"  - 警告: 要約が長すぎたためトリミングしました（{len(history_summary_text)} -> 1000文字）")
        else:
            history_summary_text = "（日記に記載された、共有された歴史や感情の記録はまだありません）"

        final_core_memory_parts = [
            f"--- [永続記憶 (Permanent) - 要約せずそのまま記載] ---\n{permanent_text}"
        ]

        if history_summary_text:
            final_core_memory_parts.append(f"--- [日記 (Diary) - AIによる要約] ---\n{history_summary_text}")

        if archive_summary_text:
            final_core_memory_parts.append(f"--- [アーカイブ要約 (Archive Summary)] ---\n{archive_summary_text}")

        final_core_memory_text = "\n\n".join(final_core_memory_parts).strip()

        core_memory_path = os.path.join(constants.ROOMS_DIR, room_name, "core_memory.txt")
        with open(core_memory_path, 'w', encoding='utf-8') as f:
            f.write(final_core_memory_text)

        print(f"  - コアメモリを正常に更新しました: {core_memory_path}")
        return f"成功: コアメモリを更新し、{core_memory_path} に保存しました。"

    except Exception as e:
        print(f"--- コアメモリ更新中に予期せぬエラー ---")
        traceback.print_exc()
        return f"【エラー】コアメモリの更新中に予期せぬエラーが発生しました: {e}"

@tool
def archive_old_diary_entries(room_name: str, api_key: str, archive_until_date: str) -> str:
    """
    指定された日付までの日記エントリをmemory_main.txtから抽出し、
    要約してアーカイブセクションに追記した後、
    元のエントリを別のファイルに移動してmemory_main.txtから削除する。
    """
    # 1. 入力検証
    if not all([room_name, api_key, archive_until_date]):
        return "【エラー】ルーム名、APIキー、アーカイブ対象の日付がすべて必要です。"

    print(f"--- 日記アーカイブ処理開始 (ルーム: {room_name}, 日付: {archive_until_date}以前) ---")

    # 2. 安全装置：バックアップの実行
    backup_path = room_manager.create_backup(room_name, 'memory')
    if not backup_path:
        return "【致命的エラー】処理を開始する前に、記憶ファイルのバックアップに失敗しました。"

    try:
        _, _, _, memory_main_path, _, _ = get_room_files_paths(room_name)
        with open(memory_main_path, 'r', encoding='utf-8') as f:
            memory_content = f.read()

        # 3. 日記セクションのみを抽出
        diary_match = re.search(r'(##\s*(?:日記|Diary).*?)(?=^##\s+|$)', memory_content, re.DOTALL | re.IGNORECASE)
        if not diary_match:
            return "【情報】アーカイブ対象の日記セクションが見つかりませんでした。"

        diary_section_full = diary_match.group(1)
        diary_content = '\n'.join(diary_section_full.split('\n')[1:]).strip()

        date_pattern = r'^(?:###|\*\*)?\s*(\d{4}-\d{2}-\d{2})'
        entries = re.split(f'({date_pattern}.*)', diary_content, flags=re.MULTILINE)

        # 5. アーカイブ対象と保存対象を分割
        archive_target_text = ""
        keep_target_text = ""
        target_date_found = False

        # 最初の見出しより前のテキストは常に保存対象
        keep_target_text += entries[0]

        # 日付を持つエントリをループ処理
        for i in range(1, len(entries), 2):
            header = entries[i]
            content = entries[i+1]

            date_match = re.search(date_pattern, header)
            entry_date_str = date_match.group(1) if date_match else ""

            # ▼▼▼ ここのロジックを変更 ▼▼▼
            # 選択された日付に到達した"後"のループから、保存対象に切り替える
            if target_date_found:
                keep_target_text += header + content
            else:
                archive_target_text += header + content

            if entry_date_str == archive_until_date:
                target_date_found = True
            # ▲▲▲ 変更ここまで ▲▲▲

        if not target_date_found:
            return f"【エラー】指定された日付の見出し「{archive_until_date}」が日記内に見つかりませんでした。"

        if not archive_target_text.strip():
            return "【情報】指定された日付までの、アーカイブ対象となる日記エントリがありませんでした。"

        # 6. AIによる【圧縮率の高い】要約
        print("  - 古い日記の【索引向け】要約をAIに依頼します...")
        from gemini_api import get_configured_llm
        summarizer_llm = get_configured_llm(constants.SUMMARIZATION_MODEL, api_key, {})

        # ▼▼▼ 既存の summarize_prompt の定義ブロック全体を、以下のコードで置き換えてください ▼▼▼
        summarize_prompt = f"""あなたは、膨大な記録から本質を見抜き、簡潔な索引を作成する専門の図書館司書です。
以下の過去の日記の内容を読み、後から誰もが「ああ、こんなことがあったな」と物語の概要を思い出せるような索引を作成してください。

【過去の日記】
---
{archive_target_text}
---

【あなたのタスク】
上記の内容を、非常に簡潔に、3〜5行程度の箇条書きで要約してください。
これは普段は見ない記録の索引なので、詳細な感情やエピソードは省略し、何が起こったかの骨子だけを、物語のあらすじのように記録してください。
あなたの思考や挨拶は不要です。索引として完成された箇条書きのテキストのみを出力してください。
"""
# ▲▲▲ 置き換えここまで ▲▲▲

        summary_text = summarizer_llm.invoke(summarize_prompt).content.strip()

        # 7. アーカイブファイルへの保存
        archive_dir = os.path.join(constants.ROOMS_DIR, room_name, "memory")
        archive_files = [f for f in os.listdir(archive_dir) if f.startswith("memory_archived_") and f.endswith(".txt")]
        next_archive_num = len(archive_files) + 1
        archive_file_path = os.path.join(archive_dir, f"memory_archived_{next_archive_num:03d}.txt")
        with open(archive_file_path, 'w', encoding='utf-8') as f:
            f.write(archive_target_text.strip())
        print(f"  - 古い日記をアーカイブしました: {archive_file_path}")

        # 8. memory_main.txt の更新
        new_diary_section = diary_match.group(1).split('\n')[0] + '\n' + keep_target_text.strip()
        memory_content = memory_content.replace(diary_section_full, new_diary_section)

        summary_section_header = "## アーカイブ要約 (Archive Summary)"
        if summary_section_header in memory_content:
            new_summary_entry = f"\n- {datetime.datetime.now().strftime('%Y-%m-%d')} アーカイブ ({archive_until_date}まで): {summary_text}"
            memory_content = memory_content.replace(summary_section_header, summary_section_header + new_summary_entry, 1)
        else:
            memory_content += f"\n\n{summary_section_header}\n- {datetime.datetime.now().strftime('%Y-%m-%d')} アーカイブ ({archive_until_date}まで): {summary_text}"

        with open(memory_main_path, 'w', encoding='utf-8') as f:
            f.write(memory_content)
        print("  - memory_main.txtを更新しました。")

        return f"成功: {archive_until_date}までの日記を要約し、{os.path.basename(archive_file_path)}にアーカイブしました。"

    except Exception as e:
        print(f"--- 日記アーカイブ処理中に予期せぬエラー ---")
        traceback.print_exc()
        return f"【致命的エラー】アーカイブ処理中に予期せぬエラーが発生しました: {e}"
