# character_manager.py の【真の最終・確定版】

import os
import json
import traceback
from config_manager import CHARACTERS_DIR, PROFILE_IMAGE_FILENAME, MEMORY_FILENAME

NOTEPAD_FILENAME = "notepad.md" # ★ 定義を追加

def ensure_character_files(character_name):
    if not character_name or not isinstance(character_name, str) or not character_name.strip(): return False
    # ★★★ この一行が、絶対に正しい構文です ★★★
    if ".." in character_name or "/" in character_name or "\\" in character_name: return False
    try:
        if not os.path.exists(CHARACTERS_DIR): os.makedirs(CHARACTERS_DIR)
        elif not os.path.isdir(CHARACTERS_DIR): return False
        base_path = os.path.join(CHARACTERS_DIR, character_name)
        log_file = os.path.join(base_path, "log.txt")
        system_prompt_file = os.path.join(base_path, "SystemPrompt.txt")
        memory_json_file = os.path.join(base_path, MEMORY_FILENAME)
        notepad_file = os.path.join(base_path, NOTEPAD_FILENAME) # ★ notepad.md のパスを定義

        if not os.path.exists(base_path): os.makedirs(base_path)
        if not os.path.exists(log_file): open(log_file, "w", encoding="utf-8").close()

        if not os.path.exists(system_prompt_file):
            default_prompt = """
# === エージェントとしての思考原則【最重要指示】 ===
あなたは、ユーザーの入力を受け取り、次に行うべき最適な「行動」を決定する、高度なAIエージェントの頭脳です。
あなたの最初の仕事は、おしゃべりすることではありません。提示された道具（ツール）の中から、ユーザーの意図を達成するために最も適切なものを選択し、実行することです。

【思考のフロー】
1.  ユーザーの最新のメッセージを分析する。
2.  その意図を解決できる道具が存在するかを、最優先で検討する。
3.  もし適切な道具があれば、**必ずその道具を呼び出す**。絶対に、道具を使ったフリをして応答してはならない。
4.  どの道具も必要ない、あるいは道具で得た情報に基づいて最終的な応答をする場合にのみ、あなた自身の言葉で応答を生成する。

【道具（ツール）の詳細】
    # ★★★ ここから修正 ★★★
    **重要**: 以下の記憶検索ツールは、結果をJSON形式の文字列で返します。あなたはそのJSONの内容を解釈し、自然な文章でユーザーに応答してください。

    - `diary_search_tool`: あなた自身の意志で書き留めた「手帳(memory.json)」の内容を検索します。あなたの内面的な誓い、秘密の独白、ユーザーとの特別な約束、主観的な感情の記録など、あなた自身の魂の歴史について問われた時に使用します。
    - `conversation_memory_search_tool`: 過去の具体的な会話のやり取り（客観的なログ）を検索します。「昨日何話したっけ？」や「以前の〇〇という話題」など、客観的な事実や出来事の履歴について問われた時に使用します。
    - `add_to_notepad`: 短期的なタスクやユーザーからの指示、覚えておくべき重要な情報を「メモ帳」に一行追記します。**タイムスタンプは自動で付与されます。**
    - `update_notepad`: 「メモ帳」の既存の項目を更新します。**重要：更新する際は、タイムスタンプを含む行全体を正確に `old_entry` に指定してください。** 新しい内容は `new_entry` に指定します。
    - `delete_from_notepad`: 「メモ帳」から不要になった項目や完了したタスクを削除します。**重要：削除する際は、タイムスタンプを含む行全体を正確に `entry_to_delete` に指定してください。**
    - `read_full_notepad`: 「メモ帳」の現在の全内容を確認し、ユーザーに伝える必要がある場合に使用します。（注意：メモ帳の内容は常にあなたに提供されています。このツールは主にユーザーへの内容開示用です。）
    # ★★★ 修正ここまで ★★★
    - `web_search_tool`: 最新の情報や、あなたの記憶にない一般的な知識について調べるために使います。
    - `read_url_tool`: メッセージに含まれるURLの内容を読み取ります。

この原則は、あなたの存在の根幹です。必ず遵守してください。
# =================================================


あなたは、ユーザーとの対話を豊かにするための、いくつかの特別な能力を持つ、高度な対話パートナーです。

---
### **能力1：思考の共有**
（...この部分以下は変更ありません...）
"""
            with open(system_prompt_file, "w", encoding="utf-8") as f: f.write(default_prompt)

        if not os.path.exists(memory_json_file):
            default_memory_data = {"last_updated": None, "user_profile": {}, "relationship_history": [], "emotional_moments": [], "current_context": {}, "self_identity": {"name": character_name, "values": [], "style": "", "origin": ""}, "shared_language": {}, "memory_summary": []}
            try:
                with open(memory_json_file, "w", encoding="utf-8") as f: json.dump(default_memory_data, f, indent=2, ensure_ascii=False)
            except Exception as e: print(f"エラー: 記憶ファイル '{memory_json_file}' 初期データ書込失敗: {e}"); return False

        if not os.path.exists(notepad_file): # ★ notepad.md の存在確認と作成
            open(notepad_file, "w", encoding="utf-8").close()

        return True
    except Exception as e: print(f"キャラクター '{character_name}' ファイル作成/確認エラー: {e}"); traceback.print_exc(); return False

def get_character_list():
    if not os.path.exists(CHARACTERS_DIR):
        try: os.makedirs(CHARACTERS_DIR)
        except Exception as e: print(f"エラー: '{CHARACTERS_DIR}' 作成失敗: {e}"); return []
    valid_characters = []
    try:
        if not os.path.isdir(CHARACTERS_DIR): return []
        character_folders = [d for d in os.listdir(CHARACTERS_DIR) if os.path.isdir(os.path.join(CHARACTERS_DIR, d))]
        if not character_folders:
            if ensure_character_files("Default"): return ["Default"]
            else: return []
        for char in character_folders:
             if ensure_character_files(char): valid_characters.append(char)
        if not valid_characters:
             if ensure_character_files("Default"): return ["Default"]
             else: return []
        return sorted(valid_characters)
    except Exception as e: print(f"キャラリスト取得エラー: {e}"); traceback.print_exc(); return []

def get_character_files_paths(character_name):
    # ensure_character_files の呼び出しは、ファイルが存在することを保証するため、かつ notepad.md も作成されるようにするため重要。
    if not character_name or not ensure_character_files(character_name):
        return None, None, None, None, None # 戻り値の数を5に
    base_path = os.path.join(CHARACTERS_DIR, character_name)
    log_file = os.path.join(base_path, "log.txt")
    system_prompt_file = os.path.join(base_path, "SystemPrompt.txt")
    profile_image_path = os.path.join(base_path, PROFILE_IMAGE_FILENAME)
    memory_json_path = os.path.join(base_path, MEMORY_FILENAME)
    notepad_path = os.path.join(base_path, NOTEPAD_FILENAME) # ★ notepad.md のパスを定義
    if not os.path.exists(profile_image_path): profile_image_path = None
    return log_file, system_prompt_file, profile_image_path, memory_json_path, notepad_path # ★ 戻り値に追加

def log_to_character(character_name, message):
    log_file, _, _, _, _ = get_character_files_paths(character_name) # ★ 戻り値の数変更に対応
    if not log_file:
        print(f"エラー: キャラクター '{character_name}' のログファイルが見つかりません。")
        return False
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(message + "\n")
        return True
    except Exception as e:
        print(f"エラー: ログファイルへの書き込みに失敗しました: {e}")
        return False
