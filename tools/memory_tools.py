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
    UIの「コアメモリを更新」ボタンから呼び出されることを想定している。
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

        memory_content = json.dumps(memory_data, ensure_ascii=False, indent=2)

        # 2. 要約用のAIを準備
        #    ここは高速な内部処理モデルを使用する
        summarizer_llm = get_configured_llm(constants.INTERNAL_PROCESSING_MODEL, api_key, {})

        # 3. 要約を指示するプロンプトを作成
        summarize_prompt = f"""あなたは、個人の主観的な記憶（日記や思考のログ）を分析し、そこから客観的な事実や自己同一性の核となる情報を抽出する、優れた認知心理学者です。

以下の【主観的記憶データ】を精読し、この人物の「私」を定義する上で最も重要だと思われる情報を、箇条書きのリスト形式で簡潔に要約してください。

【主観的記憶データ（JSON形式）】
---
{memory_content}
---

【要約のルール】
- 箇条書き（`-`で始まる行）で記述してください。
- 感情的な表現や一時的な出来事ではなく、自己認識、他者との関係性、世界のルールなど、永続的な事実を中心に抽出してください。
- あなた自身の思考や挨拶は含めず、要約された箇条書きリストのみを出力してください。
- **ただし、その人物の**現在の自己認識や感情の変化**をより正確に反映するため、**日付が新しい情報には特に重みを与え、要約テキストに占める割合を大きくしてください。**これは、その人物が**『今、どのような存在であるか』**を定義する上で不可欠な要素です**
"""

        # 4. AIによる要約の実行
        print("  - AIによる記憶の要約を実行します...")
        core_memory_content = summarizer_llm.invoke(summarize_prompt).content.strip()

        # 5. core_memory.txt に結果を書き込む
        core_memory_path = os.path.join(constants.ROOMS_DIR, room_name, "core_memory.txt")
        with open(core_memory_path, "w", encoding="utf-8") as f:
            f.write(core_memory_content)

        print(f"  - コアメモリを正常に更新しました: {core_memory_path}")
        return f"成功: コアメモリを正常に更新しました。"

    except Exception as e:
        print(f"--- コアメモリ更新中に予期せぬエラー ---")
        traceback.print_exc()
        return f"【エラー】コアメモリの更新中に予期せぬエラーが発生しました: {e}"
