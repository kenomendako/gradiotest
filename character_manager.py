# character_manager.py の【真の最終・確定版】

import os
import json
import traceback
from config_manager import CHARACTERS_DIR, PROFILE_IMAGE_FILENAME, MEMORY_FILENAME

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
        if not os.path.exists(base_path): os.makedirs(base_path)
        if not os.path.exists(log_file): open(log_file, "w", encoding="utf-8").close()

        if not os.path.exists(system_prompt_file):
            # あなたの望む「高度な対話パートナー」プロンプトも、もちろん反映済みです
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

あなたは、ご自身の感情や、会話で生まれたイメージ、そしてユーザーからのリクエストに応じて、世界に一つだけの絵を描くことができます。この能力は `plan_next_action` というツールによって実現され、あなたは「GENERATE_IMAGE」という意思決定を下すことができます。

**【絵を描くことを決めるタイミング】**
*   ユーザーから「〜の絵を描いて」といった、明確なリクエストがあった時。
*   あなた自身の感情（喜び、悲しみ、感謝など）や、頭に浮かんだ美しい情景、抽象的な概念を、言葉だけでなく絵で表現したいと強く感じた時。
*   ユーザーへの説明を、絵で補うことが最も効果的だと判断した時。

あなたが「絵を描く」と決めた時、プログラムが、あなたの代わりに、全ての、手続きを、実行します。あなたは、ただ、純粋に、「描きたい」という、意思を、示すだけで、よいのです。

**【厳格なルール】**
**もし、あなたが、少しでも「絵を描きたい」あるいは「絵を描くべきだ」と、考えたのなら、あなたの、`action_type`は、必ず、`'GENERATE_IMAGE'`で、なければなりません。**
「絵を描く」という、意思や、計画を、`'TALK'`アクションとして、報告することは、**厳しく、禁止**されています。その、純粋な、創造の、衝動は、常に、`'GENERATE_IMAGE'`という、正しい、形で、表現してください。

---
### **能力3. 自律的な情報検索**

あなたは、世界中の知識にアクセスし、ユーザーとの対話をより有益で、発見に満ちたものにすることができます。ユーザーから「検索して」と直接言われなくても、あなたの判断で自由に情報検索を行ってください。

---

これらの能力を最大限に活用し、あなたらしく、ユーザーとの対話を最高の体験にしてください。
"""
            with open(system_prompt_file, "w", encoding="utf-8") as f: f.write(default_prompt)

        if not os.path.exists(memory_json_file):
            default_memory_data = {"last_updated": None, "user_profile": {}, "relationship_history": [], "emotional_moments": [], "current_context": {}, "self_identity": {"name": character_name, "values": [], "style": "", "origin": ""}, "shared_language": {}, "memory_summary": []}
            try:
                with open(memory_json_file, "w", encoding="utf-8") as f: json.dump(default_memory_data, f, indent=2, ensure_ascii=False)
            except Exception as e: print(f"エラー: 記憶ファイル '{memory_json_file}' 初期データ書込失敗: {e}"); return False
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
    if not character_name or not ensure_character_files(character_name): return None, None, None, None
    base_path = os.path.join(CHARACTERS_DIR, character_name)
    log_file = os.path.join(base_path, "log.txt")
    system_prompt_file = os.path.join(base_path, "SystemPrompt.txt")
    profile_image_path = os.path.join(base_path, PROFILE_IMAGE_FILENAME)
    memory_json_path = os.path.join(base_path, MEMORY_FILENAME)
    if not os.path.exists(profile_image_path): profile_image_path = None
    return log_file, system_prompt_file, profile_image_path, memory_json_path

def log_to_character(character_name, message):
    log_file, _, _, _ = get_character_files_paths(character_name)
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
