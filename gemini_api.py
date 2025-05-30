# -*- coding: utf-8 -*-
import google.genai as genai
from google.genai import types
from google.genai.types import Tool, GoogleSearch, GenerateContentConfig, Content, Part
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
        print(f"Google GenAI Client for API key '{api_key_name}' initialized successfully.") # New success message
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
        elif sdk_role == "model" and not send_thoughts_to_api:
            processed_text = th_pat.sub("", processed_text).strip()
        
        if processed_text:
            api_contents.append(Content(role=sdk_role, parts=[Part(text=processed_text)]))

    current_turn_parts = []
    if user_prompt:
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
                    current_turn_parts.append(Part(inline_data={"mime_type": mime_type, "data": encoded_data}))
                    print(f"情報: ファイル '{os.path.basename(file_path)}' ({mime_type}) をAPIリクエストに追加しました。")
                except Exception as e:
                    print(f"警告: ファイル '{os.path.basename(file_path)}' の処理中にエラー: {e}. スキップします。")
            else:
                print(f"警告: 指定されたファイルパス '{file_path}' が見つかりません。スキップします。")

    if not current_turn_parts:
        if user_prompt is not None or uploaded_file_parts:
             return "エラー: 送信する有効なコンテンツがありません (テキストが空か、ファイル処理に失敗しました)。"
        if not api_contents:
            return "エラー: 送信するメッセージ履歴も現在の入力もありません。"

    if current_turn_parts:
        api_contents.append(Content(role="user", parts=current_turn_parts))
    
    if not api_contents:
        return "エラー: 最終的な送信コンテンツが空です。"

    tools_list = []
    if "2.5-pro" in selected_model.lower() or "2.5-flash" in selected_model.lower():
        try:
            google_search_tool = Tool(google_search=GoogleSearch())
            tools_list.append(google_search_tool)
            print("情報: Google検索グラウンディング (google-genai SDK) がセットアップされました。")
        except Exception as e:
            print(f"警告: GoogleSearch Toolのセットアップ中にエラー (google-genai SDK): {e}")
    
    generation_config_args = {}
    if tools_list:
        generation_config_args["tools"] = tools_list
    
    if config_manager.SAFETY_CONFIG:
        generation_config_args["safety_settings"] = config_manager.SAFETY_CONFIG
    
    active_generation_config = None
    if generation_config_args:
        try:
            active_generation_config = GenerateContentConfig(**generation_config_args)
        except Exception as e:
            print(f"警告: GenerateContentConfig の作成中にエラー: {e}. 引数なしで試行します。")
            try:
                active_generation_config = GenerateContentConfig()
            except Exception as e_cfg_fallback:
                 print(f"警告: フォールバック GenerateContentConfig の作成中にもエラー: {e_cfg_fallback}.")

    print(f"Gemini (google-genai) へ送信開始... モデル: {selected_model}, contents長: {len(api_contents)}, sys_ins提供: {True if sys_ins_text else False}")
    try:
        gen_content_args = {
            "model": selected_model,
            "contents": api_contents
        }
        if sys_ins_text:
            gen_content_args["system_instruction"] = sys_ins_text
        if active_generation_config:
            gen_content_args["generation_config"] = active_generation_config
        
        response = _gemini_client.models.generate_content(**gen_content_args)

    except google.api_core.exceptions.ResourceExhausted as e:
        return f"エラー: Gemini API リソース枯渇 (google-genai): {e}"
    except Exception as e:
        import traceback
        print(f"Gemini API (google-genai) 呼び出し中に予期しないエラー: {traceback.format_exc()}")
        return f"エラー: Gemini APIとの通信中に予期しないエラー (google-genai): {e}"
    
    final_text_response = None
    try:
        if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
            text_parts = [part.text for part in response.candidates[0].content.parts if hasattr(part, 'text')]
            final_text_response = "".join(text_parts)
        
        if final_text_response is None or not final_text_response.strip():
            if hasattr(response, 'prompt_feedback') and response.prompt_feedback and response.prompt_feedback.block_reason:
                return f"応答取得エラー: プロンプトがブロックされました。理由: {response.prompt_feedback.block_reason}"
            if final_text_response is None : 
                 final_text_response = "応答にテキストコンテンツが見つかりませんでした。"

    except Exception as e:
        print(f"応答テキストの処理中にエラー: {e}")
        if hasattr(response, 'prompt_feedback') and response.prompt_feedback and response.prompt_feedback.block_reason:
            return f"応答取得エラー ({e}) ブロック理由: {response.prompt_feedback.block_reason}"
        return f"応答取得エラー ({e}) ブロック理由は不明"
    
    return final_text_response.strip() if final_text_response is not None else "応答生成失敗 (空の応答)"

def send_alarm_to_gemini(character_name, theme, flash_prompt_template, alarm_model_name, api_key_name, log_file_path, alarm_api_history_turns):
    print(f"--- アラーム応答生成開始 (google-genai SDK) --- キャラ: {character_name}, テーマ: '{theme}'") # Updated log
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
        # print("情報: アラーム応答にカスタムプロンプトを使用します。") # Redundant due to main log
    elif theme:
        sys_ins_text = f"""あなたはキャラクター「{character_name}」です。
以下のテーマについて、ユーザーに送る短いメッセージを生成してください。
過去の会話履歴があれば参考にし、自然な応答を心がけてください。

テーマ: {theme}

重要: あなたの思考過程、応答の候補リスト、自己対話、マーカー（例: `---`）などは一切含めず、ユーザーに送る最終的な短いメッセージ本文のみを出力してください。"""
        # print("情報: アラーム応答にデフォルトプロンプト（テーマ使用）を使用します。") # Redundant

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
            # print("情報: memory.json の内容をシステムプロンプトに追加しました。") # Redundant
        except Exception as e: print(f"記憶ファイル '{memory_json_path}' 読込/処理エラー (アラーム): {e}")
    # else:
        # print("情報: memory.json が見つからないため、記憶データは追加されません。") # Can be noisy

    api_contents = []
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
            processed_text = img_pat.sub("", processed_text).strip() 
            processed_text = alrm_pat.sub("", processed_text).strip()

            if processed_text:
                api_contents.append(Content(role=sdk_role, parts=[Part(text=processed_text)]))
        print(f"情報: アラーム応答生成のために、直近 {alarm_api_history_turns} 往復 ({len(api_contents)} 件) の整形済み履歴を参照します。")
    else:
        print("情報: アラーム応答生成では履歴を参照しません。")

    if not api_contents or (api_contents and api_contents[-1].role == "model"):
        placeholder_text = "（時間になりました。アラームメッセージをお願いします。）" if not api_contents else "（続けて）"
        api_contents.append(Content(role="user", parts=[Part(text=placeholder_text)]))
        print(f"情報: API呼び出し用に形式的なユーザー入力 ('{placeholder_text}') を追加しました。")

    if not api_contents: 
         return "【アラームエラー】内部エラー: 送信コンテンツ空"

    generation_config_args = {}
    if config_manager.SAFETY_CONFIG:
        generation_config_args["safety_settings"] = config_manager.SAFETY_CONFIG
    
    active_generation_config = None
    if generation_config_args:
        try:
            active_generation_config = GenerateContentConfig(**generation_config_args)
        except Exception as e:
            print(f"警告: アラーム用 GenerateContentConfig の作成中にエラー: {e}.")

    print(f"アラーム用モデル ({alarm_model_name}, google-genai) へ送信開始... 送信contents件数: {len(api_contents)}, sys_ins提供: {True if sys_ins_text else False}")
    try:
        gen_content_args = {
            "model": alarm_model_name, 
            "contents": api_contents
        }
        if sys_ins_text:
            gen_content_args["system_instruction"] = sys_ins_text
        if active_generation_config:
            gen_content_args["generation_config"] = active_generation_config

        response = _gemini_client.models.generate_content(**gen_content_args)

    except Exception as e: 
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
            if final_text_response is None: 
                 final_text_response = "【アラームエラー】モデルから空の応答または非テキスト応答が返されました。"
        
        if final_text_response.strip().startswith("```"):
            return final_text_response.strip()
        else:
            return re.sub(r"^\s*([-*_#=`>]+|\n)+\s*", "", final_text_response.strip())

    except Exception as e:
        print(f"アラーム応答テキストの処理中にエラー: {e}")
        if hasattr(response, 'prompt_feedback') and response.prompt_feedback and response.prompt_feedback.block_reason:
            return f"【アラームエラー】応答処理エラー ({e}) ブロック理由: {response.prompt_feedback.block_reason}"
        return f"【アラームエラー】応答処理エラー ({e}) ブロック理由は不明"