# -*- coding: utf-8 -*-
import google.genai as genai
from google.genai import types
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

# --- Google API (Gemini) 連携関数 ---
def configure_google_api(api_key_name):
    if not api_key_name: return False, "APIキー名が指定されていません。"
    # 関数内で config_manager.API_KEYS を参照するように変更
    api_key = config_manager.API_KEYS.get(api_key_name)
    if not api_key or api_key.startswith("YOUR_API_KEY"):
        # エラーメッセージは変更せず、参照方法のみ変更
        return False, f"APIキー名 '{api_key_name}' に対応する有効なAPIキーが設定されていません。"
    try:
        genai.configure(api_key=api_key)
        print(f"Google API キー '{api_key_name}' の設定が完了しました。")
        return True, None
    except Exception as e:
        return False, f"APIキー '{api_key_name}' の設定中にエラーが発生しました: {e}"

def send_to_gemini(system_prompt_path, log_file_path, user_prompt, selected_model, character_name, send_thoughts_to_api, api_history_limit_option, uploaded_file_parts: list = None, memory_json_path=None): # MODIFIED signature
    print(f"--- 通常対話開始 --- Thoughts API送信: {send_thoughts_to_api}, 履歴制限: {api_history_limit_option}")
    sys_ins = "あなたはチャットボットです。"
    if system_prompt_path and os.path.exists(system_prompt_path):
        try:
            with open(system_prompt_path, "r", encoding="utf-8") as f: sys_ins = f.read().strip() or sys_ins
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
            if m_api: sys_ins += f"\n\n---\n## 参考記憶:\n{json.dumps(m_api, indent=2, ensure_ascii=False)}\n---"
        except Exception as e: print(f"記憶ファイル '{memory_json_path}' 読込/処理エラー: {e}")
    msgs = load_chat_log(log_file_path, character_name)
    if api_history_limit_option.isdigit():
        limit_turns = int(api_history_limit_option)
        limit_msgs = limit_turns * 2
        if len(msgs) > limit_msgs:
            print(f"情報: API履歴を直近 {limit_turns} 往復 ({limit_msgs} メッセージ) に制限します。")
            msgs = msgs[-limit_msgs:]
        else:
            print(f"情報: API履歴は全 {len(msgs)} メッセージ ({math.ceil(len(msgs)/2)} 往復相当) を送信します（制限未満）。")
    else:
         print(f"情報: API履歴は全 {len(msgs)} メッセージ ({math.ceil(len(msgs)/2)} 往復相当) を送信します。")
    g_hist = []
    th_pat = re.compile(r"【Thoughts】.*?【/Thoughts】\s*", re.DOTALL | re.IGNORECASE)
    for m in msgs:
        r, c = m.get("role"), m.get("content", "")
        if not c: continue
        a_c = c
        if r == "user":
            a_c = re.sub(r"\[画像添付:[^\]]+\]", "", a_c).strip()
        elif r == "model" and not send_thoughts_to_api:
             a_c = th_pat.sub("", a_c).strip()
        if a_c: g_hist.append({"role": r, "parts": [{"text": a_c}]})

    parts_for_gemini_api = []
    if user_prompt:
        parts_for_gemini_api.append({"text": user_prompt})

    if uploaded_file_parts: # This is the new list of file details
        for file_detail in uploaded_file_parts:
            file_path = file_detail['path']
            mime_type = file_detail['mime_type']
            if os.path.exists(file_path):
                try:
                    with open(file_path, 'rb') as f_bytes:
                        file_bytes = f_bytes.read()
                    encoded_data = base64.b64encode(file_bytes).decode('utf-8')
                    parts_for_gemini_api.append({
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": encoded_data
                        }
                    })
                    print(f"情報: ファイル '{os.path.basename(file_path)}' ({mime_type}) をAPIリクエストに追加しました。")
                except Exception as e:
                    print(f"警告: ファイル '{os.path.basename(file_path)}' の処理中にエラー: {e}. スキップします。")
            else:
                print(f"警告: 指定されたファイルパス '{file_path}' が見つかりません。スキップします。")
    
    # If only text was provided and it was empty, or only files were provided but all failed to process
    if not parts_for_gemini_api:
        # Check if there was an original user_prompt (even if empty string) or any file parts attempted
        if user_prompt is not None or uploaded_file_parts: # User intended to send something
             return "エラー: 送信する有効なコンテンツがありません (テキストが空か、ファイル処理に失敗しました)。"
        else: # Should have been caught by ui_handlers, but as a safeguard
             return "エラー: 送信するテキストまたはファイルが指定されていません。"

    print(f"Gemini ({selected_model}) へ送信開始... 履歴: {len(g_hist)}件, 新規入力パーツ: {len(parts_for_gemini_api)}件")
    try:
        model_kwargs = {
            "model_name": selected_model,
            "system_instruction": sys_ins,
            "safety_settings": config_manager.SAFETY_CONFIG
        }
        if "2.5-pro" in selected_model.lower() or "2.5-flash" in selected_model.lower():
            print(f"情報: モデル '{selected_model}' のため、Google検索グラウンディング (google-genai SDK) を有効化しようと試みます。")
            try:
                # Assuming types.Tool and types.GoogleSearchRetrieval are available
                # from 'from google.genai import types'
                tool_instance = types.Tool(google_search_retrieval=types.GoogleSearchRetrieval())
                model_kwargs["tools"] = [tool_instance]
                print("情報: Google検索グラウンディング (google-genai SDK) がセットアップされました。")
            except AttributeError as ae:
                # This would occur if Tool or GoogleSearchRetrieval are not attributes of 'types'
                print(f"警告: `google.genai.types` モジュールに `Tool` または `GoogleSearchRetrieval` が見つかりません: {ae}。検索グラウンディングは無効になります。")
            except Exception as e:
                print(f"警告: Google検索グラウンディング (google-genai SDK) のセットアップ中に予期せぬ例外が発生しました: {e}。検索グラウンディングは無効になります。")
        else:
            print(f"情報: モデル '{selected_model}' は現在グラウンディング対象外のため、検索グラウンディングは試行されません。")

        model = genai.GenerativeModel(**model_kwargs)
        # Use parts_for_gemini_api for the user's current turn
        resp = model.generate_content(g_hist + [{"role": "user", "parts": parts_for_gemini_api}])
        r_txt = None
        try:
            r_txt = resp.text
        except Exception as e:
            print(f"応答テキストの取得中にエラー: {e}")
            try: block_reason = resp.prompt_feedback.block_reason
            except: block_reason = "不明"
            return f"応答取得エラー ({e}) ブロック理由: {block_reason}" # Removed fin_log
        return (r_txt.strip() if r_txt is not None else "応答生成失敗 (空の応答)") # Removed fin_log
    except google.api_core.exceptions.ResourceExhausted as e:
        error_message = f"Gemini APIとの通信中にエラーが発生しました: {str(e)}"
        print(error_message)
        return f"エラー: {error_message}" # Removed None
    except Exception as e:
        error_message = f"予期しないエラーが発生しました: {str(e)}"
        print(error_message)
        return f"エラー: {error_message}" # Removed None
    # Removed PIL image closing as it's not opened here anymore

def send_alarm_to_gemini(character_name, theme, flash_prompt_template, alarm_model_name, api_key_name, log_file_path, alarm_api_history_turns):
    print(f"--- アラーム応答生成開始 --- キャラ: {character_name}, テーマ: '{theme}'")
    # configure_google_api は内部で config_manager.API_KEYS を参照するようになった
    ok, msg = configure_google_api(api_key_name)
    if not ok: return f"【アラームエラー】APIキー設定失敗: {msg}"
    sys_ins = ""
    if flash_prompt_template:
        sys_ins = flash_prompt_template.replace("[キャラクター名]", character_name).replace("[テーマ内容]", theme)
        sys_ins += "\n\n**重要:** あなたの思考過程、応答の候補、メタテキスト（例: ---）などは一切出力せず、ユーザーに送る最終的な短いメッセージ本文のみを生成してください。"
        print("情報: アラーム応答にカスタムプロンプトを使用します。")
    elif theme:
        sys_ins = f"""あなたはキャラクター「{character_name}」です。
以下のテーマについて、ユーザーに送る短いメッセージを生成してください。
過去の会話履歴があれば参考にし、自然な応答を心がけてください。

テーマ: {theme}

重要: あなたの思考過程、応答の候補リスト、自己対話、マーカー（例: `---`）などは一切含めず、ユーザーに送る最終的な短いメッセージ本文のみを出力してください。"""
        print("情報: アラーム応答にデフォルトプロンプト（テーマ使用）を使用します。")

    _, _, _, memory_json_path = get_character_files_paths(character_name)
    if memory_json_path and os.path.exists(memory_json_path):
        try:
            with open(memory_json_path, "r", encoding="utf-8") as f:
                mem = json.load(f)
                # 関数内で config_manager.MEMORY_SUMMARY_LIMIT_FOR_API を参照
                m_api = {k: v for k, v in {
                    "user_profile": mem.get("user_profile"),
                    "self_identity": mem.get("self_identity"),
                    "shared_language": mem.get("shared_language"),
                    "current_context": mem.get("current_context"),
                    "memory_summary": mem.get("memory_summary", [])[-config_manager.MEMORY_SUMMARY_LIMIT_FOR_API:] # 変更
                }.items() if v}
                if m_api:
                    sys_ins += f"\n\n---\n## 参考記憶:\n{json.dumps(m_api, indent=2, ensure_ascii=False)}\n---"
                    print("情報: memory.json の内容をシステムプロンプトに追加しました。")
        except Exception as e:
            print(f"記憶ファイル '{memory_json_path}' 読込/処理エラー: {e}")
    else:
        print("情報: memory.json が見つからないため、記憶データは追加されません。")

    print("情報: アラーム応答生成ではキャラクター記憶を参照します。")
    g_hist = []
    if alarm_api_history_turns > 0:
        msgs = load_chat_log(log_file_path, character_name)
        limit_msgs = alarm_api_history_turns * 2
        if len(msgs) > limit_msgs: msgs = msgs[-limit_msgs:]
        th_pat = re.compile(r"【Thoughts】.*?【/Thoughts】\s*", re.DOTALL | re.IGNORECASE)
        img_pat = re.compile(r"\[画像添付:[^\]]+\]")
        alrm_pat = re.compile(r"（システムアラーム：.*?）")
        for m in msgs:
            r, c = m.get("role"), m.get("content", "")
            if not c: continue
            a_c = th_pat.sub("", c).strip() if r == "model" else img_pat.sub("", c).strip()
            a_c = alrm_pat.sub("", a_c).strip()
            if a_c: g_hist.append({"role": r, "parts": [{"text": a_c}]})
        print(f"情報: アラーム応答生成のために、直近 {alarm_api_history_turns} 往復 ({len(g_hist)} 件) の整形済み履歴を参照します。")
    else:
        print("情報: アラーム応答生成では履歴を参照しません。")
    contents_to_send = g_hist
    if not contents_to_send:
        print("情報: 履歴が空のため、API呼び出し用に形式的なユーザー入力を追加します。")
        contents_to_send = [{"role": "user", "parts": [{"text": "（時間になりました。アラームメッセージをお願いします。）"}]}]
    elif contents_to_send and contents_to_send[-1].get("role") == "model":
        print("情報: 履歴の最後がモデル応答のため、API呼び出し用に形式的なユーザー入力を追加します。")
        contents_to_send.append({"role": "user", "parts": [{"text": "（続けて）"}]})
    if not contents_to_send:
         print("致命的エラー: APIに送信するコンテンツリストを作成できませんでした。")
         return "【アラームエラー】内部エラー: 送信コンテンツ空"
    print(f"アラーム用モデル ({alarm_model_name}) へ送信開始... 送信contents件数: {len(contents_to_send)}")
    try:
        # 関数内で config_manager.SAFETY_CONFIG を参照
        model = genai.GenerativeModel(alarm_model_name, system_instruction=sys_ins, safety_settings=config_manager.SAFETY_CONFIG) # 変更
        resp = model.generate_content(contents_to_send)
        r_txt = None
        try:
            r_txt = resp.text
        except Exception as e:
            print(f"アラーム応答テキストの取得中にエラー: {e}")
            try: block_reason = resp.prompt_feedback.block_reason
            except: block_reason = "不明"
            block_reason_str = str(block_reason) if block_reason is not None else "不明"
            return f"【アラームエラー】応答取得失敗 ({e}) ブロック理由: {block_reason_str}"
        if r_txt is not None:
            # コードブロック（```）で始まる場合は何も除去しない
            if r_txt.strip().startswith("```"):
                cleaned_resp = r_txt.strip()
            else:
                cleaned_resp = re.sub(r"^\s*([-*_#=`>]+|\n)+\s*", "", r_txt.strip())
            return cleaned_resp
        else:
            return "【アラームエラー】モデルから空の応答が返されました。"
    except types.generation_types.BlockedPromptException as bpe:
        print(f"アラームAPI呼び出しでプロンプトがブロックされました: {bpe}")
        return f"【アラームエラー】プロンプトブロック"
    except types.generation_types.StopCandidateException as sce:
         print(f"アラームAPI呼び出しで候補生成が停止されました: {sce}")
         return f"【アラームエラー】候補生成停止"
    except Exception as e:
        print(f"アラーム用モデル ({alarm_model_name}) との通信中にエラーが発生しました: {e}"); traceback.print_exc()
        return f"【アラームエラー】API通信失敗: {e}"