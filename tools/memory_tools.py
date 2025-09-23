# tools/memory_tools.py (v20: Final Architecture)

import re
from langchain_core.tools import tool
import json
import datetime
from room_manager import get_room_files_paths
from memory_manager import load_memory_data_safe
from typing import List, Dict, Any
import traceback
import os
import constants
import utils # <-- 追加が必要な場合

@tool
def search_memory(query: str, room_name: str) -> str:
    """
    あなたの長期記憶（日記アーカイブを含む）の中から、指定されたクエリに最も関連する日記の断片を検索します。
    ユーザーとの会話で過去の出来事を思い出す必要がある場合に使用します。
    query: 検索したい事柄に関する自然言語のキーワード。（例：「初めて会った日のこと」）
    """
    if not query or not room_name:
        return "【エラー】検索クエリとルーム名が必要です。"

    memory_folder = os.path.join(constants.ROOMS_DIR, room_name, "memory")
    if not os.path.isdir(memory_folder):
        return "【情報】記憶フォルダが見つかりません。"

    search_files = [os.path.join(memory_folder, f) for f in os.listdir(memory_folder) if f.endswith(".txt")]

    # 検索キーワードを分割
    keywords = query.split()

    found_blocks = []

    for file_path in search_files:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            # 見出し行のインデックスをすべて特定 (##, ###, **)
            header_indices = [i for i, line in enumerate(lines) if re.match(r"^(## |### |\*\*)", line.strip())]

            for i, line in enumerate(lines):
                # 行にキーワードが含まれているかチェック
                if any(keyword in line for keyword in keywords):
                    # ヒットした行を含むブロックを特定
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
                    header_line = lines[start_index].strip()

                    # 重複を避けるため、ブロックの内容でチェック
                    if block_content not in [b['content'] for b in found_blocks]:
                        found_blocks.append({
                            "file": os.path.basename(file_path),
                            "header": header_line,
                            "content": block_content
                        })

        except Exception as e:
            print(f"記憶ファイル '{file_path}' の検索中にエラー: {e}")
            continue

    if not found_blocks:
        return f"【検索結果】「{query}」に関する記憶は見つかりませんでした。"

    # 結果を整形して返す
    result_text = f"【記憶検索の結果：「{query}」】\n\n"
    for block in found_blocks:
        result_text += f"--- [出典: {block['file']}, 見出し: {block['header']}] ---\n"
        result_text += f"{block['content']}\n\n"

    return result_text.strip()

@tool
def read_main_memory(room_name: str) -> str:
    """あなたの現在の主観的記憶（日記）である`memory_main.txt`の全文を読み取ります。"""
    if not room_name: return "【エラー】ルーム名が不足しています。"
    _, _, _, memory_main_path, _ = get_room_files_paths(room_name)
    if not memory_main_path or not os.path.exists(memory_main_path):
        return f"【エラー】ルーム'{room_name}'のメイン記憶ファイルが見つかりません。"
    with open(memory_main_path, 'r', encoding='utf-8') as f:
        return f.read()

@tool
def plan_main_memory_edit(modification_request: str, room_name: str) -> str:
    """`memory_main.txt`の変更を計画します。"""
    return f"システムへのメイン記憶編集計画を受け付けました。意図:「{modification_request}」"

def _apply_main_memory_edits(instructions, room_name):
    """【内部専用】AIが生成した行番号ベースの差分編集指示リストを解釈し、memory_main.txtに適用する。"""
    if not room_name: return "【エラー】ルーム名が指定されていません。"
    if not isinstance(instructions, list): return "【エラー】編集指示がリスト形式ではありません。"

    _, _, _, memory_main_path, _ = get_room_files_paths(room_name)
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
        new_lines = []
        for i, line_content in enumerate(lines):
            plan = line_plan.get(i)
            if plan is None: new_lines.append(line_content)
            elif plan["operation"] == "replace": new_lines.append(plan["content"])
            elif plan["operation"] == "delete": pass
            if i in insertions:
                new_lines.extend(insertions[i])

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
                insertions[target_index].append(inst.get("content", ""))
        new_lines = []
        for i, line_content in enumerate(lines):
            plan = line_plan.get(i)
            if plan is None: new_lines.append(line_content)
            elif plan["operation"] == "replace": new_lines.append(plan["content"])
            elif plan["operation"] == "delete": pass
            if i in insertions:
                new_lines.extend(insertions[i])

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
    現在の主観的記憶（memory_main.txt）を読み込み、## Sanctuary と ## Diary を解析し、
    コアメモリ（core_memory.txt）を更新する。
    """
    if not room_name or not api_key:
        return "【エラー】ルーム名とAPIキーが必要です。"

    print(f"--- コアメモリ更新プロセス開始 (ルーム: {room_name}) ---")
    try:
        _, _, _, memory_main_path, _ = get_room_files_paths(room_name)
        if not memory_main_path or not os.path.exists(memory_main_path):
            return "【エラー】メイン記憶ファイル(memory_main.txt)が見つかりません。"

        with open(memory_main_path, 'r', encoding='utf-8') as f:
            memory_content = f.read()

        # --- 堅牢なセクション抽出ロジック ---
        # ヘッダー(## ...)で全体を分割。キャプチャグループに入れると区切り文字もリストに残る。
        parts = re.split(r'(^##\s+.*)', memory_content, flags=re.MULTILINE)

        sanctuary_text = ""
        diary_text_to_summarize = ""
        current_section = None

        for part in parts:
            part_content = part.strip()
            if not part_content:
                continue

            if part_content.startswith("## "):
                header = part_content.lower()
                if "聖域" in header or "sanctuary" in header:
                    current_section = "sanctuary"
                elif "日記" in header or "diary" in header:
                    current_section = "diary"
                else:
                    current_section = None
                continue

            if current_section == "sanctuary":
                sanctuary_text += part + "\n"
            elif current_section == "diary":
                diary_text_to_summarize += part + "\n"

        sanctuary_text = sanctuary_text.strip()
        diary_text_to_summarize = diary_text_to_summarize.strip()

        # 3. 日記エリアの要約処理
        history_summary_text = ""
        if diary_text_to_summarize:
            from gemini_api import get_configured_llm
            summarizer_llm = get_configured_llm(constants.INTERNAL_PROCESSING_MODEL, api_key, {})

            summarize_prompt = f"""あなたは、対話の歴史を整理し、その本質を抽出することに特化した思考AIです。
以下の「日記」の内容を深く読み解き、ルーム「{room_name}」がユーザーとの関係性を思い出す上で、特に重要な出来事や感情の要点を、箇条書き形式で簡潔に要約してください。
あなたの思考や挨拶は不要です。要約結果のテキストのみを出力してください。

---
日記:
{diary_text_to_summarize}
---

【最重要指示】
日付が新しい情報には特に重みを与え、要約テキストに占める割合を大きくしてください。これは、その人物が『今、どのような存在であるか』を定義する上で不可欠な要素です。

日記の要約:
"""
            print("  - AIによる日記の要約を実行します...")
            history_summary_text = summarizer_llm.invoke(summarize_prompt).content.strip()
        else:
            history_summary_text = "（日記に記載された、共有された歴史や感情の記録はまだありません）"

        # 4. 聖域エリアと、要約した日記を結合
        final_core_memory_text = (
            f"--- [聖域 (Sanctuary) - 要約せずそのまま記載] ---\n"
            f"{sanctuary_text}\n\n"
            f"--- [日記 (Diary) - AIによる要約] ---\n"
            f"{history_summary_text}"
        ).strip()

        # 5. core_memory.txt に結果を書き込む
        core_memory_path = os.path.join(constants.ROOMS_DIR, room_name, "core_memory.txt")
        with open(core_memory_path, 'w', encoding='utf-8') as f:
            f.write(final_core_memory_text)

        print(f"  - コアメモリを正常に更新しました: {core_memory_path}")
        return f"成功: コアメモリを更新し、{core_memory_path} に保存しました。"

    except Exception as e:
        print(f"--- コアメモリ更新中に予期せぬエラー ---")
        traceback.print_exc()
        return f"【エラー】コアメモリの更新中に予期せぬエラーが発生しました: {e}"
