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

@tool
def read_full_memory(room_name: str) -> str:
    """あなたの「主観的記憶（日記）」である`memory.txt`の全文を読み取ります。"""
    if not room_name: return "【エラー】内部処理エラー: 引数 'room_name' が不足しています。"
    _, _, _, memory_txt_path, _ = get_room_files_paths(room_name)
    if not memory_txt_path or not os.path.exists(memory_txt_path):
        return f"【エラー】ルーム'{room_name}'の記憶ファイルが見つかりません。"
    with open(memory_txt_path, 'r', encoding='utf-8') as f:
        return f.read()

@tool
def plan_memory_edit(modification_request: str, room_name: str) -> str:
    """
    【ステップ1：計画】あなたの「主観的記憶（日記）」である`memory.json`の変更を計画します。
    このツールは、あなたが記憶に対してどのような変更を行いたいかの「意図」をシステムに伝えるために、最初に呼び出します。
    """
    return f"システムへの記憶編集計画を受け付けました。意図:「{modification_request}」"

# ▼▼▼ 既存の _apply_memory_edits 関数を、以下のコードで完全に置き換えてください ▼▼▼
def _apply_memory_edits(
    instructions: List[Dict[str, Any]],
    room_name: str
) -> str:
    """【内部専用】AIが生成した行番号ベースの差分編集指示リストを解釈し、memory.txtに適用し、更新日時をroom_config.jsonに記録する。"""
    if not room_name: return "【エラー】ルーム名が指定されていません。"
    if not isinstance(instructions, list): return "【エラー】編集指示がリスト形式ではありません。"

    _, _, _, memory_txt_path, _ = get_room_files_paths(room_name)
    if not memory_txt_path: return f"【エラー】ルーム'{room_name}'の記憶ファイルパスが見つかりません。"

    try:
        with open(memory_txt_path, 'r', encoding='utf-8') as f:
            lines = f.read().split('\n')

        # (行番号ベースの編集ロジック部分は、前回の指示から変更なし)
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

        # memory.txt ファイルに書き戻す
        with open(memory_txt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(new_lines))

        # --- ▼▼▼【ここからが新しいブロック】▼▼▼ ---
        # 2. room_config.json に最終更新日時を記録する
        try:
            config_path = os.path.join(constants.ROOMS_DIR, room_name, "room_config.json")
            config = {}
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)

            config["memory_last_updated"] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
        except Exception as config_e:
            print(f"警告: room_config.jsonへの更新日時記録中にエラーが発生しました: {config_e}")
        # --- ▲▲▲【新しいブロックここまで】▲▲▲ ---

        return f"成功: {len(instructions)}件の指示に基づき、主観的記憶(memory.txt)を更新しました。"
    except Exception as e:
        traceback.print_exc()
        return f"【エラー】記憶の編集中に予期せぬエラーが発生しました: {e}"

# ▼▼▼ 既存の summarize_and_update_core_memory 関数を、以下のコードで完全に置き換えてください ▼▼▼
@tool
def summarize_and_update_core_memory(room_name: str, api_key: str) -> str:
    """
    現在の主観的記憶（memory.txt）を読み込み、## Sanctuary エリアと ## Diary エリアを解析し、
    客観的な事実のリストであるコアメモリ（core_memory.txt）を更新する。
    """
    if not room_name or not api_key:
        return "【エラー】ルーム名とAPIキーが必要です。"

    print(f"--- コアメモリ更新プロセス開始 (ルーム: {room_name}) ---")
    try:
        # 1. memory.txt を読み込む
        _, _, _, memory_txt_path, _ = get_room_files_paths(room_name)
        if not memory_txt_path or not os.path.exists(memory_txt_path):
            return "【エラー】主観的記憶ファイル(memory.txt)が見つかりません。"

        with open(memory_txt_path, 'r', encoding='utf-8') as f:
            memory_content = f.read()

        # 2. 正規表現を使って各エリアの内容を抽出
        sanctuary_match = re.search(r"##\s*聖域\s*\(Sanctuary\)(.*?)##\s*日記\s*\(Diary\)", memory_content, re.DOTALL | re.IGNORECASE)
        diary_match = re.search(r"##\s*日記\s*\(Diary\)(.*?)##\s*秘密の日記\s*\(Secret Diary\)", memory_content, re.DOTALL | re.IGNORECASE)

        sanctuary_text = sanctuary_match.group(1).strip() if sanctuary_match else ""
        diary_text_to_summarize = diary_match.group(1).strip() if diary_match else ""

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
        return f"成功: 新しい形式のコアメモリを更新し、{core_memory_path} に保存しました。"

    except Exception as e:
        print(f"--- コアメモリ更新中に予期せぬエラー ---")
        traceback.print_exc()
        return f"【エラー】コアメモリの更新中に予期せぬエラーが発生しました: {e}"
