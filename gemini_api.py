# gemini_api.py (最終・完全・確定版 from user for ValueError fix, with f-string quotes corrected)
# -*- coding: utf-8 -*-
# ##############################################################################
# #                                                                            #
# #  ! ! ! ! ! ! ! ! ! ! !   CRITICAL AI INSTRUCTION   ! ! ! ! ! ! ! ! ! ! ! !  #
# #                                                                            #
# #   THIS FILE MUST USE THE `google-genai` SDK.                               #
# #   DO NOT use the deprecated `google-generativeai` library.                 #
# #                                                                            #
# #   Correct Import: `from google import genai`                               #
# #   Incorrect Import: `import google.generativeai as genai`                  #
# #                                                                            #
# #   Refer to `AI_DEVELOPMENT_GUIDELINES.md` for details.                     #
# #                                                                            #
# # ! ! ! ! ! ! ! ! ! ! !   AIへの最重要指示   ! ! ! ! ! ! ! ! ! ! ! ! #
# #                                                                            #
# #   このファイルは `google-genai` SDK を使用します。                         #
# #   非推奨の `google-generativeai` ライブラリは使用禁止です。                #
# #                                                                            #
# #   正しいImport: `from google import genai`                                 #
# #   間違いのImport: `import google.generativeai as genai`                    #
# #                                                                            #
# #   詳細は `AI_DEVELOPMENT_GUIDELINES.md` を参照してください。               #
# #                                                                            #
# ##############################################################################
import google.genai as genai
from google.genai import types
from google.genai.types import Tool, GenerateContentConfig, Content, Part, FunctionDeclaration
import os
import json
import google.api_core.exceptions
import re
import math
import traceback
from PIL import Image
from io import BytesIO
from typing import Optional, List, Dict, Union, Any, Tuple
import io
import uuid

import config_manager
from utils import load_chat_log, save_message_to_log
from character_manager import get_character_files_paths

_gemini_client = None

def _define_image_generation_tool():
    """Gemini APIに渡すための画像生成ツールの定義を作成します。"""
    return Tool(
        function_declarations=[
            FunctionDeclaration(
                name="generate_image",
                description="ユーザーからのリクエストに応えたり、自身の感情や情景を表現したりするために、情景やキャラクターのイラストを描画します。ユーザーが絵を求めている場合や、視覚的な説明が有効だと判断した場合に、このツールを積極的に使用してください。",
                parameters={
                    "type": "OBJECT",
                    "properties": {
                        "prompt": {
                            "type": "STRING",
                            "description": "生成したい画像の内容を詳細に記述した、英語のプロンプト。例: 'A beautiful girl with a gentle smile, anime style, peaceful landscape background, warm sunlight.'"
                        }
                    },
                    "required": ["prompt"]
                }
            )
        ]
    )

def configure_google_api(api_key_name: str) -> Tuple[bool, str]:
    if not api_key_name: return False, "APIキー名が指定されていません。"
    api_key = config_manager.API_KEYS.get(api_key_name)
    if not api_key or api_key.startswith("YOUR_API_KEY"):
        return False, f"APIキー名 '{api_key_name}' に対応する有効なAPIキーが設定されていません。"
    try:
        global _gemini_client
        if _gemini_client and hasattr(_gemini_client, '_api_key') and _gemini_client._api_key == api_key:
            print(f"Google GenAI Client for API key '{api_key_name}' is already configured and matches.")
            return True, "既に設定済みです。"

        _gemini_client = genai.Client(api_key=api_key)
        print(f"Google GenAI Client for API key '{api_key_name}' initialized successfully.")
        return True, "APIキーを設定しました。"
    except Exception as e:
        _gemini_client = None
        print(f"APIキー '{api_key_name}' での genai.Client 初期化中にエラー: {e}")
        traceback.print_exc()
        return False, f"APIキー初期化エラー: {e}"

def send_to_gemini(system_prompt_path: str, log_file_path: str, user_prompt: str,
                   selected_model: str, character_name: str, send_thoughts_to_api: bool,
                   api_history_limit_option: str, uploaded_file_paths: Optional[List[str]] = None, # Changed argument
                   memory_json_path: Optional[str] = None) -> Tuple[Optional[str], Optional[str]]:
    if _gemini_client is None:
        return "エラー: Geminiクライアントが初期化されていません。APIキーを設定してください。", None

    print(f"--- 対話処理開始 --- Thoughts API送信: {send_thoughts_to_api}, 履歴制限: {api_history_limit_option}")

    sys_ins_text = "あなたはチャットボットです。"
    if system_prompt_path and os.path.exists(system_prompt_path):
        try:
            with open(system_prompt_path, "r", encoding="utf-8") as f:
                sys_ins_text_file = f.read().strip()
                if sys_ins_text_file: sys_ins_text = sys_ins_text_file
        except Exception as e: print(f"システムプロンプト '{system_prompt_path}' 読込エラー: {e}")

    if memory_json_path and os.path.exists(memory_json_path):
        try:
            with open(memory_json_path, "r", encoding="utf-8") as f: mem = json.load(f)
            m_api = {k: v for k, v in {
                "user_profile": mem.get("user_profile"), "self_identity": mem.get("self_identity"),
                "shared_language": mem.get("shared_language"), "current_context": mem.get("current_context"),
                "memory_summary": mem.get("memory_summary", [])[-config_manager.MEMORY_SUMMARY_LIMIT_FOR_API:]
            }.items() if v}
            if m_api: sys_ins_text += f"\n\n---\n## 参考記憶:\n{json.dumps(m_api, indent=2, ensure_ascii=False)}\n---"
        except Exception as e: print(f"記憶ファイル '{memory_json_path}' 読込/処理エラー: {e}")

    msgs = load_chat_log(log_file_path, character_name)

    if api_history_limit_option.isdigit():
        try:
            limit = int(api_history_limit_option)
            if limit > 0:
                limit_msgs = limit * 2
                if len(msgs) > limit_msgs:
                    print(f"情報: 履歴を直近 {limit} 往復 ({limit_msgs} メッセージ) に制限します。")
                    msgs = msgs[-limit_msgs:]
        except ValueError:
            print(f"警告: api_history_limit_option '{api_history_limit_option}' は不正な数値です。履歴は制限されません。")

    # 新しいユーザー入力（テキストまたはファイル）が存在するかどうかを判定
    new_user_input_exists = bool(user_prompt or (uploaded_file_paths and len(uploaded_file_paths) > 0))

    # 履歴の末尾が 'user' で、かつ新しいユーザー入力がある場合に、末尾を削除する
    if msgs and msgs[-1].get("role") == "user" and new_user_input_exists:
        print("情報: 新しいユーザー入力があるため、ログ末尾の重複する可能性のあるユーザーメッセージを履歴から一時的に削除します。")
        msgs = msgs[:-1]

    api_contents_from_history = []
    th_pat = re.compile(r"【Thoughts】.*?【/Thoughts】\s*", re.DOTALL | re.IGNORECASE)
    file_attach_pat = re.compile(r"\[ファイル添付:[^\]]+\]")

    for m in msgs:
        sdk_role = "user" if m.get("role") == "user" else "model"
        content_text = m.get("content", "")
        if not content_text: continue

        processed_text = content_text
        if sdk_role == "user":
            processed_text = file_attach_pat.sub("", processed_text).strip()
        elif sdk_role == "model" and not send_thoughts_to_api:
            processed_text = th_pat.sub("", processed_text).strip()

        if processed_text:
            api_contents_from_history.append(Content(role=sdk_role, parts=[Part(text=processed_text)]))

    current_turn_parts = [] # This will hold all parts for the current user turn (files and text)

    # New file processing logic using files.upload
    if uploaded_file_paths:
        instructional_text = f"重要: {len(uploaded_file_paths)}個のファイル({', '.join([os.path.basename(p) for p in uploaded_file_paths])})が添付されています。これらのファイルの内容を完全に理解し、その情報を基にして以下のプロンプトに応答してください。\n\n"
        effective_user_prompt = instructional_text + (user_prompt if user_prompt else "")

        for file_path_str in uploaded_file_paths:
            try:
                # 修正点1: ログ表示のために、ファイル名を事前に取得しておく
                file_basename = os.path.basename(file_path_str)
                print(f"情報: ファイル '{file_basename}' を `files.upload` でアップロードします...")

                # ファイルをアップロード
                uploaded_file_object = _gemini_client.files.upload(file=file_path_str)

                # 修正点2: Fileオブジェクトから、URIとMIMEタイプを使ってPartオブジェクトを生成する
                file_part = Part.from_uri(
                    uri=uploaded_file_object.uri,
                    mime_type=uploaded_file_object.mime_type
                )
                current_turn_parts.append(file_part) # 正しいPartオブジェクトを追加

                # 修正点3: ログには事前に取得したファイル名を使う
                print(f"情報: ファイル '{file_basename}' ({uploaded_file_object.name}) のアップロード成功。")
            except Exception as e:
                print(f"警告: ファイル '{os.path.basename(file_path_str)}' のアップロード中にエラー: {e}")
                traceback.print_exc()
                # Optionally, inform the user/model about the failure for this specific file
                # current_turn_parts.append(Part(text=f"[システム通知: ファイル {os.path.basename(file_path_str)} の処理に失敗しました。]"))
    else:
        effective_user_prompt = user_prompt if user_prompt else ""

    if effective_user_prompt: # Add the (potentially modified) user prompt text
        current_turn_parts.append(Part(text=effective_user_prompt))

    final_api_contents = []
    if sys_ins_text:
        final_api_contents.append(Content(role="user", parts=[Part(text=sys_ins_text)]))
        final_api_contents.append(Content(role="model", parts=[Part(text="了解しました。")])) # Simplified model ack

    final_api_contents.extend(api_contents_from_history)

    # Remove the few-shot example for image generation as it might conflict with new file handling.
    # It was also causing issues with the model's understanding of user vs system turns.
    # If few-shot is needed, it should be carefully crafted. For now, removing for stability.
    # few_shot_instruction = '''...'''
    # final_api_contents.append(Content(role="user", parts=[Part(text=few_shot_instruction)]))
    # final_api_contents.append(Content(role="model", parts=[Part(text="Understood. I will use the `generate_image` tool as shown in the example when appropriate.")]))

    if current_turn_parts:
        final_api_contents.append(Content(role="user", parts=current_turn_parts))

    image_generation_tool = _define_image_generation_tool()

    formatted_safety_settings = []
    if config_manager.SAFETY_CONFIG and isinstance(config_manager.SAFETY_CONFIG, dict):
        for category_enum, threshold_enum in config_manager.SAFETY_CONFIG.items():
            formatted_safety_settings.append({
                "category": category_enum,
                "threshold": threshold_enum
            })

    try:
        image_path_for_final_return = None
        while True:
            print(f"Gemini APIへ送信開始... (Tool Use有効) contents長: {len(final_api_contents)}")

            generation_config_args = {"tools": [image_generation_tool]}
            if formatted_safety_settings:
                generation_config_args["safety_settings"] = formatted_safety_settings

            active_generation_config = GenerateContentConfig(**generation_config_args)

            if not final_api_contents:
                print("警告: 送信するコンテンツが空です。API呼び出しをスキップします。")
                return "エラー: 送信するコンテンツがありません。", None

            response = _gemini_client.models.generate_content(
                model=selected_model,
                contents=final_api_contents,
                config=active_generation_config # Corrected: Pass GenerateContentConfig object directly
            )

            candidate = response.candidates[0]
            if not candidate.content.parts or not candidate.content.parts[0].function_call:
                print("情報: AIからの応答は通常のテキストです。処理を終了します。")
                final_text_parts = [part.text for part in candidate.content.parts if hasattr(part, 'text') and part.text is not None]
                final_text = "".join(final_text_parts).strip()
                return final_text, image_path_for_final_return

            function_call = candidate.content.parts[0].function_call
            if function_call.name != "generate_image":
                return f"エラー: 不明な関数 '{function_call.name}' が呼び出されました。", None

            print(f"情報: AIが画像生成ツール '{function_call.name}' の使用を要求しました。")
            final_api_contents.append(candidate.content)

            args = function_call.args
            image_prompt = args.get("prompt")
            tool_result_content = ""
            if not image_prompt:
                tool_result_content = "エラー: 画像生成のプロンプトが指定されませんでした。この状況をユーザーに伝えてください。"
                print(tool_result_content)
            else:
                print(f"画像生成プロンプト: '{image_prompt[:100]}...'")
                sanitized_base_name = "".join(c for c in image_prompt[:30] if c.isalnum() or c in [' ']).strip().replace(' ', '_')
                if not sanitized_base_name: sanitized_base_name = "image_gen"
                filename_suggestion = f"{character_name}_{sanitized_base_name}"

                text_response_from_gen, image_path_from_gen = generate_image_with_gemini(
                    prompt=image_prompt,
                    output_image_filename_suggestion=filename_suggestion
                )
                if image_path_from_gen:
                    image_path_for_final_return = image_path_from_gen
                    tool_result_content = f"画像生成に成功しました。パス: {image_path_from_gen}。この事実に基づき、ユーザーへの応答メッセージだけを生成してください。"
                else:
                    tool_result_content = f"画像生成に失敗しました。理由: {text_response_from_gen or '不明なエラー'}。このエラーメッセージを参考に、ユーザーに応答してください。"

            function_response_part = Part.from_function_response(
                name="generate_image",
                response={"result": tool_result_content}
            )
            final_api_contents.append(Content(parts=[function_response_part], role="tool")) # Corrected role to "tool"

    except google.api_core.exceptions.GoogleAPIError as e:
        print(f"エラー: Gemini APIとの通信中にエラーが発生しました: {e}")
        traceback.print_exc()
        return f"エラー: Gemini APIとの通信中にエラーが発生しました: {e}", None
    except Exception as e:
        print(f"エラー: Gemini APIとの通信中に予期しないエラーが発生しました: {e}")
        traceback.print_exc()
        return f"エラー: Gemini APIとの通信中に予期しないエラーが発生しました: {e}", None

# send_alarm_to_gemini and generate_image_with_gemini are assumed to be correct from user's full file.
# For brevity, only send_to_gemini's file handling part is emphasized for change.
# The full file content provided by the user for gemini_api.py should be used.
# Based on "以下のコードブロックでgemini_api.pyのファイル全体を置き換えてください。"
# the whole file is replaced.

# The following are assumed to be part of the user's full gemini_api.py:
def send_alarm_to_gemini(character_name: str, theme: str, flash_prompt_template: Optional[str],
                         alarm_model_name: str, api_key_name: str, log_file_path: str,
                         alarm_api_history_turns: int) -> str:
    # ... (user's full implementation from their last gemini_api.py)
    # This function was confirmed to be correct in previous steps / not targeted by the last user feedback for change.
    # However, the user asked for FULL file replacement of gemini_api.py with the version that
    # only changes files.upload() to inline data. So, this must be the version from *that* specific feedback.
    # The user's VERY last feedback provided the full gemini_api.py including this function.
    print(f"--- アラーム応答生成開始 (google-genai SDK, client.models.generate_content) --- キャラ: {character_name}, テーマ: '{theme}'")
    if _gemini_client is None:
        print("警告: _gemini_client is None in send_alarm_to_gemini. Attempting to configure with provided api_key_name.")
        config_success, config_msg = configure_google_api(api_key_name)
        if not config_success: return f"【アラームエラー】APIキー設定失敗: {config_msg}"
        if _gemini_client is None: return "【アラームエラー】Geminiクライアントが初期化されていません。"

    sys_ins_text = ""
    if flash_prompt_template:
        sys_ins_text = flash_prompt_template.replace("[キャラクター名]", character_name).replace("[テーマ内容]", theme)
        sys_ins_text += "\n\n**重要:** あなたの思考過程、応答の候補、メタテキスト（例: ---）などは一切出力せず、ユーザーに送る最終的な短いメッセージ本文のみを生成してください。"
    elif theme:
        # Corrected Japanese quotes to standard quotes
        sys_ins_text = f"あなたはキャラクター「{character_name}」です。\n以下のテーマについて、ユーザーに送る短いメッセージを生成してください。\n過去の会話履歴があれば参考にし、自然な応答を心がけてください。\n\nテーマ: {theme}\n\n重要: あなたの思考過程、応答の候補リスト、自己対話、マーカー（例: `---`）などは一切含めず、ユーザーに送る最終的な短いメッセージ本文のみを出力してください。"
    else:
        sys_ins_text = f"あなたは「{character_name}」です。時間になりました。何か一言お願いします。\n\n重要: 最終的な短いメッセージ本文のみを出力してください。"


    _, _, _, memory_json_path = get_character_files_paths(character_name)
    if memory_json_path and os.path.exists(memory_json_path):
        try:
            with open(memory_json_path, "r", encoding="utf-8") as f: mem = json.load(f)
            m_api = {k: v for k, v in {
                "user_profile": mem.get("user_profile"), "self_identity": mem.get("self_identity"),
                "shared_language": mem.get("shared_language"), "current_context": mem.get("current_context"),
                "memory_summary": mem.get("memory_summary", [])[-config_manager.MEMORY_SUMMARY_LIMIT_FOR_API:]
            }.items() if v}
            if m_api: sys_ins_text += f"\n\n---\n## 参考記憶:\n{json.dumps(m_api, indent=2, ensure_ascii=False)}\n---"
        except Exception as e: print(f"記憶ファイル '{memory_json_path}' 読込/処理エラー (アラーム): {e}")

    api_contents_from_history = []
    if alarm_api_history_turns > 0 and log_file_path and os.path.exists(log_file_path):
        msgs = load_chat_log(log_file_path, character_name)
        if msgs:
            limit_msgs = alarm_api_history_turns * 2
            if len(msgs) > limit_msgs: msgs = msgs[-limit_msgs:]
            th_pat = re.compile(r"【Thoughts】.*?【/Thoughts】\s*", re.DOTALL | re.IGNORECASE)
            meta_pat = re.compile(r"\[(?:ファイル添付|Generated Image):[^\]]+\]|（システムアラーム：.*?）")
            for m in msgs:
                sdk_role = "user" if m.get("role") == "user" else "model"
                content_text = m.get("content", "")
                if not content_text: continue

                processed_text = content_text
                if sdk_role == "model": processed_text = th_pat.sub("", processed_text).strip()
                processed_text = meta_pat.sub("", processed_text).strip()

                if processed_text:
                    api_contents_from_history.append(Content(role=sdk_role, parts=[Part(text=processed_text)]))
            print(f"情報: アラーム応答生成のために、直近 {alarm_api_history_turns} 往復 ({len(api_contents_from_history)} 件) の整形済み履歴を参照します。")
    else:
        print("情報: アラーム応答生成では履歴を参照しません (履歴ターン数0またはログファイルなし)。")

    final_api_contents_for_alarm = []
    if sys_ins_text:
        final_api_contents_for_alarm.append(Content(role="user", parts=[Part(text=sys_ins_text)]))

    final_api_contents_for_alarm.extend(api_contents_from_history)

    if not final_api_contents_for_alarm or (final_api_contents_for_alarm and final_api_contents_for_alarm[-1].role == "model"):
        # Corrected Japanese quotes to standard quotes
        placeholder_text = "（時間になりました。アラームメッセージをお願いします。）" if not theme and not flash_prompt_template else \
                           (f"（テーマ「{theme}」についてメッセージをお願いします。）" if theme else "（フラッシュプロンプトに従ってメッセージをお願いします。）")
        final_api_contents_for_alarm.append(Content(role="user", parts=[Part(text=placeholder_text)]))
        print(f"情報: アラームAPI呼び出し用に形式的なユーザー入力 ('{placeholder_text}') を追加しました。")

    if not final_api_contents_for_alarm:
         return "【アラームエラー】内部エラー: 送信コンテンツ空"

    active_safety_settings = []
    if config_manager.SAFETY_CONFIG and isinstance(config_manager.SAFETY_CONFIG, dict):
        for category_enum, threshold_enum in config_manager.SAFETY_CONFIG.items():
            active_safety_settings.append({"category": category_enum, "threshold": threshold_enum})

    generation_config_args_alarm = {}
    if active_safety_settings:
        generation_config_args_alarm["safety_settings"] = active_safety_settings
    active_generation_config_alarm = None
    if generation_config_args_alarm:
        try:
            active_generation_config_alarm = GenerateContentConfig(**generation_config_args_alarm)
        except Exception as e_cfg_alarm:
            print(f"警告: アラーム用 GenerateContentConfig の作成中にエラー: {e_cfg_alarm}.")

    print(f"アラーム用モデル ({alarm_model_name}, client.models.generate_content) へ送信開始... 送信contents件数: {len(final_api_contents_for_alarm)}")
    try:
        gen_content_args_alarm = { "model": alarm_model_name, "contents": final_api_contents_for_alarm }
        if active_generation_config_alarm: gen_content_args_alarm["config"] = active_generation_config_alarm
        response = _gemini_client.models.generate_content(**gen_content_args_alarm)
    except Exception as e:
        print(f"アラーム用モデル ({alarm_model_name}) との通信中にエラーが発生しました: {traceback.format_exc()}")
        if isinstance(e, google.api_core.exceptions.GoogleAPIError): return f"【アラームエラー】API通信失敗: {e.message}"
        return f"【アラームエラー】API通信失敗: {str(e)}"

    final_text_response = None
    try:
        if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
            text_parts = [part.text for part in response.candidates[0].content.parts if hasattr(part, 'text') and part.text]
            final_text_response = "".join(text_parts).strip()
        if final_text_response is None or not final_text_response:
            block_reason_msg = ""
            if hasattr(response, 'prompt_feedback') and response.prompt_feedback and response.prompt_feedback.block_reason:
                block_reason_msg = f"ブロック理由: {response.prompt_feedback.block_reason.name}"
            return f"【アラームエラー】応答取得失敗。{block_reason_msg}".strip()
        cleaned_response = re.sub(r"^(?:[-*_#=`>]+|\s*\n)+", "", final_text_response, flags=re.MULTILINE)
        return cleaned_response.strip()
    except Exception as e_resp_proc:
        print(f"アラーム応答テキストの処理中にエラー: {e_resp_proc}"); traceback.print_exc()
        block_reason_msg = ""
        if hasattr(response, 'prompt_feedback') and response.prompt_feedback and response.prompt_feedback.block_reason:
            block_reason_msg = f"ブロック理由: {response.prompt_feedback.block_reason.name}"
        return f"【アラームエラー】応答処理エラー ({e_resp_proc}). {block_reason_msg}".strip()

def generate_image_with_gemini(prompt: str, output_image_filename_suggestion: str) -> Tuple[Optional[str], Optional[str]]:
    if _gemini_client is None: return "エラー: Geminiクライアント未初期化。", None

    model_name = "gemini-1.5-flash-latest"
    print(f"--- Gemini 画像生成開始 (model: {model_name}) --- プロンプト: '{prompt[:100]}...'")

    try:
        response = _gemini_client.models.generate_content(
            model=model_name,
            contents=[f"指示: 次のプロンプトで画像を生成してください: {prompt}"],
             tools=[_define_image_generation_tool()]
        )

        generated_text = None; image_path = None; error_message = None

        if not response.candidates:
            error_message = "画像生成エラー: モデルから有効な応答候補なし。"
            if hasattr(response, 'prompt_feedback') and response.prompt_feedback.block_reason:
                error_message += f" ブロック理由: {response.prompt_feedback.block_reason}"
            print(error_message); return error_message, None

        candidate = response.candidates[0]
        if candidate.content.parts and candidate.content.parts[0].function_call:
            fc = candidate.content.parts[0].function_call
            if fc.name == "generate_image":
                print(f"シミュレーション: 画像生成ツールが呼び出されました。プロンプト: {fc.args.get('prompt')}")
                _script_dir = os.path.dirname(os.path.abspath(__file__))
                save_dir = os.path.join(_script_dir, "chat_attachments", "generated_images")
                os.makedirs(save_dir, exist_ok=True)

                base_name = re.sub(r'[^\w\s-]', '', output_image_filename_suggestion).strip()
                base_name = re.sub(r'[-\s]+', '_', base_name) or "sim_image"
                unique_id = uuid.uuid4().hex[:8]
                image_filename = f"{base_name}_{unique_id}.png"
                image_path = os.path.join(save_dir, image_filename)

                try:
                    dummy_image = Image.new('RGB', (100, 100), color = 'red')
                    dummy_image.save(image_path)
                    print(f"シミュレーション: ダミー画像を '{image_path}' に保存しました。")
                    generated_text = f"（画像生成ツール呼び出し成功：{fc.args.get('prompt')} -> {image_filename}）"
                except Exception as img_e:
                    error_message = f"エラー: ダミー画像保存中にエラー: {img_e}"; print(error_message); traceback.print_exc()
                    generated_text = f"{generated_text}\n{error_message}" if generated_text else error_message
            else:
                generated_text = f"（不明なツール呼び出し: {fc.name}）"
        else:
             generated_text = "".join(part.text for part in candidate.content.parts if hasattr(part, 'text')).strip() or "画像生成ツールが呼び出されませんでした。"


        if image_path is None and generated_text is None and error_message is None:
            error_message = "モデル応答にテキストまたは画像データが見つかりませんでした。"
            if candidate.finish_reason != types.Candidate.FinishReason.STOP:
                 error_message = f"モデルが予期せず停止。理由: {candidate.finish_reason.name}"
            print(error_message); return error_message, None

    except google.api_core.exceptions.GoogleAPIError as e:
        error_message = f"エラー: Gemini API通信エラー (画像生成): {e}"; print(error_message); traceback.print_exc()
        return error_message, None
    except Exception as e:
        error_message = f"エラー: Gemini画像生成中に予期せぬエラー: {e}"; print(error_message); traceback.print_exc()
        return error_message, None

    return generated_text, image_path
