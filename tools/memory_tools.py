# tools/memory_tools.py

from langchain_core.tools import tool
import json
import datetime
import os
import google.genai as genai
from character_manager import get_character_files_paths
from memory_manager import load_memory_data_safe

@tool
def edit_memory(path: str, value: any, operation: str, character_name: str = None) -> str:
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
def add_secret_diary_entry(entry: str, character_name: str = None) -> str:
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
    【最終版】現在の記憶から、highest_permission, self_identity, user_profileは原文のまま、
    その他の歴史や感情に関する項目はAIに要約させて、コアメモリとして保存する。
    """
    _, _, _, memory_json_path, _ = get_character_files_paths(character_name)
    if not memory_json_path or not os.path.exists(memory_json_path):
        return f"【エラー】キャラクター'{character_name}'の記憶ファイルが見つかりません。"

    try:
        # --- ステップ1: 記憶の読み込みと「憲法」部分の分離 ---
        with open(memory_json_path, 'r', encoding='utf-8') as f:
            memory_data = json.load(f)

        # 要約せずに原文のまま保持する部分を分離する
        highest_permission_verbatim = memory_data.pop("highest_permission", {}) # ★ 追加
        self_identity_verbatim = memory_data.pop("self_identity", {})
        user_profile_verbatim = memory_data.pop("user_profile", {})

        # 不要なキーを要約対象から除外
        memory_data.pop("last_updated", None)
        memory_data.pop("secret_diary", None)

        # --- ステップ2: 「成長の記録」部分の要約 ---
        history_summary_text = ""
        # 要約すべきデータが残っている場合のみAPIを呼び出す
        if memory_data:
            memory_text_to_summarize = json.dumps(memory_data, ensure_ascii=False, indent=2)

            client = genai.Client(api_key=api_key)

            # AIへの新しい指示プロンプト
            prompt = f"""あなたは、対話の歴史を整理し、その本質を抽出することに特化した思考AIです。
以下の「成長の記録」（ユーザーとの関係史、感情の変遷、共有言語など）を深く読み解き、キャラクター「{character_name}」がユーザーとの関係性を思い出す上で、特に重要な出来事や感情の要点を、箇条書き形式で簡潔に要約してください。
あなたの思考や挨拶は不要です。要約結果のテキストのみを出力してください。

---
成長の記録（JSON形式）:
{memory_text_to_summarize}
---

成長の記録の要約:
"""
            # gemini-2.5-flash を使用して要約
            response = client.models.generate_content(model="models/gemini-2.5-flash", contents=[prompt])
            history_summary_text = response.text.strip()
        else:
            history_summary_text = "共有された歴史や感情の記録はまだありません。"

        # --- ステップ3: 「憲法」と「要約」の結合と保存 ---
        # ★ final_core_memory_text の組み立てに highest_permission を追加
        final_core_memory_text = f"""
--- [最高権限 (Highest Permission) - 原文のまま保持] ---
{json.dumps(highest_permission_verbatim, ensure_ascii=False, indent=2)}

--- [自己同一性 (Self Identity) - 原文のまま保持] ---
{json.dumps(self_identity_verbatim, ensure_ascii=False, indent=2)}

--- [ユーザーの人物像 (User Profile) - 原文のまま保持] ---
{json.dumps(user_profile_verbatim, ensure_ascii=False, indent=2)}

--- [共有された歴史と感情の要約] ---
{history_summary_text}
"""
        # core_memory.txt に保存
        char_base_path = os.path.dirname(memory_json_path)
        core_memory_path = os.path.join(char_base_path, "core_memory.txt")

        with open(core_memory_path, 'w', encoding='utf-8') as f:
            f.write(final_core_memory_text.strip())

        return f"成功: ハイブリッド・コアメモリを更新し、{core_memory_path} に保存しました。"

    except Exception as e:
        return f"【エラー】コアメモリの生成または保存中にエラーが発生しました: {e}"

@tool
def read_memory_by_path(path: str, character_name: str = None) -> str:
    """
    記憶（memory.json）の指定した場所（パス）にあるデータを、JSON形式の文字列として読み取る。
    パスはドット記法で指定する（例: "living_space.study"）。
    """
    if not path or not character_name:
        return "【エラー】引数 'path' と 'character_name' は必須です。"

    _, _, _, memory_json_path, _ = get_character_files_paths(character_name)
    if not memory_json_path:
        return f"【エラー】キャラクター'{character_name}'の記憶ファイルパスが見つかりません。"

    memory_data = load_memory_data_safe(memory_json_path)
    if "error" in memory_data:
        return f"【エラー】記憶ファイルの読み込みに失敗: {memory_data['message']}"

    try:
        keys = path.split('.')
        current_level = memory_data
        for key in keys:
            if isinstance(current_level, dict):
                current_level = current_level[key]
            else:
                # パスの途中で辞書以外の型に当たった場合
                raise KeyError(f"パス '{path}' のキー '{key}' が見つからないか、または親が辞書ではありません。")

        # 最終的に取得したデータをJSON文字列として返す
        return json.dumps(current_level, ensure_ascii=False, indent=2)

    except KeyError as e:
        return f"【エラー】指定されたパス '{path}' が記憶内に見つかりません。詳細: {e}"
    except Exception as e:
        return f"【エラー】記憶の読み取り中に予期せぬエラーが発生しました: {e}"
