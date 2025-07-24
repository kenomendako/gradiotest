# gemini_api.py の内容を、以下のコードで完全に置き換えてください

import traceback
from typing import Any, List, Union, Optional, Dict
import os
import io
import base64
from PIL import Image
import google.genai as genai
import filetype

from agent.graph import app
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_google_genai.chat_models import _parse_chat_history
import config_manager
import utils
# import mem0_manager # 依存関係の問題のため、mem0は無効化
from character_manager import get_character_files_paths

# --- invoke_nexus_agent関数を全面的に書き換えます ---
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

    # --- 1. LangChain形式のメッセージ履歴を作成 ---
    lc_messages = []
    log_file, _, _, _, _ = get_character_files_paths(current_character_name)
    raw_history = utils.load_chat_log(log_file, current_character_name)
    limit = int(api_history_limit_state) if api_history_limit_state.isdigit() else 0
    if limit > 0 and len(raw_history) > limit * 2:
        raw_history = raw_history[-(limit * 2):]
    for h_item in raw_history:
        role, content = h_item.get('role'), h_item.get('content', '').strip()
        if not content: continue
        if role in ['model', 'assistant', current_character_name]: lc_messages.append(AIMessage(content=content))
        elif role in ['user', 'human']: lc_messages.append(HumanMessage(content=content))

    # --- 2. ユーザーの新しい入力を処理し、ルートを判定 ---
    user_message_parts_for_direct_api = []
    has_unsupported_media = False
    if user_input_text:
        user_message_parts_for_direct_api.append(user_input_text)

    if file_input_list:
        client = genai.Client(api_key=api_key)
        for file_obj in file_input_list:
            filepath = file_obj.name
            print(f"  - ファイル添付を処理中: {filepath}")
            try:
                kind = filetype.guess(filepath)
                mime_type = kind.mime if kind else "application/octet-stream"
                print(f"    - 検出されたMIMEタイプ: {mime_type}")

                if mime_type.startswith("image/"):
                    img = Image.open(filepath)
                    user_message_parts_for_direct_api.append(img)
                else:
                    has_unsupported_media = True
                    uploaded_file = client.files.upload(file=filepath)
                    user_message_parts_for_direct_api.append(uploaded_file)
            except Exception as e:
                print(f"    - 警告: ファイル処理中にエラー ({e})。テキストとして読み込みます。")
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        text_content = f.read()
                    user_message_parts_for_direct_api.append(f"--- 添付ファイル「{os.path.basename(filepath)}」の内容 ---\n{text_content}\n--- ファイル内容ここまで ---")
                except Exception as text_e:
                    print(f"    - 警告: ファイル '{os.path.basename(filepath)}' の読み込みに失敗しました。スキップします。エラー: {text_e}")

    # --- 3. ルート判定と実行 ---
    if has_unsupported_media:
        # --- ルートA: LangChainをバイパスし、google-genaiで直接APIを叩く ---
        print("--- [情報] LangChain非対応のファイル種別を検出。google-genaiダイレクトパスを使用します。 ---")
        try:
            client = genai.Client(api_key=api_key)
            model = client.models.get(f"models/{current_model_name}")

            # 履歴をgoogle-genaiが理解できる形式に変換
            _, history = _parse_chat_history(lc_messages, convert_system_message_to_human=True)
            history.append({"role": "user", "parts": user_message_parts_for_direct_api})

            # システムプロンプトを構築
            char_prompt_path = os.path.join("characters", current_character_name, "SystemPrompt.txt")
            character_prompt = ""
            if os.path.exists(char_prompt_path):
                with open(char_prompt_path, 'r', encoding='utf-8') as f: character_prompt = f.read().strip()

            # API呼び出し
            response = model.generate_content(
                history,
                safety_settings=config_manager.SAFETY_CONFIG,
                generation_config={"temperature": 1.0},
                system_instruction=character_prompt
            )
            final_response_text = response.text

        except Exception as e:
            print(f"--- [エラー] google-genaiダイレクトパスでの実行中にエラー ---")
            traceback.print_exc()
            return f"[ダイレクトパス実行エラー: {e}]"
    else:
        # --- ルートB: 通常通りLangGraphエンジンを使用 ---
        print("--- [情報] 通常のLangGraphパスを使用します。 ---")
        try:
            lc_user_message_parts = []
            for part in user_message_parts_for_direct_api:
                if isinstance(part, str):
                    lc_user_message_parts.append({"type": "text", "text": part})
                elif isinstance(part, Image.Image):
                    buffered = io.BytesIO()
                    save_image = part.convert('RGB') if part.mode in ('RGBA', 'P') else part
                    img_format = part.format or 'PNG'
                    save_image.save(buffered, format=img_format)
                    img_base64 = base64.b64encode(buffered.getvalue()).decode('utf-8')
                    mime_type = f"image/{img_format.lower()}"
                    lc_user_message_parts.append({ "type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{img_base64}"}})
            if lc_user_message_parts:
                 lc_messages.append(HumanMessage(content=lc_user_message_parts))

            initial_state = {
                "messages": lc_messages,
                "character_name": current_character_name, "api_key": api_key,
                "tavily_api_key": config_manager.TAVILY_API_KEY, "model_name": current_model_name,
            }
            final_state = app.invoke(initial_state)
            final_response_text = final_state['messages'][-1].content
        except Exception as e:
            print(f"--- [エラー] LangGraphパスでの実行中にエラー ---")
            traceback.print_exc()
            return f"[LangGraph実行エラー: {e}]"

    # --- 4. 共通の後処理 ---
    # try:
    #     mem0_instance = mem0_manager.get_mem0_instance(current_character_name, api_key)
    #     user_text_for_mem0 = "\n".join([part for part in user_message_parts_for_direct_api if isinstance(part, str)])
    #     if user_text_for_mem0:
    #         mem0_instance.add([
    #             {"role": "user", "content": user_text_for_mem0},
    #             {"role": "assistant", "content": final_response_text}
    #         ], user_id=current_character_name)
    #         print("--- mem0への記憶成功 ---")
    # except Exception as e:
    #     print(f"--- mem0への記憶中にエラー: {e} ---")

    return final_response_text


def get_model_token_limits(model_name: str, api_key: str) -> Optional[Dict[str, int]]:
    if model_name in utils._model_token_limits_cache:
        return utils._model_token_limits_cache[model_name]
    if not api_key or api_key.startswith("YOUR_API_KEY"):
        return None
    try:
        client = genai.Client(api_key=api_key)
        model_info = client.models.get(model=f"models/{model_name}")
        if model_info and hasattr(model_info, 'input_token_limit') and hasattr(model_info, 'output_token_limit'):
            limits = {"input": model_info.input_token_limit, "output": model_info.output_token_limit}
            utils._model_token_limits_cache[model_name] = limits
            return limits
        return None
    except Exception as e:
        print(f"モデル情報の取得中にエラー: {e}")
        return None

def _convert_lc_to_gg_for_count(messages: List[Union[SystemMessage, HumanMessage, AIMessage]]) -> List[Dict]:
    contents = []
    for msg in messages:
        role = "model" if isinstance(msg, AIMessage) else "user"
        sdk_parts = []
        if isinstance(msg.content, str):
            sdk_parts.append({"text": msg.content})
        elif isinstance(msg.content, list):
             for part_data in msg.content:
                if isinstance(part_data, dict) and part_data.get("type") == "text":
                    sdk_parts.append({"text": part_data["text"]})
        if sdk_parts:
            contents.append({"role": role, "parts": sdk_parts})
    return contents

def count_tokens_from_lc_messages(messages: List, model_name: str, api_key: str) -> int:
    if not messages: return 0
    try:
        client = genai.Client(api_key=api_key)
        contents = _convert_lc_to_gg_for_count(messages)
        final_contents_for_api = []
        if contents and isinstance(messages[0], SystemMessage):
             system_instruction = contents[0]['parts']
             final_contents_for_api.extend([
                 {"role": "user", "parts": system_instruction},
                 {"role": "model", "parts": [{"text": "OK"}]}
             ])
             final_contents_for_api.extend(contents[1:])
        else:
            final_contents_for_api = contents
        result = client.models.count_tokens(model=f"models/{model_name}", contents=final_contents_for_api)
        return result.total_tokens
    except Exception as e:
        print(f"トークン計算エラー: {e}")
        return -1
