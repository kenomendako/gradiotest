def _generate_initial_scenery(character_name: str, api_key_name: str) -> Tuple[str, str]:
    """【復活】UIからの要求に応じて、高速モデルで情景のみを生成する"""
    from langchain_google_genai import ChatGoogleGenerativeAI
    from tools.memory_tools import read_memory_by_path
    import json
    import datetime
    import pytz

    print(f"--- UIからの独立した情景生成開始: {character_name} ---")
    api_key = config_manager.API_KEYS.get(api_key_name)
    if not character_name or not api_key:
        return "（エラー）", "（キャラクターまたはAPIキー未設定）"

    location_id = utils.get_current_location(character_name) or "living_space"
    space_details_raw = read_memory_by_path.invoke({"path": f"living_space.{location_id}", "character_name": character_name})

    location_display_name = location_id
    scenery_text = "（場所の定義がないため、情景を描写できません）"

    if not space_details_raw.startswith("【エラー】"):
        try:
            space_data = json.loads(space_details_raw)
            location_display_name = space_data.get("name", location_id) if isinstance(space_data, dict) else location_id

            # 高速LLMを初期化
            llm_flash = ChatGoogleGenerativeAI(model="gemini-2.5-flash", google_api_key=api_key)

            # 日本時間を取得
            jst_now = datetime.datetime.now(pytz.timezone('Asia/Tokyo'))

            scenery_prompt = (
                f"空間定義:{json.dumps(space_data, ensure_ascii=False, indent=2)}\n"
                f"時刻:{jst_now.strftime('%H:%M')} / 季節:{jst_now.month}月\n\n"
                "あなたは情景描写の専門家です。以下のルールに従い、この空間の「今この瞬間」を1〜2文で描写してください。\n"
                "【ルール】\n- 人物描写は含めない。\n- 五感に訴えかける写実的な描写を重視する。"
            )
            scenery_text = llm_flash.invoke(scenery_prompt).content
        except Exception as e:
            print(f"--- 情景生成中にエラー: {e} ---")
            scenery_text = "（情景の生成に失敗しました）"

    return location_display_name, scenery_text

def handle_location_change(character_name: str, location_id: str):
    """【復活】場所IDをファイルに書き込むだけの、静かな処理"""
    from tools.space_tools import set_current_location

    if not character_name or not location_id:
        gr.Warning("キャラクターと移動先を選択してください。")
        return gr.update(), gr.update()

    result = set_current_location.func(location=location_id, character_name=character_name)
    if "Success" not in result:
        gr.Error(f"場所の変更に失敗: {result}")
        return gr.update(), gr.update()

    # ファイル書き込みに成功したら、UIの表示を更新
    memory_data = load_memory_data_safe(get_character_files_paths(character_name)[3])
    new_location_name = memory_data.get("living_space", {}).get(location_id, {}).get("name", location_id)
    gr.Info(f"場所を「{new_location_name}」に変更しました。")

    # 情景は「次の対話で更新される」ことを示すメッセージを表示
    return new_location_name, "（次の対話時に、新しい場所の情景が描写されます）"

def handle_scenery_refresh(character_name: str, api_key_name: str):
    """【復活】UI上の「情景を更新」ボタンの処理"""
    if not character_name or not api_key_name:
        gr.Warning("キャラクターとAPIキーを選択してください。")
        return gr.update(), gr.update()

    gr.Info(f"「{character_name}」の情景を更新しています...")
    location_name, scenery_text = _generate_initial_scenery(character_name, api_key_name)
    gr.Info("情景を更新しました。")
    return location_name, scenery_text
