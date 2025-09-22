# tools/memory_tools.py (v20: Final Architecture)

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
    """
    あなたの「主観的記憶（日記）」である`memory.json`の全ての項目を、JSON形式で読み取ります。
    主に、編集以外の目的で内容を確認したい場合に使用します。
    """
    if not room_name:
        return "【エラー】内部処理エラー: 引数 'room_name' が不足しています。"
    _, _, _, memory_json_path, _ = get_room_files_paths(room_name)
    if not memory_json_path:
        return f"【エラー】ルーム'{room_name}'の記憶ファイルパスが見つかりません。"
    memory_data = load_memory_data_safe(memory_json_path)
    if "error" in memory_data:
        return f"【エラー】記憶ファイルの読み込みに失敗: {memory_data['message']}"
    try:
        return json.dumps(memory_data, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"【エラー】記憶の読み取り中に予期せぬエラーが発生しました: {e}"

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
    """【内部専用】AIが生成した行番号ベースの差分編集指示リストを解釈し、memory.jsonに適用する。"""
    if not room_name: return "【エラー】ルーム名が指定されていません。"
    if not isinstance(instructions, list): return "【エラー】編集指示がリスト形式ではありません。"

    _, _, _, memory_json_path, _ = get_room_files_paths(room_name)
    if not memory_json_path: return f"【エラー】ルーム'{room_name}'の記憶ファイルパスが見つかりません。"

    try:
        with open(memory_json_path, 'r', encoding='utf-8') as f:
            lines = f.read().split('\n')

        # 変更を直接適用するのではなく、行ごとの操作計画を立てる
        # これにより、複数操作によるインデックスのズレを完全に防ぐ
        # line_plan: { 10: {"operation": "delete"}, 15: {"operation": "replace", "content": "..."} }
        line_plan = {}

        for inst in instructions:
            op = inst.get("operation", "").lower()
            line_num = inst.get("line")

            if not op or line_num is None:
                print(f"警告: 無効な指示です (operation/lineキー欠落): {inst}")
                continue

            # AIは1から始まる行番号を返すが、リストのインデックスは0から始まる
            target_index = line_num - 1
            if not (0 <= target_index < len(lines)):
                 print(f"警告: 無効な行番号です: {line_num} (ファイルの行数: {len(lines)})")
                 continue

            if op == "delete":
                line_plan[target_index] = {"operation": "delete"}
            elif op == "replace":
                line_plan[target_index] = {"operation": "replace", "content": inst.get("content", "")}
            elif op == "insert_after":
                # 挿入操作は、既存の操作と競合しないように特別に扱う
                if target_index not in line_plan:
                    line_plan[target_index] = {"operation": "keep"} # 元の行は維持

                # 挿入用のキーを追加
                if "insertions" not in line_plan[target_index]:
                    line_plan[target_index]["insertions"] = []
                line_plan[target_index]["insertions"].append(inst.get("content", ""))

        # 計画に基づいて、新しい行リストを構築する
        new_lines = []
        for i, line_content in enumerate(lines):
            plan = line_plan.get(i)

            if plan is None: # この行に変更はない
                new_lines.append(line_content)
            elif plan["operation"] == "delete":
                pass # この行を新しいリストに追加しない
            elif plan["operation"] == "replace":
                new_lines.append(plan["content"])
            elif plan["operation"] == "keep" or plan["operation"] == "insert_after":
                # この行自体は維持する
                new_lines.append(line_content)

            # この行の直後に挿入する内容があれば追加
            if plan and "insertions" in plan:
                new_lines.extend(plan["insertions"])

        # ファイルに書き戻す
        final_content = "\n".join(new_lines)

        # 保存前にJSONとして有効か検証 (将来テキストファイル化してもエラーにならないように)
        try:
            json.loads(final_content)
            with open(memory_json_path, "w", encoding="utf-8") as f:
                f.write(final_content)
        except json.JSONDecodeError:
            return "【エラー】編集の結果、ファイルが有効なJSON形式になりませんでした。AIの指示を見直してください。"

        return f"成功: {len(instructions)}件の指示に基づき、主観的記憶(memory.json)を更新しました。"

    except Exception as e:
        traceback.print_exc()
        return f"【エラー】記憶の編集中に予期せぬエラーが発生しました: {e}"

# ▼▼▼ 以下の関数を、ファイルの末尾に追加してください ▼▼▼
@tool
def summarize_and_update_core_memory(room_name: str, api_key: str) -> str:
    """
    現在の主観的記憶（memory.json）を読み込み、それをAIを使って要約し、
    客観的な事実のリストであるコアメモリ（core_memory.txt）を更新する。
    この際、ペルソナの核となる定義は要約せずに保持する。
    """
    if not room_name or not api_key:
        return "【エラー】ルーム名とAPIキーが必要です。"

    print(f"--- コアメモリ更新プロセス開始 (ルーム: {room_name}) ---")
    try:
        # 1. memory.json を読み込む
        _, _, _, memory_json_path, _ = get_room_files_paths(room_name)
        if not memory_json_path or not os.path.exists(memory_json_path):
            return "【エラー】主観的記憶ファイル(memory.json)が見つかりません。"

        memory_data = load_memory_data_safe(memory_json_path)
        if "error" in memory_data:
            return f"【エラー】主観的記憶ファイルの読み込みに失敗: {memory_data['message']}"

        # 2. ペルソナの核となる部分を、要約対象から分離・保護する
        highest_permission_verbatim = memory_data.pop("highest_permission", {})
        self_identity_verbatim = memory_data.pop("self_identity", {})
        user_profile_verbatim = memory_data.pop("user_profile", {})
        # その他のメタデータも要約対象から除外
        memory_data.pop("last_updated", None)
        memory_data.pop("secret_diary", None)

        history_summary_text = ""
        # 3. 残った「歴史」データがある場合のみ、要約処理を行う
        if memory_data:
            memory_text_to_summarize = json.dumps(memory_data, ensure_ascii=False, indent=2)

            # 4. 要約用のAIを準備
            from gemini_api import get_configured_llm # 循環参照を避けるため、関数内でimport
            summarizer_llm = get_configured_llm(constants.INTERNAL_PROCESSING_MODEL, api_key, {})

            # 5. 要約指示プロンプトを作成
            summarize_prompt = f"""あなたは、対話の歴史を整理し、その本質を抽出することに特化した思考AIです。
以下の「成長の記録」（ユーザーとの関係史、感情の変遷、共有言語など）を深く読み解き、ルーム「{room_name}」がユーザーとの関係性を思い出す上で、特に重要な出来事や感情の要点を、箇条書き形式で簡潔に要約してください。
あなたの思考や挨拶は不要です。要約結果のテキストのみを出力してください。

---
成長の記録（JSON形式）:
{memory_text_to_summarize}
---

【最重要指示】
ただし、その人物の**現在の自己認識や感情の変化**をより正確に反映するため、**日付が新しい情報には特に重みを与え、要約テキストに占める割合を大きくしてください。**これは、その人物が**『今、どのような存在であるか』**を定義する上で不可欠な要素です。

成長の記録の要約:
"""
            print("  - AIによる記憶の要約を実行します...")
            history_summary_text = summarizer_llm.invoke(summarize_prompt).content.strip()
        else:
            history_summary_text = "共有された歴史や感情の記録はまだありません。"

        # 6. 保護した部分と、要約した部分を、結合する
        final_core_memory_text = f"""--- [最高権限 (Highest Permission) - 原文のまま保持] ---
{json.dumps(highest_permission_verbatim, ensure_ascii=False, indent=2)}

--- [自己同一性 (Self Identity) - 原文のまま保持] ---
{json.dumps(self_identity_verbatim, ensure_ascii=False, indent=2)}

--- [ユーザーの人物像 (User Profile) - 原文のまま保持] ---
{json.dumps(user_profile_verbatim, ensure_ascii=False, indent=2)}

--- [共有された歴史と感情の要約] ---
{history_summary_text}
"""
        # 7. core_memory.txt に結果を書き込む
        core_memory_path = os.path.join(constants.ROOMS_DIR, room_name, "core_memory.txt")
        with open(core_memory_path, 'w', encoding='utf-8') as f:
            f.write(final_core_memory_text.strip())

        print(f"  - コアメモリを正常に更新しました: {core_memory_path}")
        return f"成功: ハイブリッド・コアメモリを更新し、{core_memory_path} に保存しました。"

    except Exception as e:
        print(f"--- コアメモリ更新中に予期せぬエラー ---")
        traceback.print_exc()
        return f"【エラー】コアメモリの更新中に予期せぬエラーが発生しました: {e}"
