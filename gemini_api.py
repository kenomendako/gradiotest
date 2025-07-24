# gemini_api.py の invoke_nexus_agent 関数のみを、以下のコードで置き換えてください

def invoke_nexus_agent(*args: Any) -> str:
    (textbox_content, chatbot_history, current_character_name, current_model_name,
     current_api_key_name_state, file_input_list, add_timestamp_checkbox,
     send_thoughts_state, api_history_limit_state,
     send_notepad_state, use_common_prompt_state) = args

    api_key = config_manager.API_KEYS.get(current_api_key_name_state)
    if not api_key or api_key.startswith("YOUR_API_KEY"):
        return f"[エラー: APIキー '{current_api_key_name_state}' が有効ではありません。]"

    user_input_text = textbox_content.strip() if textbox_content else ""
    if not user_input_text and not file_input_list:
         return "[エラー: テキスト入力またはファイル添付がありません]"

    messages = []
    log_file, _, _, _, _ = get_character_files_paths(current_character_name)
    raw_history = utils.load_chat_log(log_file, current_character_name)
    limit = int(api_history_limit_state) if api_history_limit_state.isdigit() else 0
    if limit > 0 and len(raw_history) > limit * 2:
        raw_history = raw_history[-(limit * 2):]
    for h_item in raw_history:
        role, content = h_item.get('role'), h_item.get('content', '').strip()
        if not content: continue
        if role in ['model', 'assistant', current_character_name]: messages.append(AIMessage(content=content))
        elif role in ['user', 'human']: messages.append(HumanMessage(content=content))

    user_message_parts = []
    if user_input_text:
        user_message_parts.append({"type": "text", "text": user_input_text})

    if file_input_list:
        client = genai.Client(api_key=api_key)
        for file_obj in file_input_list:
            filepath = file_obj.name
            print(f"  - ファイル添付を処理中: {filepath}")
            try:
                kind = filetype.guess(filepath)
                if kind is None:
                    raise TypeError("Cannot guess file type, attempting to read as text.")

                mime_type = kind.mime
                print(f"    - 検出されたMIMEタイプ: {mime_type}")

                if mime_type.startswith("image/"):
                    img = Image.open(filepath)
                    buffered = io.BytesIO()
                    img_format = img.format or 'PNG'
                    save_image = img.convert('RGB') if img.mode in ('RGBA', 'P') else img
                    save_image.save(buffered, format=img_format)
                    img_base64 = base64.b64encode(buffered.getvalue()).decode('utf-8')
                    user_message_parts.append({
                        "type": "image_url",
                        "image_url": { "url": f"data:{mime_type};base64,{img_base64}"}
                    })
                elif mime_type.startswith("audio/") or mime_type.startswith("video/"):
                    # ★★★ 最後の、そして真実の聖杯 ★★★
                    # お客様が見つけられた情報に基づき、LangChainが要求する唯一の正しい形式に変換する
                    uploaded_file = client.files.upload(
                        file=filepath
                    )
                    user_message_parts.append({
                        "type": "media_url",
                        "media_url": {"url": uploaded_file.uri}
                    })

                else:
                    raise TypeError("Unsupported MIME type, attempting to read as text.")

            except Exception as e:
                print(f"    - 警告: バイナリファイルとして処理中にエラー ({e})。テキストとして読み込みます。")
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        text_content = f.read()
                    user_message_parts.append({
                        "type": "text",
                        "text": f"--- 添付ファイル「{os.path.basename(filepath)}」の内容 ---\n{text_content}\n--- ファイル内容ここまで ---"
                    })
                except Exception as text_e:
                    print(f"    - 警告: ファイル '{os.path.basename(filepath)}' の読み込みに失敗しました。スキップします。エラー: {text_e}")

    if user_message_parts:
        messages.append(HumanMessage(content=user_message_parts))

    initial_state = {
        "messages": messages,
        "character_name": current_character_name,
        "api_key": api_key,
        "tavily_api_key": config_manager.TAVILY_API_KEY,
        "model_name": current_model_name,
    }

    try:
        final_state = app.invoke(initial_state)
        final_response_message = final_state['messages'][-1]

        try:
            mem0_instance = mem0_manager.get_mem0_instance(current_character_name, api_key)
            user_text_for_mem0 = "\n".join([part['text'] for part in user_message_parts if isinstance(part, dict) and part.get('type') == 'text' and part.get('text')])
            if user_text_for_mem0:
                mem0_instance.add([
                    {"role": "user", "content": user_text_for_mem0},
                    {"role": "assistant", "content": final_response_message.content}
                ], user_id=current_character_name)
                print("--- mem0への記憶成功 ---")
        except Exception as e:
            print(f"--- mem0への記憶中にエラー: {e} ---")

        return final_response_message.content
    except Exception as e:
        print(f"--- エージェント実行エラー ---")
        traceback.print_exc()
        return f"[エージェント実行エラー: {e}]"
