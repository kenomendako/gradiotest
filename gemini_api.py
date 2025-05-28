# -*- coding: utf-8 -*-
import google.generativeai as genai
from google.generativeai import types
import os
import json
import google.api_core.exceptions
import re
import math
import traceback
from PIL import Image
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

def send_to_gemini(system_prompt_path, log_file_path, user_prompt, selected_model, character_name, send_thoughts_to_api, api_history_limit_option, image_path=None, memory_json_path=None):
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
    u_parts, log_txt, img_log, pil = [], "", "", None
    if user_prompt: u_parts.append({"text": user_prompt}); log_txt = user_prompt
    if image_path and os.path.exists(image_path):
        try:
            pil = Image.open(image_path)
            img_format = pil.format.upper()
            if img_format not in ["JPEG", "PNG", "WEBP", "HEIC", "HEIF"]:
                 print(f"警告: 画像 '{os.path.basename(image_path)}' の形式 ({img_format}) はGeminiでサポートされていない可能性があります。送信を試みますが、エラーになる場合があります。")
            u_parts.append(pil)
            img_log = f"[画像添付:{os.path.basename(image_path)}]"
        except Exception as e:
            print(f"画像ファイル '{image_path}' の処理中にエラー: {e}")
            img_log = f"[画像読み込みエラー:{e}]"
            if pil: pil.close(); pil = None
    fin_log = (log_txt + " " + img_log).strip()
    if not u_parts: return "エラー: 送信するテキストまたは画像がありません。", fin_log or ""
    print(f"Gemini ({selected_model}) へ送信開始... 履歴: {len(g_hist)}件, 新規入力パーツ: {len(u_parts)}件")
    try:
        model_kwargs = {
            "model_name": selected_model,
            "system_instruction": sys_ins,
            "safety_settings": config_manager.SAFETY_CONFIG
        }
        if "2.5-pro" in selected_model.lower() or "2.5-flash" in selected_model.lower():
            print(f"情報: モデル '{selected_model}' のため、Google検索グラウンディングを有効化します。")
            # GoogleSearchRetrievalが存在しない場合はtoolsを指定しない
            try:
                GoogleSearchRetrieval = getattr(types, "GoogleSearchRetrieval", None)
                if GoogleSearchRetrieval is not None:
                    model_kwargs["tools"] = [types.Tool(google_search_retrieval=GoogleSearchRetrieval())]
                else:
                    print("警告: types.GoogleSearchRetrieval が見つからないため、グラウンディング機能は無効化されます。")
            except Exception as e:
                print(f"警告: GoogleSearchRetrievalのセットアップ中に例外: {e}")
        else:
            print(f"情報: モデル '{selected_model}' は現在グラウンディング対象外です。")

        model = genai.GenerativeModel(**model_kwargs)
        resp = model.generate_content(g_hist + [{"role": "user", "parts": u_parts}])
        r_txt = None
        try:
            r_txt = resp.text
        except Exception as e:
            print(f"応答テキストの取得中にエラー: {e}")
            try: block_reason = resp.prompt_feedback.block_reason
            except: block_reason = "不明"
            return f"応答取得エラー ({e}) ブロック理由: {block_reason}", fin_log
        return (r_txt.strip() if r_txt is not None else "応答生成失敗 (空の応答)"), fin_log
    except google.api_core.exceptions.ResourceExhausted as e:
        error_message = f"Gemini APIとの通信中にエラーが発生しました: {str(e)}"
        print(error_message)
        return f"エラー: {error_message}", None
    except Exception as e:
        error_message = f"予期しないエラーが発生しました: {str(e)}"
        print(error_message)
        return f"エラー: {error_message}", None
    finally:
        if pil: pil.close()

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