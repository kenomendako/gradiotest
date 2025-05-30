# -*- coding: utf-8 -*-
import google.genai as genai
from google.genai import types
from google.genai.types import Tool, GoogleSearch, GenerateContentConfig, Content, Part # Removed SafetySetting, HarmCategory, HarmBlockThreshold
from google.ai.generativelanguage import HarmCategory, SafetySetting, HarmBlockThreshold # Added new imports
import os
import json
import google.api_core.exceptions
import re
import math
import traceback
import base64 # Added for processing multiple file types
from PIL import Image # Kept for now, might be removed if not used elsewhere, but send_to_gemini will not use it directly for file parts
# config_manager モジュール全体をインポートするように変更
import config_manager
from utils import load_chat_log
from character_manager import get_character_files_paths

_gemini_client = None

# --- Google API (Gemini) 連携関数 ---
def configure_google_api(api_key_name):
    if not api_key_name: return False, "APIキー名が指定されていません。"
    # 関数内で config_manager.API_KEYS を参照するように変更
    api_key = config_manager.API_KEYS.get(api_key_name)
    if not api_key or api_key.startswith("YOUR_API_KEY"):
        # エラーメッセージは変更せず、参照方法のみ変更
        return False, f"APIキー名 '{api_key_name}' に対応する有効なAPIキーが設定されていません。"
    try:
        global _gemini_client
        _gemini_client = genai.Client(api_key=api_key)
        print(f"Google GenAI Client for API key '{api_key_name}' initialized successfully.") 
        return True, None
    except Exception as e:
        return False, f"APIキー '{api_key_name}' での genai.Client 初期化中にエラー: {e}"

def send_to_gemini(system_prompt_path, log_file_path, user_prompt, selected_model, character_name, send_thoughts_to_api, api_history_limit_option, uploaded_file_parts: list = None, memory_json_path=None):
    if _gemini_client is None:
        return "エラー: Geminiクライアントが初期化されていません。APIキーを設定してください。"

    print(f"--- 通常対話開始 (google-genai SDK) --- Thoughts API送信: {send_thoughts_to_api}, 履歴制限: {api_history_limit_option}")
    
    sys_ins_text = "あなたはチャットボットです。" # Renamed to avoid conflict with system_instruction parameter name
    if system_prompt_path and os.path.exists(system_prompt_path):
        try:
            with open(system_prompt_path, "r", encoding="utf-8") as f: sys_ins_text = f.read().strip() or sys_ins_text
        except Exception as e: print(f"システムプロンプト '{system_prompt_path}' 読込エラー: {e}")
    if memory_json_path and os.path.exists(memory_json_path):
        try:
            with open(memory_json_path, "r", encoding="utf-8") as f: mem = json.load(f)
            m_api = {k: v for k, v in {
                "user_profile": mem.get("user_profile"),
                "self_identity": mem.get("self_identity"),
                "shared_language": mem.get("shared_language"),
                "current_context": mem.get("current_context"),
                "memory_summary": mem.get("memory_summary", [])[-config_manager.MEMORY_SUMMARY_LIMIT_FOR_API:]
            }.items() if v}
            if m_api: sys_ins_text += f"\n\n---\n## 参考記憶:\n{json.dumps(m_api, indent=2, ensure_ascii=False)}\n---"
        except Exception as e: print(f"記憶ファイル '{memory_json_path}' 読込/処理エラー: {e}")

    msgs = load_chat_log(log_file_path, character_name)
    if api_history_limit_option.isdigit():
        limit_turns = int(api_history_limit_option)
        limit_msgs = limit_turns * 2
        if len(msgs) > limit_msgs:
            print(f"情報: API履歴を直近 {limit_turns} 往復 ({limit_msgs} メッセージ) に制限します。") # Log message kept from original
            msgs = msgs[-limit_msgs:]
        # else: # Removed redundant log messages about history length from original prompt for brevity
            # print(f"情報: API履歴は全 {len(msgs)} メッセージ ({math.ceil(len(msgs)/2)} 往復相当) を送信します（制限未満）。")
    # else:
        #  print(f"情報: API履歴は全 {len(msgs)} メッセージ ({math.ceil(len(msgs)/2)} 往復相当) を送信します。")

    api_contents = []
    th_pat = re.compile(r"【Thoughts】.*?【/Thoughts】\s*", re.DOTALL | re.IGNORECASE)
    for m in msgs:
        sdk_role = "user" if m.get("role") == "user" else "model"
        content_text = m.get("content", "")
        if not content_text: continue
        
        processed_text = content_text
        if sdk_role == "user":
            processed_text = re.sub(r"\[画像添付:[^\]]+\]", "", processed_text).strip()
        elif sdk_role == "model" and not send_thoughts_to_api: # Corrected this line from original
            processed_text = th_pat.sub("", processed_text).strip()
        
        if processed_text:
            api_contents.append(Content(role=sdk_role, parts=[Part(text=processed_text)]))

    current_turn_parts = []
    if user_prompt: # Ensure user_prompt is not None and not empty string
        current_turn_parts.append(Part(text=user_prompt))
    
    if uploaded_file_parts:
        for file_detail in uploaded_file_parts:
            file_path = file_detail['path']
            mime_type = file_detail['mime_type']
            if os.path.exists(file_path):
                try:
                    with open(file_path, 'rb') as f_bytes:
                        file_bytes = f_bytes.read()
                    encoded_data = base64.b64encode(file_bytes).decode('utf-8')
                    # Assuming google.genai.types.Part can take inline_data directly
                    current_turn_parts.append(Part(inline_data={"mime_type": mime_type, "data": encoded_data}))
                    print(f"情報: ファイル '{os.path.basename(file_path)}' ({mime_type}) をAPIリクエストに追加しました。")
                except Exception as e:
                    print(f"警告: ファイル '{os.path.basename(file_path)}' の処理中にエラー: {e}. スキップします。")
            else:
                print(f"警告: 指定されたファイルパス '{file_path}' が見つかりません。スキップします。")

    if not current_turn_parts:
        if user_prompt is not None or uploaded_file_parts: # Intended to send something, but it became empty
             return "エラー: 送信する有効なコンテンツがありません (テキストが空か、ファイル処理に失敗しました)。"
        # If both user_prompt is None and uploaded_file_parts is None/empty, it's a "continue" scenario
        # The API might require a final user message. If api_contents is also empty, it's an error.
        if not api_contents:
            return "エラー: 送信するメッセージ履歴も現在の入力もありません。"
        # If there's history, but no new user input, proceed. The last content part is model's or older user's.
        # The API likely expects the last part of `contents` to be the one to respond to, typically user's.
        # This could be an issue if current_turn_parts is empty but history is not.
        # For now, we allow sending history only, but this might need adjustment based on API behavior.

    if current_turn_parts: # Add current user's turn if there are any parts
        api_contents.append(Content(role="user", parts=current_turn_parts))
    
    if not api_contents: # Final check if somehow api_contents is still empty
        return "エラー: 最終的な送信コンテンツが空です。"

    tools_list = []
    if "2.5-pro" in selected_model.lower() or "2.5-flash" in selected_model.lower(): # Adjusted model name check
        try:
            # Ensure Tool and GoogleSearch are imported from google.genai.types
            google_search_tool = Tool(google_search=GoogleSearch())
            tools_list.append(google_search_tool)
            print("情報: Google検索グラウンディング (google-genai SDK) がセットアップされました。")
        except Exception as e:
            print(f"警告: GoogleSearch Toolのセットアップ中にエラー (google-genai SDK): {e}")
    
    generation_config_args = {}
    if tools_list:
        generation_config_args["tools"] = tools_list
    
    if config_manager.SAFETY_CONFIG:
        try:
            safety_settings_list = []
            for category, threshold in config_manager.SAFETY_CONFIG.items():
                safety_settings_list.append(SafetySetting(category=category, threshold=threshold))
            generation_config_args["safety_settings"] = safety_settings_list
            print(f"デバッグ: safety_settings_list: {safety_settings_list}") 
        except NameError as ne:
             print(f"警告: SafetySetting, HarmCategory, or HarmBlockThreshold types not found. Safety settings may not be correctly applied. Error: {ne}")
             try:
                safety_settings_list_of_dicts = []
                for category, threshold in config_manager.SAFETY_CONFIG.items():
                    safety_settings_list_of_dicts.append({"category": category, "threshold": threshold})
                generation_config_args["safety_settings"] = safety_settings_list_of_dicts
                print(f"デバッグ: safety_settings_list_of_dicts (fallback): {safety_settings_list_of_dicts}")
             except Exception as e_dict_conv:
                print(f"警告: Fallback conversion of safety_settings to list of dicts failed: {e_dict_conv}. Passing raw dict.")
                generation_config_args["safety_settings"] = config_manager.SAFETY_CONFIG 
        except Exception as e_ss:
            print(f"警告: Error processing safety settings: {e_ss}. Safety settings may not be applied.")
            generation_config_args["safety_settings"] = config_manager.SAFETY_CONFIG 
    
    # response_modalities from user example, consider if always needed or configurable.
    # generation_config_args["response_modalities"] = ["TEXT"] 

    # Prepare formatted_safety_settings (moved this block higher, before model init)
    formatted_safety_settings = []
    if config_manager.SAFETY_CONFIG:
        try:
            for category, threshold in config_manager.SAFETY_CONFIG.items():
                formatted_safety_settings.append(SafetySetting(category=category, threshold=threshold))
            print(f"デバッグ: formatted_safety_settings for send_to_gemini: {formatted_safety_settings}")
        except NameError as ne: # Should not happen due to corrected imports
            print(f"警告: SafetySetting, HarmCategory, or HarmBlockThreshold types not found for send_to_gemini. Safety settings may not be correctly applied. Error: {ne}")
        except Exception as e_ss:
            print(f"警告: Error processing safety settings for send_to_gemini: {e_ss}. Safety settings may not be applied.")
    
    if not formatted_safety_settings: # Ensure it's None if empty, for get_generative_model
        formatted_safety_settings = None

    # Model Initialization
    model_init_args = {"model_name": selected_model}
    if sys_ins_text:
        model_init_args["system_instruction"] = sys_ins_text
    if formatted_safety_settings:
        model_init_args["safety_settings"] = formatted_safety_settings
    
    try:
        model = _gemini_client.get_generative_model(**model_init_args)
        print(f"情報: GenerativeModel '{selected_model}' initialized with sys_ins and safety_settings.")
    except Exception as e_model_init:
        print(f"エラー: GenerativeModel '{selected_model}' の初期化中にエラー: {e_model_init}")
        return f"エラー: モデル '{selected_model}' の初期化に失敗しました: {e_model_init}"

    # active_generation_config (for tools) - this was part of the original block, ensure it's still prepared
    active_generation_config = None
    # generation_config_args was defined above, now it only needs to consider tools for this specific config
    gen_config_for_tools_only_args = {}
    if tools_list: # tools_list is prepared earlier in the function
        gen_config_for_tools_only_args["tools"] = tools_list

    if gen_config_for_tools_only_args: # only create if there are tools
        try:
            active_generation_config = GenerateContentConfig(**gen_config_for_tools_only_args)
        except Exception as e:
            print(f"警告: GenerateContentConfig (for tools) の作成中にエラー: {e}.")
            # Not creating a fallback GenerateContentConfig() here as it's specifically for tools.

    # Prepare final_api_contents (history + current turn parts, NO system instruction)
    # api_contents is already prepared from history.
    # current_turn_parts is also prepared.
    # The logic that appended current_turn_parts to api_contents is from the previous state.
    # Let's ensure final_api_contents_for_generate is what we send.
    final_api_contents_for_generate = api_contents # api_contents should have history + current turn by this point based on previous logic.
                                                 # The previous step: `final_api_contents.extend(api_contents)` where api_contents
                                                 # was `history + current_turn_parts`.
                                                 # And then `sys_ins_text` was prepended to `final_api_contents`.
                                                 # Now, `sys_ins_text` is gone from here.
                                                 # `api_contents` itself should be the complete list of user/model messages.

    if not final_api_contents_for_generate: # Check if it's empty
        return "エラー: 最終的な送信コンテンツが空です。"

    print(f"Gemini (google-genai) model.generate_content へ送信開始... モデル: {selected_model}, contents長: {len(final_api_contents_for_generate)}")
    try:
        # Construct arguments for generate_content
        gen_content_args = {
            "contents": final_api_contents_for_generate,
        }
        if active_generation_config: # This contains tools
            gen_content_args["generation_config"] = active_generation_config
        
        response = model.generate_content(**gen_content_args)

    except google.api_core.exceptions.ResourceExhausted as e: # Assuming this exception type is still relevant
        return f"エラー: Gemini API リソース枯渇 (google-genai): {e}"
    # Add specific exception handling for google.genai.types.BlockedPromptException etc. if those are confirmed and imported
    except Exception as e:
        # Log the full traceback for unexpected errors
        import traceback
        print(f"Gemini API (google-genai) 呼び出し中に予期しないエラー: {traceback.format_exc()}")
        return f"エラー: Gemini APIとの通信中に予期しないエラー (google-genai): {e}"
    
    final_text_response = None
    try:
        if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
            text_parts = [part.text for part in response.candidates[0].content.parts if hasattr(part, 'text')]
            final_text_response = "".join(text_parts)
        
        # Check for blocking if no text found or if prompt_feedback exists
        if final_text_response is None or not final_text_response.strip():
            if hasattr(response, 'prompt_feedback') and response.prompt_feedback and response.prompt_feedback.block_reason:
                return f"応答取得エラー: プロンプトがブロックされました。理由: {response.prompt_feedback.block_reason}"
            if final_text_response is None : # Still None, means no valid parts found
                 final_text_response = "応答にテキストコンテンツが見つかりませんでした。"

    except Exception as e:
        print(f"応答テキストの処理中にエラー: {e}")
        # Try to get block_reason even if parts processing failed
        if hasattr(response, 'prompt_feedback') and response.prompt_feedback and response.prompt_feedback.block_reason:
            return f"応答取得エラー ({e}) ブロック理由: {response.prompt_feedback.block_reason}"
        return f"応答取得エラー ({e}) ブロック理由は不明"
    
    return final_text_response.strip() if final_text_response is not None else "応答生成失敗 (空の応答)"

def send_alarm_to_gemini(character_name, theme, flash_prompt_template, alarm_model_name, api_key_name, log_file_path, alarm_api_history_turns):
    print(f"--- アラーム応答生成開始 (google-genai SDK) --- キャラ: {character_name}, テーマ: '{theme}'") 
    if _gemini_client is None:
        print("警告: _gemini_client is None in send_alarm_to_gemini. Attempting to configure with provided api_key_name.")
        config_success, config_msg = configure_google_api(api_key_name) 
        if not config_success:
            return f"【アラームエラー】APIキー設定失敗: {config_msg}"
        if _gemini_client is None: 
            return "【アラームエラー】Geminiクライアントが初期化されていません。"

    sys_ins_text = ""
    if flash_prompt_template:
        sys_ins_text = flash_prompt_template.replace("[キャラクター名]", character_name).replace("[テーマ内容]", theme)
        sys_ins_text += "\n\n**重要:** あなたの思考過程、応答の候補、メタテキスト（例: ---）などは一切出力せず、ユーザーに送る最終的な短いメッセージ本文のみを生成してください。"
    elif theme:
        sys_ins_text = f"""あなたはキャラクター「{character_name}」です。
以下のテーマについて、ユーザーに送る短いメッセージを生成してください。
過去の会話履歴があれば参考にし、自然な応答を心がけてください。

テーマ: {theme}

重要: あなたの思考過程、応答の候補リスト、自己対話、マーカー（例: `---`）などは一切含めず、ユーザーに送る最終的な短いメッセージ本文のみを出力してください。"""

    _, _, _, memory_json_path = get_character_files_paths(character_name) 
    if memory_json_path and os.path.exists(memory_json_path):
        try:
            with open(memory_json_path, "r", encoding="utf-8") as f: mem = json.load(f)
            m_api = {k: v for k, v in {
                "user_profile": mem.get("user_profile"),
                "self_identity": mem.get("self_identity"),
                "shared_language": mem.get("shared_language"),
                "current_context": mem.get("current_context"),
                "memory_summary": mem.get("memory_summary", [])[-config_manager.MEMORY_SUMMARY_LIMIT_FOR_API:]
            }.items() if v}
            if m_api: sys_ins_text += f"\n\n---\n## 参考記憶:\n{json.dumps(m_api, indent=2, ensure_ascii=False)}\n---"
        except Exception as e: print(f"記憶ファイル '{memory_json_path}' 読込/処理エラー (アラーム): {e}")

    # Prepare formatted_safety_settings
    formatted_safety_settings = []
    if config_manager.SAFETY_CONFIG:
        try:
            for category_enum, threshold_enum in config_manager.SAFETY_CONFIG.items(): # Renamed for clarity if they are enums
                formatted_safety_settings.append(SafetySetting(category=category_enum, threshold=threshold_enum))
            print(f"デバッグ (alarm): formatted_safety_settings: {formatted_safety_settings}")
        except NameError as ne: # Should not happen if imports are correct
            print(f"警告 (alarm): SafetySetting, HarmCategory, or HarmBlockThreshold types not found. Error: {ne}")
        except Exception as e_ss:
            print(f"警告 (alarm): Error processing safety settings: {e_ss}.")
    if not formatted_safety_settings:
        formatted_safety_settings = None

    # Model Initialization
    model_init_args = {"model_name": alarm_model_name}
    if sys_ins_text:
        model_init_args["system_instruction"] = sys_ins_text
    if formatted_safety_settings:
        model_init_args["safety_settings"] = formatted_safety_settings
    
    try:
        model = _gemini_client.get_generative_model(**model_init_args)
        print(f"情報 (alarm): GenerativeModel '{alarm_model_name}' initialized with sys_ins and safety_settings.")
    except Exception as e_model_init:
        print(f"エラー (alarm): GenerativeModel '{alarm_model_name}' の初期化中にエラー: {e_model_init}")
        return f"【アラームエラー】モデル '{alarm_model_name}' の初期化に失敗: {e_model_init}"

    # Prepare api_contents (history and placeholder - NO system instruction here)
    api_contents = [] # This variable will now hold only the history/placeholder for generate_content
    if alarm_api_history_turns > 0:
        msgs = load_chat_log(log_file_path, character_name)
        limit_msgs = alarm_api_history_turns * 2
        if len(msgs) > limit_msgs: msgs = msgs[-limit_msgs:]
        
        th_pat = re.compile(r"【Thoughts】.*?【/Thoughts】\s*", re.DOTALL | re.IGNORECASE)
        img_pat = re.compile(r"\[画像添付:[^\]]+\]")
        alrm_pat = re.compile(r"（システムアラーム：.*?）")
        
        for m in msgs:
            sdk_role = "user" if m.get("role") == "user" else "model"
            content_text = m.get("content", "")
            if not content_text: continue
            
            processed_text = content_text
            if sdk_role == "model": processed_text = th_pat.sub("", processed_text).strip()
            processed_text = img_pat.sub("", processed_text).strip() # Remove image tags for both roles
            processed_text = alrm_pat.sub("", processed_text).strip() # Remove alarm tags for both roles

            if processed_text:
                api_contents.append(Content(role=sdk_role, parts=[Part(text=processed_text)]))
        print(f"情報: アラーム応答生成のために、直近 {alarm_api_history_turns} 往復 ({len(api_contents)} 件) の整形済み履歴を参照します。")
    else:
        print("情報: アラーム応答生成では履歴を参照しません。")

    # If history is empty, or last message was model's, add a placeholder user message.
    if not api_contents or (api_contents and api_contents[-1].role == "model"):
        placeholder_text = "（時間になりました。アラームメッセージをお願いします。）" if not api_contents else "（続けて）"
        api_contents.append(Content(role="user", parts=[Part(text=placeholder_text)]))
        print(f"情報: API呼び出し用に形式的なユーザー入力 ('{placeholder_text}') を追加しました。")

    if not api_contents: # Should not happen due to above logic
         return "【アラームエラー】内部エラー: 送信コンテンツ空"

    generation_config_args = {}
    if config_manager.SAFETY_CONFIG:
        try:
            safety_settings_list = []
            for category, threshold in config_manager.SAFETY_CONFIG.items():
                safety_settings_list.append(SafetySetting(category=category, threshold=threshold))
            generation_config_args["safety_settings"] = safety_settings_list
            print(f"デバッグ (alarm): safety_settings_list: {safety_settings_list}") 
        except NameError as ne:
            print(f"警告 (alarm): SafetySetting, HarmCategory, or HarmBlockThreshold types not found. Safety settings may not be correctly applied. Error: {ne}")
            try:
                safety_settings_list_of_dicts = []
                for category, threshold in config_manager.SAFETY_CONFIG.items():
                    safety_settings_list_of_dicts.append({"category": category, "threshold": threshold})
                generation_config_args["safety_settings"] = safety_settings_list_of_dicts
                print(f"デバッグ (alarm): safety_settings_list_of_dicts (fallback): {safety_settings_list_of_dicts}")
            except Exception as e_dict_conv_alarm:
                print(f"警告 (alarm): Fallback conversion of safety_settings to list of dicts failed: {e_dict_conv_alarm}. Passing raw dict.")
                generation_config_args["safety_settings"] = config_manager.SAFETY_CONFIG
        except Exception as e_ss_alarm:
            print(f"警告 (alarm): Error processing safety settings: {e_ss_alarm}. Safety settings may not be applied.")
            generation_config_args["safety_settings"] = config_manager.SAFETY_CONFIG
    
    active_generation_config = None
    if generation_config_args:
        try:
            active_generation_config = GenerateContentConfig(**generation_config_args)
        except Exception as e:
            print(f"警告: アラーム用 GenerateContentConfig の作成中にエラー: {e}.")
            # Proceed without generation_config if it fails

    print(f"アラーム用モデル ({alarm_model_name}, google-genai) へ送信開始... 送信contents件数: {len(api_contents)}, sys_ins提供: {True if sys_ins_text else False}") # Original api_contents length before prepending sys_ins
    try:
        final_api_contents_alarm = []
        if sys_ins_text:
            print(f"デバッグ (alarm): Prepending system instruction as 'user' role content part.")
            final_api_contents_alarm.append(Content(role="user", parts=[Part(text=sys_ins_text)]))
            # Optionally add model ack here too if desired for alarms
            # final_api_contents_alarm.append(Content(role="model", parts=[Part(text="了解しました。")]))

        final_api_contents_alarm.extend(api_contents) # api_contents is from history or placeholder

        if not final_api_contents_alarm: 
             return "【アラームエラー】内部エラー: 送信コンテンツ空"

        gen_content_args = {
            "model": alarm_model_name, 
            "contents": final_api_contents_alarm
        }
        # if sys_ins_text: # REMOVE THIS (already handled by prepending)
        #    gen_content_args["system_instruction"] = sys_ins_text
        if active_generation_config:
            gen_content_args["generation_config"] = active_generation_config

        response = _gemini_client.models.generate_content(**gen_content_args)

    # Assuming google.genai.types.BlockedPromptException etc. exist
    # For now, using general catch for specific exceptions related to content blocking
    except Exception as e: # Broaden this if specific exceptions are confirmed
        # Check if it's a known type of blocking exception, even if not specifically imported by name
        if "BlockedPromptException" in str(type(e)) or "StopCandidateException" in str(type(e)):
             print(f"アラームAPI呼び出しでブロックまたは停止例外: {e}")
             return f"【アラームエラー】プロンプトブロックまたは候補生成停止"

        print(f"アラーム用モデル ({alarm_model_name}, google-genai) との通信中にエラーが発生しました: {traceback.format_exc()}")
        return f"【アラームエラー】API通信失敗: {e}"
    
    final_text_response = None
    try:
        if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
            text_parts = [part.text for part in response.candidates[0].content.parts if hasattr(part, 'text')]
            final_text_response = "".join(text_parts)

        if final_text_response is None or not final_text_response.strip():
            if hasattr(response, 'prompt_feedback') and response.prompt_feedback and response.prompt_feedback.block_reason:
                block_reason_str = str(response.prompt_feedback.block_reason)
                return f"【アラームエラー】応答取得失敗。ブロック理由: {block_reason_str}"
            if final_text_response is None: # Still None
                 final_text_response = "【アラームエラー】モデルから空の応答または非テキスト応答が返されました。"
        
        # Clean up markdown-like formatting if not code block
        if final_text_response.strip().startswith("```"):
            return final_text_response.strip()
        else:
            return re.sub(r"^\s*([-*_#=`>]+|\n)+\s*", "", final_text_response.strip())

    except Exception as e:
        print(f"アラーム応答テキストの処理中にエラー: {e}")
        if hasattr(response, 'prompt_feedback') and response.prompt_feedback and response.prompt_feedback.block_reason:
            return f"【アラームエラー】応答処理エラー ({e}) ブロック理由: {response.prompt_feedback.block_reason}"
        return f"【アラームエラー】応答処理エラー ({e}) ブロック理由は不明"