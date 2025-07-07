import google.genai as genai
import os
import io
import json
import traceback
from typing import List, Union # Union を追加
from PIL import Image
import base64
import re # re をインポート

import config_manager
import utils # utils全体をインポート
from character_manager import get_character_files_paths
from agent.graph import app
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

def _build_lc_messages_from_ui(character_name: str, parts: list, api_history_limit_option: str) -> List[Union[SystemMessage, HumanMessage, AIMessage]]:
    """UIからの入力に基づいて、LangChainのメッセージオブジェクトのリストを構築する共通関数"""
    messages: List[Union[SystemMessage, HumanMessage, AIMessage]] = [] # 型ヒントをより具体的に

    # 1. システムプロンプト
    _, sys_prompt_file, _, _ = get_character_files_paths(character_name)
    system_prompt_content = ""
    if sys_prompt_file and os.path.exists(sys_prompt_file):
        with open(sys_prompt_file, 'r', encoding='utf-8') as f:
            system_prompt_content = f.read().strip()
    if system_prompt_content:
        messages.append(SystemMessage(content=system_prompt_content))
    else:
        print(f"警告: キャラクター '{character_name}' のシステムプロンプトファイルが見つからないか空です。")

    # 2. 会話履歴
    log_file, _, _, _ = get_character_files_paths(character_name)
    raw_history = utils.load_chat_log(log_file, character_name) # 修正: utils.load_chat_log を使用

    # API履歴制限の準備 (SystemMessageを除外してカウント)
    history_for_limit_check = []
    for h_item in raw_history:
        role = h_item.get('role')
        content = h_item.get('content', '').strip()
        if not content:
            continue
        # 履歴のロールをLangChainのメッセージタイプに正規化
        if role == 'model' or role == 'assistant' or role == character_name:
            history_for_limit_check.append(AIMessage(content=content))
        elif role == 'user' or role == 'human':
            history_for_limit_check.append(HumanMessage(content=content))

    limit = 0
    if api_history_limit_option.isdigit(): # "all" などの文字列を考慮
        limit = int(api_history_limit_option)

    if limit > 0 and len(history_for_limit_check) > limit * 2: # 実際のメッセージペア数で制限
        history_for_limit_check = history_for_limit_check[-(limit * 2):]

    messages.extend(history_for_limit_check) # 制限適用後の履歴を追加

    # 3. ユーザーの最新入力
    user_message_content_parts = []
    text_buffer = []
    for part_item in parts:
        if isinstance(part_item, str):
            text_buffer.append(part_item)
        elif isinstance(part_item, Image.Image):
            if text_buffer: # 画像の前にテキストがあれば先に追加
                user_message_content_parts.append({"type": "text", "text": "\n".join(text_buffer).strip()})
                text_buffer = []

            buffered = io.BytesIO()
            image_format = part_item.format or 'PNG' # 元のフォーマットを尊重
            # JPEG保存時のRGBA/Pモードエラー回避
            save_image = part_item.convert('RGB') if part_item.mode in ('RGBA', 'P') and image_format.upper() == 'JPEG' else part_item
            save_image.save(buffered, format=image_format)
            img_byte = buffered.getvalue()
            img_base64 = base64.b64encode(img_byte).decode('utf-8')
            mime_type = f"image/{image_format.lower()}"
            # LangChainが期待するimage_url形式 (Data URI)
            user_message_content_parts.append({"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{img_base64}"}})

    if text_buffer: # 残りのテキストを追加
        user_message_content_parts.append({"type": "text", "text": "\n".join(text_buffer).strip()})

    if user_message_content_parts:
        # LangChainのHumanMessageはcontentが文字列の場合とリストの場合で扱いが異なる
        # 文字列のみの場合は直接文字列を、複数のパートがある場合はリストを渡す
        if len(user_message_content_parts) == 1 and user_message_content_parts[0]["type"] == "text":
            messages.append(HumanMessage(content=user_message_content_parts[0]["text"]))
        else:
            messages.append(HumanMessage(content=user_message_content_parts))

    return messages

def _convert_lc_messages_to_gg_contents(messages: List[Union[SystemMessage, HumanMessage, AIMessage]]) -> (list, dict):
    """LangChainのMessageリストを、google-genai SDKのcontentsとsystem_instructionに変換"""
    contents = []
    system_instruction_dict = None # 修正: 変数名を変更し、Noneで初期化

    for msg in messages:
        if isinstance(msg, SystemMessage):
            # system_instructionは一つだけなので、最初に見つかったものを採用
            if system_instruction_dict is None:
                 system_instruction_dict = {"parts": [{"text": msg.content}]}
            else:
                print("警告: 複数のSystemMessageが見つかりました。最初のものを採用します。")
            continue # SystemMessageはcontentsには含めない

        role = "model" if isinstance(msg, AIMessage) else "user"

        sdk_parts = []
        if isinstance(msg.content, str):
            sdk_parts.append({"text": msg.content})
        elif isinstance(msg.content, list): # HumanMessage(content=[...]) の場合
            for part_data in msg.content:
                if part_data["type"] == "text":
                    sdk_parts.append({"text": part_data["text"]})
                elif part_data["type"] == "image_url":
                    # LangChainのimage_urlは {"url": "data:..."} という形式
                    data_uri = part_data["image_url"]["url"]
                    match = re.match(r"data:(image/\w+);base64,(.*)", data_uri)
                    if match:
                        mime_type, base64_data = match.groups()
                        try:
                            img_byte = base64.b64decode(base64_data)
                            sdk_parts.append({'inline_data': {'mime_type': mime_type, 'data': img_byte}})
                        except base64.binascii.Error as e:
                            print(f"警告: Base64デコードエラー。スキップします。URI: {data_uri[:50]}..., Error: {e}")
                    else:
                        print(f"警告: 不正なData URI形式です。スキップします。URI: {data_uri[:50]}...")

        if sdk_parts: # 有効なパーツがある場合のみcontentsに追加
            contents.append({"role": role, "parts": sdk_parts})

    return contents, system_instruction_dict


def count_input_tokens(character_name: str, model_name: str, parts: list, api_history_limit_option: str, api_key_name: str) -> int:
    """入力の合計トークン数を計算して返す"""
    api_key = config_manager.API_KEYS.get(api_key_name)
    if not api_key or api_key.startswith("YOUR_API_KEY"):
        print(f"トークン計算スキップ: APIキー '{api_key_name}' が無効です。")
        return -1

    try:
        # 1. LangChain形式のメッセージリストを構築
        lc_messages = _build_lc_messages_from_ui(character_name, parts, api_history_limit_option)
        if not lc_messages: # メッセージが空なら0トークン
            return 0

        # 2. Google-genai SDK形式に変換
        contents_for_api, system_instruction_for_api = _convert_lc_messages_to_gg_contents(lc_messages)

        # contentsが空でsystem_instructionのみの場合、count_tokensはエラーになる可能性があるためチェック
        if not contents_for_api and not system_instruction_for_api:
            return 0
        if not contents_for_api and system_instruction_for_api:
             # Google APIは通常、contentsなしでsystem_instructionのみのcount_tokensをサポートしない。
             # system_instructionのみのトークン数を数えたい場合は、ダミーのuser contentを追加するなどの工夫が必要になるが、
             # ここではUIからの入力が前提なので、このケースは稀とし、エラーとして扱うか、0を返す。
             # 安全策として0を返す。
             print("警告: トークン計算時、contentsが空でsystem_instructionのみでした。0トークンとして処理します。")
             return 0


        # AI_DEVELOPMENT_GUIDELINES.md に従い、genai.Client を使用
        client = genai.Client(api_key=api_key)
        model_to_use = f"models/{model_name}" # 'models/' プレフィックスが必要

        # count_tokens API呼び出し
        response = client.count_tokens( # client.models.count_tokens から client.count_tokens に変更 (SDKのバージョンによる違いの可能性)
                                           # ドキュメントを確認したところ、genai.GenerativeModel(...).count_tokens(...) が推奨されている
                                           # または client.count_tokens(model=..., contents=...)
                                           # 後者で試す
            model=model_to_use,
            contents=contents_for_api,
            system_instruction=system_instruction_for_api # system_instruction を渡す
        )
        return response.total_tokens
    except Exception as e:
        print(f"トークン計算エラー (model: {model_name}, char: {character_name}): {e}")
        traceback.print_exc() # 詳細なエラーログ
        return -2 # UI側で「計算エラー」と表示するための値

# invoke_nexus_agent 関数の修正
def invoke_nexus_agent(character_name: str, model_name: str, parts: list, api_history_limit_option: str, api_key_name: str):
    api_key = config_manager.API_KEYS.get(api_key_name)
    if not api_key or api_key.startswith("YOUR_API_KEY"):
        return f"エラー: APIキー名 '{api_key_name}' に有効なキーが設定されていません。", None
    try:
        # 1. メッセージリストの構築 (新しい共通関数を使用)
        messages = _build_lc_messages_from_ui(character_name, parts, api_history_limit_option)

        # ログファイルパスの取得 (これは変更なし)
        log_file, _, _, _ = get_character_files_paths(character_name)


        initial_state = {
            "messages": messages, # 更新されたメッセージリスト
            "character_name": character_name,
            "api_key": api_key,
            "final_model_name": model_name, # LangGraph内で最終的に使用されるモデル名
        }

        print(f"--- LangGraphエージェント呼び出し (Character: {character_name}, Final Model by User: {model_name}) ---")
        # print(f"DEBUG: LangGraphに渡す最初のメッセージリスト: {messages}") # デバッグ用
        final_state = app.invoke(initial_state)
        print("--- LangGraphエージェント実行完了 ---")

        response_text = "[エージェントからの応答がありませんでした]"
        # final_state['messages'] の最後の要素がAIMessageであることを期待
        if final_state and final_state.get('messages') and isinstance(final_state['messages'][-1], AIMessage):
            response_text = final_state['messages'][-1].content
        elif final_state and final_state.get('messages') and final_state['messages'][-1]:
             # AIMessageでない場合でも、content属性があればそれを、なければ文字列化する
             response_text = str(final_state['messages'][-1].content if hasattr(final_state['messages'][-1], 'content') else final_state['messages'][-1])

        # ユーザー入力とAI応答のログ保存は ui_handlers.py の handle_message_submission に集約されているのでここでは不要

        return response_text, None # 画像パスは返さないのでNone

    except Exception as e:
        traceback.print_exc()
        return f"エラー: エージェントの実行中にエラーが発生しました: {e}", None

# send_multimodal_to_gemini は変更なしのまま維持 (トークンカウント機能は主にエージェント呼び出し側で利用想定)
def send_multimodal_to_gemini(character_name: str, model_name: str, parts: list, api_history_limit_option: str, api_key_name: str):
    api_key = config_manager.API_KEYS.get(api_key_name)
    if not api_key or api_key.startswith("YOUR_API_KEY"):
        return f"エラー: APIキー名 '{api_key_name}' に有効なキーが設定されていません。", None

    try:
        log_file, sys_prompt_file, _, _ = get_character_files_paths(character_name)
        raw_history = utils.load_chat_log(log_file, character_name)

        limit = 0
        if api_history_limit_option and api_history_limit_option.isdigit():
            limit = int(api_history_limit_option)
        if limit > 0 and len(raw_history) > limit * 2: # ペアでカウント
            raw_history = raw_history[-(limit*2):]

        messages_for_api_direct_call = []
        # システムプロンプトの扱い (User/Modelのペアとして追加)
        if sys_prompt_file and os.path.exists(sys_prompt_file):
            with open(sys_prompt_file, 'r', encoding='utf-8') as f:
                system_instruction_text = f.read().strip()
            if system_instruction_text:
                # Gemini APIは厳密にはSystem Instructionをcontentsとは別に持つが、
                # この関数は直接呼び出し用なので、user/modelのやり取りとしてシステムプロンプトを模倣する
                messages_for_api_direct_call.append({'role': 'user', 'parts': [{'text': system_instruction_text}]})
                messages_for_api_direct_call.append({'role': 'model', 'parts': [{'text': "承知いたしました。"}]}) # AIの応答例

        for h_item in raw_history:
            # roleをuser/modelに正規化
            sdk_role = "model" if h_item["role"] == character_name or h_item["role"] == "assistant" else "user"
            messages_for_api_direct_call.append({
                "role": sdk_role,
                "parts": [{'text': h_item["content"]}]
            })

        user_message_parts_for_payload = []
        for part_data in parts:
            if isinstance(part_data, str):
                user_message_parts_for_payload.append({'text': part_data})
            elif isinstance(part_data, Image.Image):
                img_byte_arr = io.BytesIO()
                # JPEG保存時のRGBA/Pモードエラー回避
                save_image = part_data.convert('RGB') if part_data.mode in ('RGBA', 'P') else part_data
                save_image.save(img_byte_arr, format='JPEG') # 直接呼び出しはJPEG固定でよいか検討 (元コード通り)
                user_message_parts_for_payload.append({
                    'inline_data': {'mime_type': 'image/jpeg', 'data': img_byte_arr.getvalue()}
                })

        if not user_message_parts_for_payload:
            return "エラー: 送信するコンテンツがありません。", None

        messages_for_api_direct_call.append({'role': 'user', 'parts': user_message_parts_for_payload})

        model_to_call_name = f"models/{model_name}"
        # AI_DEVELOPMENT_GUIDELINES.md に従い、genai.Client を使用
        client_for_direct_call = genai.Client(api_key=api_key)

        # generate_content API呼び出し
        # system_instruction は messages_for_api_direct_call に user/model のやり取りとして含めているのでここではNone
        response = client_for_direct_call.generate_content( # client.models.generate_content から client.generate_content (SDKバージョンによる違いの可能性)
                                                              # ドキュメントでは genai.GenerativeModel(...).generate_content(...)
                                                              # または client.generate_content(model=..., contents=...)
                                                              # 後者で試す
            model=model_to_call_name,
            contents=messages_for_api_direct_call
        )

        generated_text = "[応答なし]"
        if hasattr(response, 'text') and response.text: # 通常のテキスト応答
            generated_text = response.text
        elif response.candidates and response.candidates[0].content and response.candidates[0].content.parts: # マルチパート応答の場合
            generated_text = "".join([part.text for part in response.candidates[0].content.parts if hasattr(part, 'text') and part.text])
        elif response.prompt_feedback and response.prompt_feedback.block_reason: # ブロックされた場合
            generated_text = f"[応答ブロック: 理由: {response.prompt_feedback.block_reason}]"

        # ログ保存は ui_handlers.py に移管されているため、ここでの直接のログ保存処理は削除またはコメントアウトを検討。
        # ただし、この関数が単独で呼ばれる可能性も考慮すると、残す判断も有り得る。
        # 現状は元のコードのログ保存ロジックを維持。
        user_input_text = ""
        for p in parts:
            if isinstance(p, str):
                user_input_text += p + "\n"
        user_input_text = user_input_text.strip()

        attached_file_names = []
        for p in parts:
            if not isinstance(p, str): # 画像など
                if hasattr(p, 'filename') and p.filename: # GradioのFileオブジェクトなど
                     attached_file_names.append(os.path.basename(p.filename))
                elif isinstance(p, Image.Image) and hasattr(p, 'fp') and hasattr(p.fp, 'name'): # Image.open(filepath) の場合
                     attached_file_names.append(os.path.basename(p.fp.name))


        if attached_file_names:
            user_input_text += "\n[ファイル添付: " + ", ".join(attached_file_names) + "]"

        if user_input_text.strip() or attached_file_names:
            user_header = utils._get_user_header_from_log(log_file, character_name)
            utils.save_message_to_log(log_file, user_header, user_input_text.strip())
            utils.save_message_to_log(log_file, f"## {character_name}:", generated_text)


        return generated_text, None

    except Exception as e:
        traceback.print_exc()
        error_message = f"エラー: モデル '{model_name}' との通信中に予期しないエラーが発生しました: {e}"
        # response変数がエラー発生前に定義されているか確認
        if 'response' in locals() and hasattr(response, 'prompt_feedback') and response.prompt_feedback:
            error_message += f"\nプロンプトフィードバック: {response.prompt_feedback}"
        return error_message, None
