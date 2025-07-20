import datetime
import traceback
import os
import re
from typing import Any, List, Dict, Union

import gradio as gr

import gemini_api
import utils
from character_manager import get_character_files_paths
from config_manager import (
    save_message_to_log,
    _get_user_header_from_log
)
from memory_manager import update_token_count


def handle_message_submission(*args: Any):
    (textbox_content, chatbot_history, current_character_name, current_model_name,
     current_api_key_name_state, file_input_list, add_timestamp_checkbox,
     send_thoughts_state, api_history_limit_state,
     send_notepad_state, use_common_prompt_state) = args

    user_prompt_from_textbox = textbox_content.strip() if textbox_content else ""

    # ★★★ 修正点1: ファイルのみの送信を許可する ★★★
    if not user_prompt_from_textbox and not file_input_list:
        # テキスト入力もファイル添付もない場合は、早期リターン
        token_count = update_token_count(None, None, current_character_name, current_model_name, current_api_key_name_state, api_history_limit_state, send_notepad_state, "", use_common_prompt_state)
        yield chatbot_history, gr.update(), gr.update(), token_count
        return

    timestamp = f"\n\n{datetime.datetime.now().strftime('%Y-%m-%d (%a) %H:%M:%S')}" if add_timestamp_checkbox else ""

    # ★★★ 修正点2: ログとUI表示用のメッセージを構築 ★★★
    log_message_parts = []
    ui_message_parts = []

    # テキスト部分を追加
    if user_prompt_from_textbox:
        processed_text = user_prompt_from_textbox + timestamp
        log_message_parts.append(processed_text)
        # UIにはタイムスタンプを含めないプレーンなテキストを表示
        chatbot_history.append({"role": "user", "content": user_prompt_from_textbox})

    # ファイル部分を追加
    if file_input_list:
        for file_obj in file_input_list:
            filepath = file_obj.name # GradioのFileオブジェクトからパスを取得
            filename = os.path.basename(filepath)
            # ログ記録用のタグを追加
            log_message_parts.append(f"[ファイル添付: {filepath}]")
            # UI表示用にタプルを追加
            chatbot_history.append({"role": "user", "content": (filepath, filename)})

    # ログに記録する最終的なメッセージ文字列
    final_log_message = "\n\n".join(log_message_parts).strip()

    # 「思考中...」をUIに追加
    chatbot_history.append({"role": "assistant", "content": "思考中... ▌"})

    # UIを更新（入力欄をクリア、思考中メッセージを表示）
    token_count = update_token_count(None, None, current_character_name, current_model_name, current_api_key_name_state, api_history_limit_state, send_notepad_state, "", use_common_prompt_state)
    yield chatbot_history, gr.update(value=""), gr.update(value=None), token_count

    final_response_text = ""
    try:
        # gemini_api.invoke_nexus_agent には、オリジナルの引数を渡す
        args_list = list(args)
        final_response_text = gemini_api.invoke_nexus_agent(*args_list)
    except Exception as e:
        traceback.print_exc()
        final_response_text = f"[UIハンドラエラー: {e}]"

    # --- ログ保存ロジック (UI更新より先に行う) ---
    log_f, _, _, _, _ = get_character_files_paths(current_character_name)
    if final_log_message: # ログに記録すべき内容がある場合のみ
        user_header = _get_user_header_from_log(log_f, current_character_name)
        save_message_to_log(log_f, user_header, final_log_message)
        if final_response_text:
            save_message_to_log(log_f, f"## {current_character_name}:", final_response_text)

    # 「思考中...」を削除
    chatbot_history.pop()

    # AIの応答を処理してUIに表示（この部分は変更なし）
    image_tag_pattern = re.compile(r"\[Generated Image: (.*?)\]")
    image_match = image_tag_pattern.search(final_response_text)
    if image_match:
        text_before_image = final_response_text[:image_match.start()].strip()
        image_path = image_match.group(1).strip()
        text_after_image = final_response_text[image_match.end():].strip()
        if text_before_image:
            chatbot_history.append({"role": "assistant", "content": utils.format_response_for_display(text_before_image)})
        absolute_image_path = os.path.abspath(image_path)
        if os.path.exists(absolute_image_path):
            chatbot_history.append({"role": "assistant", "content": (absolute_image_path, os.path.basename(image_path))})
        else:
            chatbot_history.append({"role": "assistant", "content": f"*[表示エラー: 画像 '{os.path.basename(image_path)}' が見つかりません]*"})
        if text_after_image:
            chatbot_history.append({"role": "assistant", "content": utils.format_response_for_display(text_after_image)})
    else:
        chatbot_history.append({"role": "assistant", "content": utils.format_response_for_display(final_response_text)})

    # 最終的なUI更新
    token_count = update_token_count(None, None, current_character_name, current_model_name, current_api_key_name_state, api_history_limit_state, send_notepad_state, "", use_common_prompt_state)
    yield chatbot_history, gr.update(), gr.update(value=None), token_count
