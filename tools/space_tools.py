# tools/space_tools.py
import os
import json
import re
from typing import Optional
from langchain_core.tools import tool
from character_manager import get_world_settings_path
from memory_manager import load_memory_data_safe
import traceback

@tool
def find_location_id_by_name(location_name: str, character_name: str = None) -> str:
    """
    「書斎」や「屋上テラス」といった日本語の場所名から、システムが使うための正式なID（例: "study", "Rooftop Terrace"）を検索して返す。
    """
    if not location_name or not character_name:
        return "【Error】Location name and character name are required."

    world_settings_path = get_world_settings_path(character_name)
    if not world_settings_path or not os.path.exists(world_settings_path):
        return f"【Error】Could not find world settings file for character '{character_name}'."

    from utils import parse_world_markdown
    world_data = parse_world_markdown(world_settings_path)
    if not world_data:
        return f"【Error】Could not load or parse world settings for '{character_name}'."

    # ▼▼▼ 新しい、堅牢な再帰検索ロジック ▼▼▼
    def find_id_recursive(data: dict) -> Optional[str]:
        # data自体が辞書でない場合は探索終了
        if not isinstance(data, dict):
            return None

        for key, value in data.items():
            # 値が辞書であり、'name'キーが探している名前と一致する場合
            if isinstance(value, dict) and value.get("name", "").lower() == location_name.lower():
                return key # IDであるキーを返す

            # さらに深い階層を探索
            found_id = find_id_recursive(value)
            if found_id:
                return found_id

        return None

    # トップレベルから探索を開始
    found_location_id = find_id_recursive(world_data)
    # ▲▲▲ 修正ここまで ▲▲▲

    if found_location_id:
        return found_location_id
    else:
        return f"【Error】Location '{location_name}' not found. Check for typos or define it first."


@tool
def set_current_location(location: str, character_name: str = None) -> str:
    """
    AIの現在地を設定する。この世界のどこにいるかを宣言するための、唯一の公式な手段。
    location: "study"のような場所のID、または"書斎"のような日本語名を指定。
    """
    if not location or not character_name:
        return "【Error】Location and character name are required."

    # --- 世界設定を読み込む ---
    world_settings_path = get_world_settings_path(character_name)
    if not world_settings_path or not os.path.exists(world_settings_path):
        return f"【Error】Could not find world settings file for character '{character_name}'."
    from utils import parse_world_markdown
    world_data = parse_world_markdown(world_settings_path)
    if not world_data:
        return f"【Error】Could not load or parse world settings for '{character_name}'."

    final_id_to_set = None

    # --- 1. まず、渡された文字列が有効な「ID」として存在するかチェック ---
    from character_manager import find_space_data_by_id_recursive
    if find_space_data_by_id_recursive(world_data, location) is not None:
        final_id_to_set = location
        print(f"  - 入力 '{location}' は有効な場所IDとして直接認識されました。")
    else:
        # --- 2. IDとして見つからなければ、「名前」として検索を試みる ---
        print(f"  - 入力 '{location}' は直接的なIDではないため、名前として検索します...")
        id_from_name = find_location_id_by_name.func(location_name=location, character_name=character_name)
        if not id_from_name.startswith("【Error】"):
            final_id_to_set = id_from_name
            print(f"  - 名前 '{location}' から場所ID '{final_id_to_set}' を特定しました。")

    # --- 3. IDが確定したらファイルに書き込み、さもなければエラーを返す ---
    if final_id_to_set:
        try:
            base_path = os.path.join("characters", character_name)
            location_file_path = os.path.join(base_path, "current_location.txt")
            with open(location_file_path, "w", encoding="utf-8") as f:
                f.write(final_id_to_set.strip())
            return f"Success: Current location has been set to '{final_id_to_set}'."
        except Exception as e:
            return f"【Error】現在地のファイル書き込みに失敗しました: {e}"
    else:
        return f"【Error】場所 '{location}' は有効なIDまたは名前として見つかりませんでした。"

#
# tools/space_tools.py の一番下に、このコードブロックをそのまま追加してください
#
def _get_location_section(full_content: str, location_id: str) -> Optional[str]:
    """Markdownコンテンツから特定のIDのセクション（## または ###）を抽出する"""
    pattern = re.compile(
        rf"(^(?:##|###) {re.escape(location_id)}\s*\n.*?)(\n^(?:##|###) |\Z)",
        re.MULTILINE | re.DOTALL
    )
    match = pattern.search(full_content)
    return match.group(1).strip() if match else None

@tool
def read_world_settings(character_name: str = None) -> str:
    """
    世界設定ファイル（world_settings.md）の全ての情報をテキスト形式で読み取る。
    新しい場所を追加したり、既存の場所を編集する前に、まず全体の構造を把握するために使用する。
    """
    if not character_name:
        return "【Error】Character name is required."
    world_settings_path = get_world_settings_path(character_name)
    if not world_settings_path or not os.path.exists(world_settings_path):
        return f"【Error】Could not find world settings file for character '{character_name}'."
    try:
        with open(world_settings_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"【Error】Failed to read world settings file: {e}"


@tool
def update_location_settings(location_id: str, new_content: str, character_name: str = None) -> str:
    """
    【更新専用】世界設定ファイル内の既存の場所（エリアまたは部屋）の定義を、新しい内容で完全に上書きする。
    注意：このツールはセクション全体を置き換えるため、追記したい場合は、まずread_specific_location_settingsで読み取り、編集してからこのツールを使用すること。
    新しい場所を作成する場合は、代わりにadd_new_locationを使用すること。
    """
    if not all([location_id, new_content, character_name]):
        return "【Error】location_id, new_content, and character_name are required."

    world_settings_path = get_world_settings_path(character_name)
    if not world_settings_path or not os.path.exists(world_settings_path):
        return f"【Error】Could not find world settings file for character '{character_name}'."

    try:
        with open(world_settings_path, "r", encoding="utf-8") as f:
            full_content = f.read()

        section_to_replace = _get_location_section(full_content, location_id)

        if not section_to_replace:
            return f"【Error】Location ID '{location_id}' not found. You cannot create a new location with this tool. Use 'add_new_location' instead."

        if not re.match(r"^(##|###)\s+", new_content.strip()):
            return f"【Error】'new_content' must start with a valid markdown heading (e.g., '## {location_id}' or '### {location_id}')."

        updated_content = full_content.replace(section_to_replace, new_content.strip())

        with open(world_settings_path, "w", encoding="utf-8") as f:
            f.write(updated_content.strip() + "\n")

        return f"Success: World settings for '{location_id}' have been updated."
    except Exception as e:
        return f"【Error】Failed to update world settings: {e}"

@tool
def add_new_location(new_content: str, character_name: str = None) -> str:
    """
    【新規作成専用】世界設定ファイルに、新しい場所（エリアまたは部屋）の定義を追記する。
    既存の場所を更新する場合は、update_location_settingsを使用すること。
    """
    if not all([new_content, character_name]):
        return "【Error】new_content and character_name are required."

    world_settings_path = get_world_settings_path(character_name)
    if not world_settings_path or not os.path.exists(world_settings_path):
        return f"【Error】Could not find world settings file for character '{character_name}'."

    try:
        # new_contentからIDを抽出
        match = re.match(r"^(?:##|###)\s+([a-zA-Z0-9_]+)", new_content.strip())
        if not match:
            return "【Error】'new_content' must start with a valid markdown heading containing an ID (e.g., '## new_area_id')."

        location_id = match.group(1)

        with open(world_settings_path, "r", encoding="utf-8") as f:
            full_content = f.read()

        if _get_location_section(full_content, location_id):
            return f"【Error】Location ID '{location_id}' already exists. Use 'update_location_settings' to modify it."

        updated_content = full_content.strip() + "\n\n" + new_content.strip()

        with open(world_settings_path, "w", encoding="utf-8") as f:
            f.write(updated_content.strip() + "\n")

        return f"Success: New location '{location_id}' has been added to the world settings."
    except Exception as e:
        return f"【Error】Failed to add new location: {e}"

@tool
def format_text_to_yaml(text_input: str, character_name: str, api_key: str) -> str:
    """
    ユーザーやAIが記述した自由形式のテキストを、world_settings.mdで利用可能な、
    厳格なYAML形式のセクションボディに変換する。
    """
    if not all([text_input, character_name, api_key]):
        return "【Error】Text input, character name, and API key are required."

    print(f"--- AIによるYAML整形ツール実行 (Character: {character_name}) ---")
    try:
        from gemini_api import get_configured_llm

        formatter_llm = get_configured_llm("gemini-2.5-flash", api_key, timeout=30)

        # ▼▼▼ 修正の核心：曖昧な入力にも対応できるようにプロンプトを高度化 ▼▼▼
        prompt_template = (
            "あなたは、自由形式のテキストを、厳格なYAML形式に変換することに特化した、高度な構造化AIです。\n"
            "以下の「場所の定義テキスト」を解析し、`world_settings.md` ファイルのセクションボディとして使用できる、有効なYAMLコードに変換してください。\n\n"
            "【最重要ルール】\n"
            "- もし入力テキストに複数の場所の定義が含まれているように見える場合、あなたは必ず**最初の場所の定義だけを処理し、2つ目以降は完全に無視**しなければなりません。\n"
            "- あなたの唯一のタスクは、YAMLコードを生成することです。それ以外の応答は絶対に行わないでください。\n"
            "- 解釈に迷う部分があっても、あなたが最も適切だと判断したYAMLの構造に当てはめて、最善を尽くして出力を生成してください。決して沈黙したり、エラーを返したりしてはいけません。\n"
            "- 出力には、YAMLコード以外の、いかなる説明や挨拶、前置き、後書き（例: ```yaml```）も絶対に含めてはなりません。\n"
            "- キーは必ず半角英数字にしてください（例: 「家具」-> `furniture`）。お手本にないキー（例: `style`）も、可能なら英語に翻訳して維持してください。\n"
            "- `⦁`のような記号で始まるリストも、`- name:` で始まるリスト形式に変換してください。\n\n"
            "【出力フォーマットの例】\n"
            "name: 場所の名前\n"
            "description: 場所の説明文。\n"
            "furniture:\n"
            "  - name: 家具1の名前\n"
            "    description: 家具1の説明\n"
            "ambiance:\n"
            "  atmosphere: 雰囲気の説明\n\n"
            "---\n"
            "場所の定義テキスト:\n"
            "{text_input}\n"
            "---\n\n"
            "変換後のYAMLコード:\n"
        )
        prompt = prompt_template.format(text_input=text_input)

        response = formatter_llm.invoke(prompt)

        if not response or not response.content or not response.content.strip():
            return "【Error】AIからの応答が空でした。テキストが複雑すぎるか、解釈不能な可能性があります。"

        return response.content.strip()

    except Exception as e:
        if "timeout" in str(e).lower():
            return "【Error】AIによる整形処理がタイムアウトしました。テキストを短くするか、後でもう一度試してください。"
        traceback.print_exc()
        return f"【Error】Failed to format text to YAML: {e}"
