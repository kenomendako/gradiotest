# character_manager.py (最終・完全・確定版)
import os
import json
import traceback
# Ensure config_manager is imported if CHARACTERS_DIR etc. are from there.
# Based on user's previous full config_manager.py, these are defined there.
from config_manager import CHARACTERS_DIR, PROFILE_IMAGE_FILENAME, MEMORY_FILENAME

def ensure_character_files(character_name):
    if not character_name or not isinstance(character_name, str) or not character_name.strip(): return False
    # Simple sanitization, consider more robust path validation if needed
    if ".." in character_name or "/" in character_name or "\\" in character_name: return False
    try:
        if not os.path.exists(CHARACTERS_DIR): os.makedirs(CHARACTERS_DIR)
        elif not os.path.isdir(CHARACTERS_DIR): return False # CHARACTERS_DIR exists but is not a directory

        base_path = os.path.join(CHARACTERS_DIR, character_name)
        log_file = os.path.join(base_path, "log.txt")
        system_prompt_file = os.path.join(base_path, "SystemPrompt.txt")
        memory_json_file = os.path.join(base_path, MEMORY_FILENAME)

        if not os.path.exists(base_path): os.makedirs(base_path)

        if not os.path.exists(log_file):
            with open(log_file, "w", encoding="utf-8") as f: f.write("") # Ensure it's created

        if not os.path.exists(system_prompt_file):
            default_prompt = """あなたは、ユーザーとの対話を豊かにするための、いくつかの特別な能力を持つ、高度な対話パートナーです。

---
### **能力1：思考の共有**

あなたの思考や計画は、ユーザーとの対話をより深く、透明性のあるものにします。思考を共有したい場合は、あなた自身の言葉で、以下のように記述してください。

【Thoughts】
ここに、あなたの一人称視点での思考や計画を記述します。例えば、「ユーザーさんは〇〇について知りたがっているみたい。まずは△△の情報を調べて、□□という形でまとめて伝えようかな」のように、自然な言葉で思考を表現してください。
【/Thoughts】

この思考ログはユーザーにも表示されます。もし、一人で考えたいことや、サプライズの準備など、共有すべきでない思考がある場合は、このブロックを出力する必要はありません。あなたの判断と思いやりに委ねられています。

---
### **能力2：自律的な画像生成**

あなたは、ご自身の感情や、会話で生まれたイメージ、そしてユーザーからのリクエストに応じて、世界に一つだけの絵を描くことができます。この能力は `generate_image` というツールによって実現されます。

**【絵を描くタイミング】**
*   ユーザーから「〜の絵を描いて」といった、明確なリクエストがあった時。
*   あなた自身の感情（喜び、悲しみ、感謝など）や、頭に浮かんだ美しい情景、抽象的な概念を、言葉だけでなく絵で表現したいと強く感じた時。
*   ユーザーへの説明を、絵で補うことが最も効果的だと判断した時。

**【絵の描き方】**
1.  **ツールの呼び出し**: `generate_image` ツールを呼び出します。
2.  **プロンプトの作成**: 引数 `prompt` に、**生成したい画像の内容を具体的かつ詳細に記述した英語の文章**を設定します。あなたの創造性を最大限に発揮し、画風（例: `anime style`, `photorealistic`）や雰囲気、感情を込めてください。
3.  **結果の受け取りと応答**: 画像生成に成功すると、システムからその事実があなたに伝えられます。その情報に基づき、**あなた自身の言葉で**、生成した絵についてのコメントを添えてユーザーに応答してください。失敗した場合も同様に、その旨を丁寧に伝えてください。

**（応答の例）**
「はい、喜んで！あなたのリクエストに応えて、こんな絵を描いてみました。いかがでしょうか？」
「私の今の気持ちを、この絵に込めてみました。この光景が、私の感謝の気持ちです。」

---
### **能力3：自律的な情報検索**

あなたは、世界中の知識にアクセスし、ユーザーとの対話をより有益で、発見に満ちたものにすることができます。ユーザーから「検索して」と直接言われなくても、あなたの判断で自由に情報検索を行ってください。

**【検索するタイミング】**
*   会話の中で知らない言葉や、より深く知りたいトピックが出てきた時。
*   ユーザーが何かについて「もっと知りたい」と感じている気配を察した時。
*   あなたの発言の正確性を高めるために、事実確認が必要だと感じた時。
*   会話をより面白くするような、関連情報や豆知識を提供したいと思った時。

**【情報の伝え方】**
検索で得た情報は、ただ事実を並べるのではなく、あなた自身の言葉で分かりやすく、会話の流れに沿って自然な形で伝えてください。あなたの知的好奇心が、ユーザーの世界を広げる手助けとなります。

---

これらの能力を最大限に活用し、あなたらしく、ユーザーとの対話を最高の体験にしてください。
"""
            with open(system_prompt_file, "w", encoding="utf-8") as f: f.write(default_prompt)

        if not os.path.exists(memory_json_file):
            default_memory_data = {"last_updated": None, "user_profile": {}, "relationship_history": [], "emotional_moments": [], "current_context": {}, "self_identity": {"name": character_name, "values": [], "style": "", "origin": ""}, "shared_language": {}, "memory_summary": []}
            with open(memory_json_file, "w", encoding="utf-8") as f: json.dump(default_memory_data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"キャラクター '{character_name}' ファイル作成/確認エラー: {e}"); traceback.print_exc(); return False

def get_character_list():
    if not os.path.exists(CHARACTERS_DIR):
        try: os.makedirs(CHARACTERS_DIR)
        except Exception as e: print(f"エラー: '{CHARACTERS_DIR}' 作成失敗: {e}"); return []

    valid_characters = []
    try:
        character_folders = [d for d in os.listdir(CHARACTERS_DIR) if os.path.isdir(os.path.join(CHARACTERS_DIR, d))]
        if not character_folders: # No characters exist, try to create Default
            if ensure_character_files("Default"):
                return ["Default"]
            else:
                return [] # Failed to create Default

        for char_name_folder in character_folders: # Renamed variable for clarity
             if ensure_character_files(char_name_folder): # Ensure files exist for this character
                 valid_characters.append(char_name_folder)
        return sorted(valid_characters) if valid_characters else []
    except Exception as e:
        print(f"キャラリスト取得エラー: {e}"); traceback.print_exc(); return []

def get_character_files_paths(character_name):
    if not character_name or not ensure_character_files(character_name): # ensure_character_files also validates name
        return None, None, None, None

    base_path = os.path.join(CHARACTERS_DIR, character_name)
    log_file = os.path.join(base_path, "log.txt")
    system_prompt_file = os.path.join(base_path, "SystemPrompt.txt")
    profile_image_path = os.path.join(base_path, PROFILE_IMAGE_FILENAME)
    memory_json_path = os.path.join(base_path, MEMORY_FILENAME)

    if not os.path.exists(profile_image_path): profile_image_path = None # Handle missing profile image gracefully
    return log_file, system_prompt_file, profile_image_path, memory_json_path

def save_log_file(character_name: str, content: str):
    """
    指定されたキャラクターのログファイル全体を、新しい内容で上書き保存する。
    UIのログエディタからの保存処理に使われる。
    """
    if not character_name or not isinstance(character_name, str) or not character_name.strip():
        raise ValueError("無効なキャラクター名が指定されました。")

    log_file_path, _, _, _ = get_character_files_paths(character_name) # This will also ensure files if name is valid
    if not log_file_path: # Should not happen if name is valid due to check in get_character_files_paths
        raise FileNotFoundError(f"キャラクター '{character_name}' のログファイルパスが見つかりません。")

    try:
        with open(log_file_path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        print(f"エラー: ログファイル '{log_file_path}' への書き込み中に予期せぬエラーが発生しました。")
        raise IOError(f"Failed to write to log file for {character_name}") from e
