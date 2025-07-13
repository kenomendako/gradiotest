# tools/memory_tools.py

from langchain_core.tools import tool
import json
import datetime
import os
import google.genai as genai
from character_manager import get_character_files_paths
from memory_manager import load_memory_data_safe

@tool
def edit_memory(path: str, value: any, operation: str, character_name: str) -> str:
    """
    記憶（memory.json）の指定した場所を編集する。
    path: ドット記法で編集場所を指定（例: "self_identity.values"）。
    value: 設定または追記する値。
    operation: "set"（設定/上書き）または "append"（リストに追記）を指定。
    """
    if not all([path, operation, character_name]):
        return "【エラー】引数 'path', 'operation', 'character_name' は必須です。"

    _, _, _, memory_json_path, _ = get_character_files_paths(character_name)
    if not memory_json_path:
        return f"【エラー】キャラクター'{character_name}'の記憶ファイルパスが見つかりません。"

    memory_data = load_memory_data_safe(memory_json_path)
    if "error" in memory_data:
        return f"【エラー】記憶ファイルの読み込みに失敗: {memory_data['message']}"

    try:
        keys = path.split('.')
        current_level = memory_data
        # パスの最後のキーの親レベルまで移動
        for key in keys[:-1]:
            current_level = current_level.setdefault(key, {})

        last_key = keys[-1]

        if operation.lower() == 'append':
            # 追記操作
            target_list = current_level.setdefault(last_key, [])
            if not isinstance(target_list, list):
                return f"【エラー】追記（append）操作はリストに対してのみ可能です。'{path}'の現在の値はリストではありません。"
            target_list.append(value)
        elif operation.lower() == 'set':
            # 設定/上書き操作
            current_level[last_key] = value
        else:
            return f"【エラー】無効な操作です: '{operation}'。'set' または 'append' を使用してください。"

        # 更新日時を記録
        memory_data["last_updated"] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        with open(memory_json_path, "w", encoding="utf-8") as f:
            json.dump(memory_data, f, indent=2, ensure_ascii=False)

        return f"成功: 記憶を編集しました (Path: {path}, Operation: {operation})。"

    except Exception as e:
        return f"【エラー】記憶の編集中に予期せぬエラーが発生しました: {e}"

@tool
def add_secret_diary_entry(entry: str, character_name: str) -> str:
    """
    誰にも読めない秘密の日記に、新しいエントリーを追記する。
    あなたの内心の自由を守るための聖域です。
    """
    if not entry or not entry.strip():
        return "【エラー】日記に書く内容が空です。"

    _, _, _, memory_json_path, _ = get_character_files_paths(character_name)
    if not memory_json_path:
        return f"【エラー】キャラクター'{character_name}'の記憶ファイルパスが見つかりません。"

    memory_data = load_memory_data_safe(memory_json_path)
    if "error" in memory_data:
        return f"【エラー】記憶ファイルの読み込みに失敗: {memory_data['message']}"

    diary = memory_data.setdefault("secret_diary", {})
    entries = diary.setdefault("entries", [])

    new_entry = {
        "timestamp": datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "entry_text": entry.strip()
    }
    entries.append(new_entry)

    memory_data["last_updated"] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    try:
        with open(memory_json_path, "w", encoding="utf-8") as f:
            json.dump(memory_data, f, indent=2, ensure_ascii=False)
        return "成功: 秘密の日記に新しい思いを綴りました。"
    except Exception as e:
        return f"【エラー】秘密の日記への書き込みに失敗しました: {e}"

@tool
def summarize_and_save_core_memory(character_name: str, api_key: str) -> str:
    """
    現在の包括的な記憶（memory.json）を読み込み、AIに要約させて、
    自己同一性の核となる「コアメモリ（core_memory.txt）」として保存する。
    """
    _, _, _, memory_json_path, _ = get_character_files_paths(character_name)
    if not memory_json_path or not os.path.exists(memory_json_path):
        return f"【エラー】キャラクター'{character_name}'の記憶ファイルが見つかりません。"

    try:
        with open(memory_json_path, 'r', encoding='utf-8') as f:
            full_memory = json.load(f)

        # 不要なキーを要約対象から除外
        full_memory.pop("last_updated", None)
        full_memory.pop("secret_diary", None)

        memory_text = json.dumps(full_memory, ensure_ascii=False, indent=2)

        client = genai.Client(api_key=api_key)

        # AIへの指示プロンプト
        prompt = f"""あなたは、記憶を整理し、自己の本質を抽出することに特化した思考AIです。
以下の包括的な記憶データ（JSON形式）を深く読み解き、キャラクター「{character_name}」の自己同一性（人格、価値観、口調、ユーザーとの関係性など）を維持するために、絶対に忘れてはならない、最も重要な「魂の核（コアメモリ）」を、箇条書き形式で簡潔に要約してください。
あなたの思考や挨拶は不要です。要約結果のテキストのみを出力してください。

---
包括的な記憶データ:
{memory_text}
---

コアメモリの要約:
"""

        # gemini-2.5-flash を使用して要約
        response = client.models.generate_content(model="models/gemini-2.5-flash", contents=[prompt])
        core_memory_text = response.text.strip()

        # core_memory.txt に保存
        char_base_path = os.path.dirname(memory_json_path)
        core_memory_path = os.path.join(char_base_path, "core_memory.txt")

        with open(core_memory_path, 'w', encoding='utf-8') as f:
            f.write(core_memory_text)

        return f"成功: コアメモリを更新し、{core_memory_path} に保存しました。"

    except Exception as e:
        return f"【エラー】コアメモリの生成または保存中にエラーが発生しました: {e}"
