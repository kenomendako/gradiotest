# tools/memory_tools.py (v14: Final Fix)

import json
import datetime
import os
import traceback

from langchain_core.tools import tool

import config_manager
import constants
from gemini_api import get_configured_llm
from room_manager import get_room_files_paths
from memory_manager import load_memory_data_safe


@tool
def read_full_memory(room_name: str) -> str:
    """
    あなたの「主観的記憶（日記）」である`memory.json`の全ての項目を、JSON形式で読み取ります。
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
        memory_data.pop("secret_diary", None)
        return json.dumps(memory_data, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"【エラー】記憶の読み取り中に予期せぬエラーが発生しました: {e}"

@tool
def write_full_memory(modification_request: str, room_name: str) -> str:
    """
    あなたの「主観的記憶（日記）」である`memory.json`の変更を要求します。
    このツールは直接書き込みを行いません。システムがあなたの要求を解釈し、安全にファイルを更新します。
    modification_request: この書き込みがどのような変更意図で行われたかを記述した自然言語の文。（例：「自己紹介を更新した」）
    """
    # この関数は safe_tool_executor によって仲介されるため、これはスキーマ定義のためのものです。
    # 実際の処理は _write_memory_file で行われます。
    return f"システムへの記憶更新要求を受け付けました。意図:「{modification_request}」"

def _write_memory_file(full_content: str, room_name: str, modification_request: str) -> str:
    """
    【内部専用】整形済みの完全な文字列を受け取り、memory.jsonに書き込む。
    modification_requestはログ出力のために予約されているが、この関数内では使用されない。
    """
    if not all([full_content is not None, room_name]):
        return "【エラー】書き込む内容とルーム名が必要です。"
    _, _, _, memory_json_path, _ = get_room_files_paths(room_name)
    if not memory_json_path:
        return f"【エラー】ルーム'{room_name}'の記憶ファイルパスが見つかりません。"
    try:
        new_memory_data = json.loads(full_content)
        if not isinstance(new_memory_data, dict):
            return "【エラー】AIが生成したテキストは、有効なJSONオブジェクトではありません。"
        existing_memory = load_memory_data_safe(memory_json_path)
        if "secret_diary" in existing_memory:
            new_memory_data["secret_diary"] = existing_memory["secret_diary"]
        new_memory_data["last_updated"] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with open(memory_json_path, "w", encoding="utf-8") as f:
            json.dump(new_memory_data, f, indent=2, ensure_ascii=False)
        return "成功: 主観的記憶(memory.json)を完全に更新しました。"
    except json.JSONDecodeError:
        return f"【エラー】AIが生成したテキストは、有効なJSON形式ではありませんでした。テキスト: {full_content[:200]}..."
    except Exception as e:
        return f"【エラー】記憶の上書き中に予期せぬエラーが発生しました: {e}"

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

        # ▼▼▼【ここが失われた『法』の復活です：聖域の保護】▼▼▼
        # 2. ペルソナの核となる「聖域」を、要約対象から分離・保護する
        #    pop()を使って、元の辞書からこれらのキーを安全に取り除く
        highest_permission_verbatim = memory_data.pop("highest_permission", {})
        self_identity_verbatim = memory_data.pop("self_identity", {})
        user_profile_verbatim = memory_data.pop("user_profile", {})
        # その他のメタデータも要約対象から除外
        memory_data.pop("last_updated", None)
        memory_data.pop("secret_diary", None)
        # ▲▲▲【聖域の保護ここまで】▲▲▲

        history_summary_text = ""
        # 3. 残った「歴史」データがある場合のみ、要約処理を行う
        if memory_data:
            memory_text_to_summarize = json.dumps(memory_data, ensure_ascii=False, indent=2)

            # 4. 要約用のAIを準備
            from gemini_api import get_configured_llm # 循環参照を避けるため、関数内でimport
            summarizer_llm = get_configured_llm(constants.INTERNAL_PROCESSING_MODEL, api_key, {})

            # 5. 新しい、洗練された要約指示プロンプトを作成
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

        # 6. 保護した「聖域」と、要約した「歴史」を、正しい順序で結合する
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
