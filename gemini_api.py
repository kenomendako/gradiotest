# gemini_api.py (Dual-State Architecture Implementation)

import tiktoken
import traceback
from typing import Any, List, Union, Optional, Dict, Iterator
import os
import json
import re
import time
import datetime
import base64
import io
import filetype
import httpx
from PIL import Image

import google.genai as genai
from google.api_core.exceptions import ResourceExhausted, ServiceUnavailable, InternalServerError
import google.genai.errors

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage, AIMessageChunk
from langchain_google_genai import HarmCategory, HarmBlockThreshold, ChatGoogleGenerativeAI

import config_manager
import constants
import room_manager
import utils
import signature_manager 
from episodic_memory_manager import EpisodicMemoryManager

# --- トークン計算関連 (変更なし) ---
def get_model_token_limits(model_name: str, api_key: str, provider: str = None) -> Optional[Dict[str, int]]:
    # 注釈（かっこ書き）を除去
    model_name = model_name.split(" (")[0].strip() if model_name else model_name
    
    if model_name in utils._model_token_limits_cache: return utils._model_token_limits_cache[model_name]
    if not api_key or api_key.startswith("YOUR_API_KEY"): return None
    
    # 【マルチモデル対応】OpenAIモデルの場合はGemini APIを呼び出さない
    # gpt-、o1-、claude-などGemini以外のモデルはGemini APIで情報取得不可
    if not provider:
        provider = config_manager.get_active_provider()

    # '/'が含まれる場合（例: mistralai/mistral-7b...）もOpenAI互換とみなす
    is_openai_model = (
        provider == "openai" or 
        model_name.startswith(("gpt-", "o1-", "claude-", "llama-", "mixtral-", "mistral-")) or
        "/" in model_name 
    )
    
    if is_openai_model:
        # OpenAI互換モデルのトークン制限は一般的なデフォルト値を返す
        # 正確な値が必要な場合は、各プロバイダのAPIを呼び出す必要があるが、
        # トークンカウントはあくまで参考値なので概算で十分
        return {"input": 128000, "output": 8192}  # GPT-4o相当のデフォルト値
    
    try:
        client = genai.Client(api_key=api_key)
        model_info = client.models.get(model=f"models/{model_name}")
        if model_info and hasattr(model_info, 'input_token_limit') and hasattr(model_info, 'output_token_limit'):
            limits = {"input": model_info.input_token_limit, "output": model_info.output_token_limit}
            utils._model_token_limits_cache[model_name] = limits
            return limits
        return None
    except Exception as e: print(f"モデル情報の取得中にエラー: {e}"); return None

def _convert_lc_to_gg_for_count(messages: List[Union[SystemMessage, HumanMessage, AIMessage]]) -> List[Dict]:
    contents = []
    for msg in messages:
        role = "model" if isinstance(msg, AIMessage) else "user"
        sdk_parts = []
        if isinstance(msg.content, str):
            sdk_parts.append({"text": msg.content})
        elif isinstance(msg.content, list):
            for part_data in msg.content:
                if not isinstance(part_data, dict): continue
                part_type = part_data.get("type")
                if part_type == "text": sdk_parts.append({"text": part_data.get("text", "")})
                elif part_type == "image_url":
                    url_data = part_data.get("image_url", {}).get("url", "")
                    if url_data.startswith("data:"):
                        try:
                            header, encoded = url_data.split(",", 1); mime_type = header.split(":")[1].split(";")[0]
                            sdk_parts.append({"inline_data": {"mime_type": mime_type, "data": encoded}})
                        except: pass
                elif part_type == "media_url":
                    url_data = part_data.get("media_url", "")
                    if url_data.startswith("data:"):
                        try:
                            header, encoded = url_data.split(",", 1)
                            mime_type = header.split(":")[1].split(";")[0]
                            sdk_parts.append({"inline_data": {"mime_type": mime_type, "data": encoded}})
                        except: pass
                elif part_type == "media": sdk_parts.append({"inline_data": {"mime_type": part_data.get("mime_type", "application/octet-stream"),"data": part_data.get("data", "")}})
        if sdk_parts: contents.append({"role": role, "parts": sdk_parts})
    return contents

def count_tokens_from_lc_messages(messages: List, model_name: str, api_key: str) -> int:
    if not messages: return 0
    # 注釈（かっこ書き）を除去
    model_name = model_name.split(" (")[0].strip() if model_name else model_name

    # モデル名に "gemini" が含まれていない、または active_provider が openai の場合
    active_provider = config_manager.get_active_provider()
    
    if active_provider != "google" or "gemini" not in model_name.lower():
        try:
            # OpenAI互換のトークナイザー(cl100k_base)で概算する
            # Llama 3のトークナイザーとは厳密には異なるが、APIを叩かずに済む安全策として十分
            encoding = tiktoken.get_encoding("cl100k_base")
            total_tokens = 0
            for msg in messages:
                content = ""
                if isinstance(msg.content, str):
                    content = msg.content
                elif isinstance(msg.content, list):
                    # マルチモーダルのテキスト部分だけ抽出
                    for part in msg.content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            content += part.get("text", "") + " "
                
                if content:
                    total_tokens += len(encoding.encode(content))
            
            # 安全係数（システムプロンプトやツール定義の分を少し上乗せ）
            return int(total_tokens * 1.1) + 100
            
        except Exception as e:
            print(f"ローカル・トークン計算エラー: {e}")
            # 最悪の場合、文字数/2 程度で返す
            return sum(len(str(m.content)) for m in messages) // 2

    # --- 以下、既存のGoogle APIを使用するロジック ---
    client = genai.Client(api_key=api_key)
    contents_for_api = _convert_lc_to_gg_for_count(messages)
    
    final_contents_for_api = []
    if contents_for_api and contents_for_api[0]['role'] == 'user' and isinstance(messages[0], SystemMessage):
        system_instruction_parts = contents_for_api[0]['parts']
        final_contents_for_api.append({"role": "user", "parts": system_instruction_parts})
        final_contents_for_api.append({"role": "model", "parts": [{"text": "OK"}]})
        final_contents_for_api.extend(contents_for_api[1:])
    else:
        final_contents_for_api = contents_for_api

    max_retries = 3
    retry_delay = 2
    for attempt in range(max_retries):
        try:
            result = client.models.count_tokens(model=f"models/{model_name}", contents=final_contents_for_api)
            return result.total_tokens
        except (ResourceExhausted, ServiceUnavailable, InternalServerError, google.genai.errors.ClientError) as e: # ClientErrorもキャッチ
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                retry_delay *= 2
            else:
                print(f"トークン計算APIエラー: {e}")
                return 0
    return 0

# --- 日付ベースフィルタリング関数 ---

def _get_effective_today_cutoff(room_name: str) -> str:
    """
    「本日分」の切り捨て日付を決定する。
    
    昨日のエピソード記憶が存在する場合は今日以降のみ（昨日分は記憶化済み）。
    存在しない場合は昨日以降も含める（エピソード記憶が生成されるまでは前日のログも必要）。
    
    Returns:
        YYYY-MM-DD形式の日付文字列
    """
    import os
    import json
    from constants import ROOMS_DIR
    
    today = datetime.datetime.now()
    today_str = today.strftime('%Y-%m-%d')
    yesterday_str = (today - datetime.timedelta(days=1)).strftime('%Y-%m-%d')
    
    # エピソード記憶ファイルを確認
    # パス: characters/[room_name]/memory/episodic_memory.json
    episodic_dir = os.path.join(ROOMS_DIR, room_name, "memory")
    episode_file = os.path.join(episodic_dir, "episodic_memory.json")
    
    has_yesterday_memory = False
    
    if os.path.exists(episode_file):
        try:
            with open(episode_file, 'r', encoding='utf-8') as f:
                episodes = json.load(f)
                
            if isinstance(episodes, list):
                for ep in episodes:
                    if not isinstance(ep, dict): continue
                    date_str = ep.get('date', '').strip()
                    
                    if date_str == yesterday_str:
                        has_yesterday_memory = True
                        break
                    elif '~' in date_str or '～' in date_str:
                        sep = '~' if '~' in date_str else '～'
                        parts = date_str.split(sep)
                        if len(parts) == 2:
                            start, end = parts[0].strip(), parts[1].strip()
                            if start <= yesterday_str <= end:
                                has_yesterday_memory = True
                                break
        except Exception as e:
            print(f"Warning: Failed to check episodic memory for {yesterday_str}: {e}")

    if has_yesterday_memory:
        return today_str  # 昨日分は記憶化済み → 今日以降のみ
    else:
        return yesterday_str  # 昨日分は未処理 → 昨日以降も含める

def _filter_messages_from_today(messages: list, today_str: str) -> list:
    """
    本日（today_str）以降の最初のメッセージを見つけ、そこから最後まで全て返す。
    タイムスタンプがないメッセージも、本日分の開始以降であれば含まれる。
    
    Args:
        messages: LangChainメッセージのリスト
        today_str: 本日の日付文字列 (YYYY-MM-DD形式)
    
    Returns:
        本日分の開始から末尾までのメッセージリスト
    """
    date_pattern = re.compile(r'(\d{4}-\d{2}-\d{2})')
    
    # 本日分の開始インデックスを探す
    today_start_index = len(messages)  # デフォルトは末尾（何も見つからない場合）
    
    for i, msg in enumerate(messages):
        content = getattr(msg, 'content', '')
        if isinstance(content, list):
            content = ' '.join(p.get('text', '') if isinstance(p, dict) else str(p) for p in content)
        
        if isinstance(content, str):
            match = date_pattern.search(content)
            if match:
                msg_date = match.group(1)
                if msg_date >= today_str:
                    today_start_index = i
                    break
    
    return messages[today_start_index:]

def _filter_raw_history_from_today(raw_history: list, today_str: str) -> list:
    """
    生の履歴辞書リストから本日分の開始以降を抽出する。
    トークン計算用。
    """
    date_pattern = re.compile(r'(\d{4}-\d{2}-\d{2})')
    
    # 本日分の開始インデックスを探す
    today_start_index = len(raw_history)
    
    for i, item in enumerate(raw_history):
        content = item.get('content', '')
        if isinstance(content, str):
            match = date_pattern.search(content)
            if match:
                msg_date = match.group(1)
                if msg_date >= today_str:
                    today_start_index = i
                    break
    
    return raw_history[today_start_index:]

def _apply_auto_summary(
    messages: list, 
    room_name: str, 
    api_key: str,
    threshold: int,
    allow_generation: bool = True
) -> list:
    """
    自動会話要約を適用する。
    閾値を超えている場合、直近N往復を除いた部分を要約に置き換える。
    """
    import summary_manager
    from langchain_core.messages import HumanMessage, AIMessage
    
    # メッセージの総文字数を計算
    total_chars = sum(
        len(msg.content) if isinstance(msg.content, str) else 0 
        for msg in messages
    )
    
    if total_chars <= threshold:
        # 閾値以下なら何もしない
        return messages
    
    if allow_generation:
        print(f"  - [Auto Summary] 閾値超過: {total_chars:,} > {threshold:,}文字")
    
    # 直近N往復を保持
    keep_count = constants.AUTO_SUMMARY_KEEP_RECENT_TURNS * 2  # 往復なので×2
    
    if len(messages) <= keep_count:
        # メッセージ数が少なすぎる場合は要約しない
        return messages
    
    recent_messages = messages[-keep_count:]
    older_messages = messages[:-keep_count]
    
    # 既存の要約を読み込み
    existing_data = summary_manager.load_today_summary(room_name)
    existing_summary = existing_data.get("summary") if existing_data else None
    chars_summarized = existing_data.get("chars_summarized", 0) if existing_data else 0
    
    # 1. メッセージを分類
    # older_messages: 直近以外 (要約対象候補), recent_messages: 直近 (常に生で送る)
    recent_messages = messages[-keep_count:]
    older_messages = messages[:-keep_count]
    
    # older_messages 内で「すでに要約に含まれている分」と「まだ含まれていない分 (pending)」を分ける
    pending_messages = []
    cumulative_len = 0
    for msg in older_messages:
        msg_content = msg.content if isinstance(msg.content, str) else str(msg.content)
        msg_len = len(msg_content)
        if cumulative_len >= chars_summarized:
            pending_messages.append(msg)
        cumulative_len += msg_len

    # 2. 要約の実行判断
    pending_chars = sum(len(m.content) if isinstance(m.content, str) else 0 for m in pending_messages)
    
    # 判定A: 初めて閾値を超えた場合、または pending 分が閾値を超えた場合に要約/マージを実行
    should_summarize = False
    if not existing_summary:
        if total_chars > threshold:
            should_summarize = True
    else:
        if pending_chars > threshold:
            should_summarize = True

    new_summary = existing_summary
    if should_summarize:
        if not allow_generation:
            # トークン計算時は生成しない
            new_summary = existing_summary or "（要約生成待ち...）"
        else:
            # pending 分を辞書形式に変換
            to_summarize_dicts = []
            for msg in pending_messages:
                c_str = msg.content if isinstance(msg.content, str) else str(msg.content)
                role = "USER" if isinstance(msg, HumanMessage) else "AGENT"
                resp = getattr(msg, 'name', room_name) if role == "AGENT" else "user"
                to_summarize_dicts.append({"role": role, "responder": resp, "content": c_str})
            
            print(f"  - [Auto Summary] 要約/マージ実行: pending {pending_chars:,}文字 > 閾値 {threshold:,}文字")
            # 新しい要約を生成 (内部で既存要約とマージされる)
            new_summary = summary_manager.generate_summary(
                to_summarize_dicts, existing_summary, room_name, api_key
            )
            
            if new_summary:
                # 累計要約文字数を更新して保存
                # older_messages 全体が要約済みとなったとみなす
                total_older_len = sum(len(m.content) if isinstance(m.content, str) else 0 for m in older_messages)
                summary_manager.save_today_summary(room_name, new_summary, total_older_len)
                # 要約が更新されたので、pending は空になる
                pending_messages = []
            else:
                new_summary = existing_summary or "（要約生成失敗）"

    # 3. メッセージリストの構築
    result_messages = []
    
    # 要約が存在すれば最初に入れる
    if new_summary:
        summary_message = HumanMessage(
            content=f"【本日のこれまでの会話の要約】\n{new_summary}\n\n---\n（以下は、要約以降および直近の会話です）"
        )
        result_messages.append(summary_message)
        # 要約された後に残っている未要約分 (pending) を追加
        result_messages.extend(pending_messages)
    else:
        # 初回閾値到達前なら、すべて生で送る
        result_messages.extend(older_messages)
        
    # 常に直近分を追加
    result_messages.extend(recent_messages)
    
    if should_summarize and allow_generation:
        print(f"  - [Auto Summary] 要約更新完了: 累計 {cumulative_len:,}文字を圧縮")
    
    return result_messages

# --- 履歴構築 (Dual-Stateの核心) ---
def convert_raw_log_to_lc_messages(raw_history: list, responding_character_id: str, add_timestamp: bool, send_thoughts: bool, provider: str = "google") -> list:
    """
    ログ(テキスト)からメッセージを復元し、signature_manager(JSON) から
    最新の思考署名とツール呼び出し情報を注入して、完全な状態のオブジェクトを返す。
    (v2: ツール実行後の履歴でも正しく注入できるように修正)
    
    Args:
        provider: "google" または "openai"。OpenAI互換の場合は履歴平滑化を無効にする。
    """
    from langchain_core.messages import HumanMessage, AIMessage
    lc_messages = []
    timestamp_pattern = re.compile(r'\n\n\d{4}-\d{2}-\d{2} \(...\) \d{2}:\d{2}:\d{2}(?: \| .*)?$')

    # 1. JSONファイルから最新のターンコンテキストを取得
    # これらは「直近にAIが行ったツール呼び出し」の情報
    turn_context = signature_manager.get_turn_context(responding_character_id)
    # Gemini 3形式の署名を優先、なければ古い形式にフォールバック
    stored_signature = turn_context.get("gemini_function_call_thought_signatures") or turn_context.get("last_signature")
    stored_tool_calls = turn_context.get("last_tool_calls")

    # --- フェーズ1: 基本的なメッセージリストの構築 ---
    # 【追加項目】履歴の平滑化 (History Flattening)
    # 過去のツール使用履歴をプレーンテキストに変換し、Gemini 3 の推論負荷を軽減する。
    # 【重要】OpenAI互換API は tool_calls を持つ AIMessage の後に ToolMessage が必須のため、
    #        OpenAIプロバイダでは平滑化を無効にする。
    if provider == "openai":
        flatten_historical_tools = False  # OpenAI互換は tool_calls-ToolMessage の対応必須
    else:
        flatten_historical_tools = "gemini-3" in responding_character_id or "thinking" in responding_character_id.lower() or True


    for idx, h_item in enumerate(raw_history):
        content = h_item.get('content', '').strip()
        responder_id = h_item.get('responder', '')
        role = h_item.get('role', '')
        if not responder_id or not role: continue
        
        # タイムスタンプの抽出（メタデータ保持用）
        ts_match = timestamp_pattern.search(content)
        extracted_ts = ts_match.group(0).strip() if ts_match else None

        # タイムスタンプ除去
        if not add_timestamp:
            content = timestamp_pattern.sub('', content)

        is_user = (role == 'USER')
        is_self = (responder_id == responding_character_id)
        
        common_kwargs = {"timestamp": extracted_ts} if extracted_ts else {}

        if is_user:
            text_only_content = re.sub(r"\[ファイル添付:.*?\]", "", content, flags=re.DOTALL).strip()
            if text_only_content:
                lc_messages.append(HumanMessage(content=text_only_content, additional_kwargs=common_kwargs))
        elif is_self:
            # AIメッセージ。後続の履歴を確認し、これが「完了したツール呼び出し」かどうかを判定。
            is_historical_tool_call = False
            if flatten_historical_tools:
                # このメッセージより後に「ユーザーの発言」または「別の自分の発言」があれば、
                # このツール呼び出しは過去の会話の一部として平滑化しても良い。
                for next_item in raw_history[idx+1:]:
                    if next_item.get('role') == 'USER' or (next_item.get('responder') == responding_character_id and next_item.get('role') == 'AGENT'):
                        is_historical_tool_call = True
                        break

            # 歴史的な思考ログは、推論の混乱を招くため常に除去する。
            clean_content = utils.remove_thoughts_from_text(content)
            
            content_for_api = clean_content
            if not send_thoughts:
                # 明示的に非表示設定の場合は再確認して除去
                content_for_api = utils.remove_thoughts_from_text(clean_content)
            
            if content_for_api:
                # 過去のツール呼び出しを含むメッセージは、属性としての tool_calls を持たない
                # 純粋なテキストの AIMessage として追加することで「平滑化」を実現する。
                ai_msg = AIMessage(content=content_for_api, name=responder_id, additional_kwargs=common_kwargs)
                lc_messages.append(ai_msg)
                     
        elif role == 'SYSTEM' and responder_id.startswith('tool_result'):
            # 【OpenAI互換対応】OpenAI APIはtool_calls→ToolMessageの厳密な対応が必須。
            # テキストログからはtool_callsを完全に復元できないため、OpenAI互換では
            # ツール履歴を完全に除外して純粋な対話のみを送信する。
            if provider == "openai":
                continue  # OpenAI互換ではツール履歴を完全スキップ
            
            # 形式: ## SYSTEM:tool_result:<tool_name>:<tool_call_id>
            parts = responder_id.split(':')
            tool_name = parts[1] if len(parts) > 1 else "unknown"
            tool_call_id = parts[2] if len(parts) > 2 else "unknown"
            
            raw_match = re.search(r'\[RAW_RESULT\]\n(.*?)\n\[/RAW_RESULT\]', content, re.DOTALL)
            tool_content = raw_match.group(1) if raw_match else content

            # 【重要】これが「過去のツール結果」かどうかを判定。
            # 直後（またはそれ以降）に AI の返答があれば、それは過去の記録。
            is_historical_result = False
            if flatten_historical_tools:
                for next_item in raw_history[idx+1:]:
                    if next_item.get('responder') == responding_character_id and next_item.get('role') == 'AGENT':
                        is_historical_result = True
                        break
            
            # ただし、直前の AIMessage がまだ tool_calls を持っている（平滑化されていない）場合は
            # プロトコル維持のため、この結果を消してはならない。
            if is_historical_result:
                last_ai_flat = True
                for i in range(len(lc_messages)-1, -1, -1):
                    if isinstance(lc_messages[i], AIMessage) and lc_messages[i].name == responding_character_id:
                        if hasattr(lc_messages[i], 'tool_calls') and lc_messages[i].tool_calls:
                            last_ai_flat = False
                        break
                if not last_ai_flat:
                    is_historical_result = False

            if is_historical_result:
                # 【Phase 7】過去のツール実行結果は履歴から完全に除外する。
                # これにより、ユーザーとAIの純粋な対話のみが維持され、プロンプトの肥大化や文脈の混乱を防ぐ。
                continue
            else:
                # 最新の（まだ返答されていない）ツール結果のみを構造化メッセージとして保持
                tool_msg = ToolMessage(content=tool_content, tool_name=tool_name, tool_call_id=tool_call_id)
                lc_messages.append(tool_msg)

                # 直前の AIMessage を探し、tool_calls をバックフィルする（最新のセッションのみ）
                for i in range(len(lc_messages) - 2, -1, -1):
                    prev_msg = lc_messages[i]
                    if isinstance(prev_msg, AIMessage) and prev_msg.name == responding_character_id:
                        if not hasattr(prev_msg, 'tool_calls') or not prev_msg.tool_calls:
                            prev_msg.tool_calls = []
                        if not any(tc.get('id') == tool_call_id for tc in prev_msg.tool_calls):
                            prev_msg.tool_calls.append({"id": tool_call_id, "name": tool_name, "args": {}})
                        break
        else:
            other_agent_config = room_manager.get_room_config(responder_id)
            display_name = other_agent_config.get("room_name", responder_id) if other_agent_config else responder_id
            clean_content = utils.remove_thoughts_from_text(content)
            lc_messages.append(HumanMessage(content=f"（{display_name}の発言）:\n{clean_content}"))

    # --- フェーズ2: 最新ターンの署名とツールコールの注入 ---
    # JSONから取得したコンテキスト（未解決の呼び出し等）を、末尾のAIMessageに注入する。
    # 【OpenAI互換対応】OpenAI APIはtool_calls-ToolMessageの厳密な対応が必須。
    #                   テキストログからは完全に復元できないため、OpenAI互換ではこの注入をスキップ。
    if provider == "openai":
        # OpenAI互換ではtool_calls注入をスキップ（APIエラー回避）
        pass
    elif stored_tool_calls or stored_signature:
        for i in range(len(lc_messages) - 1, -1, -1):
            msg = lc_messages[i]
            if isinstance(msg, AIMessage) and msg.name == responding_character_id:
                if stored_tool_calls:
                    # 既に tool_calls がある場合は、重複しなければマージ
                    if not msg.tool_calls: msg.tool_calls = []
                    for tc in stored_tool_calls:
                        if not any(existing.get('id') == tc.get('id') for existing in msg.tool_calls):
                            msg.tool_calls.append(tc)
                
                if stored_signature:
                    if not msg.additional_kwargs: msg.additional_kwargs = {}
                    
                    # 署名を SDK が期待する {tool_call_id: signature} の辞書形式に変換
                    final_sig_dict = {}
                    if isinstance(stored_signature, dict):
                        final_sig_dict = stored_signature
                    else:
                        # 文字列やリストの場合は、現在の tool_calls と紐付ける
                        sig_val = stored_signature[0] if isinstance(stored_signature, list) and stored_signature else stored_signature
                        if msg.tool_calls:
                            for tc in msg.tool_calls:
                                tc_id = tc.get("id")
                                if tc_id: final_sig_dict[tc_id] = sig_val
                    
                    if final_sig_dict:
                        msg.additional_kwargs["__gemini_function_call_thought_signatures__"] = final_sig_dict
                break
            
    return merge_consecutive_messages(lc_messages, add_timestamp=add_timestamp)

def merge_consecutive_messages(lc_messages: list, add_timestamp: bool = False) -> list:
    """
    同一ロール（AI同士、Human同士）が連続するメッセージリストを、1つのメッセージに統合する。
    Gemini API プロトコル遵守のためのユーティリティ。
    """
    if not lc_messages:
        return []

    merged_messages = []
    curr_msg = lc_messages[0]
    
    for next_msg in lc_messages[1:]:
        # 同じクラス（HumanMessage, AIMessage）が連続し、かつ名前(name)も一致する場合、内容を結合する。
        # ToolMessage は結合対象外（AI->Tool->AIの順を保つため）。
        from langchain_core.messages import ToolMessage
        is_same_role = type(curr_msg) == type(next_msg) and not isinstance(curr_msg, ToolMessage)
        is_same_name = getattr(curr_msg, 'name', None) == getattr(next_msg, 'name', None)

        if is_same_role and is_same_name:
            # 結合部にタイムスタンプを注入して、AIが時間経過を把握できるようにする。
            # ただしユーザー設定でタイムスタンプがオフの場合は、詳細な時刻は伏せる。
            next_ts = next_msg.additional_kwargs.get("timestamp")
            if add_timestamp and next_ts:
                sep = f"\n\n--- (別タイミングの発言 / タイムスタンプ: {next_ts}) ---\n\n"
            else:
                sep = f"\n\n--- (別のタイミングの発言) ---\n\n" if next_ts else "\n\n"
            
            # コンテンツの結合 (Multipart リスト対応)
            def to_parts(content):
                if isinstance(content, list): return content
                return [{"type": "text", "text": str(content)}]

            c_parts = to_parts(curr_msg.content)
            n_parts = to_parts(next_msg.content)
            
            if isinstance(curr_msg.content, str) and isinstance(next_msg.content, str):
                # 両方文字列なら文字列として結合（シンプルさを維持）
                new_content = curr_msg.content + sep + next_msg.content
            else:
                # どちらかがリストなら、リストとして結合
                sep_part = [{"type": "text", "text": sep}] if sep.strip() else []
                new_content = c_parts + sep_part + n_parts
            
            # 属性（tool_calls, signatures 等）のマージ
            m_kwargs = {**curr_msg.additional_kwargs, **next_msg.additional_kwargs}
            m_tool_calls = []
            if hasattr(curr_msg, "tool_calls") and curr_msg.tool_calls:
                m_tool_calls.extend(curr_msg.tool_calls)
            if hasattr(next_msg, "tool_calls") and next_msg.tool_calls:
                for tc in next_msg.tool_calls:
                    if not any(existing.get('id') == tc.get('id') for existing in m_tool_calls):
                        m_tool_calls.append(tc)
            
            # 更新（in-place）
            curr_msg.content = new_content
            curr_msg.additional_kwargs = m_kwargs
            if hasattr(curr_msg, "tool_calls"):
                curr_msg.tool_calls = m_tool_calls
        else:
            merged_messages.append(curr_msg)
            curr_msg = next_msg
            
    merged_messages.append(curr_msg)
    return merged_messages

def invoke_nexus_agent_stream(agent_args: dict) -> Iterator[Dict[str, Any]]:
    from agent.graph import app

    # 引数展開
    room_to_respond = agent_args["room_to_respond"]
    api_key_name = agent_args["api_key_name"]
    api_history_limit = agent_args["api_history_limit"]
    debug_mode = agent_args["debug_mode"]
    history_log_path = agent_args["history_log_path"]
    user_prompt_parts = agent_args["user_prompt_parts"]
    soul_vessel_room = agent_args["soul_vessel_room"]
    active_participants = agent_args["active_participants"]
    active_attachments = agent_args["active_attachments"]
    shared_location_name = agent_args["shared_location_name"]
    shared_scenery_text = agent_args["shared_scenery_text"]
    season_en = agent_args["season_en"]
    time_of_day_en = agent_args["time_of_day_en"]
    global_model_from_ui = agent_args.get("global_model_from_ui")
    skip_tool_execution_flag = agent_args.get("skip_tool_execution", False)
    enable_supervisor_flag = agent_args.get("enable_supervisor", False)
    
    all_participants_list = [soul_vessel_room] + active_participants

    effective_settings = config_manager.get_effective_settings(
        room_to_respond,
        global_model_from_ui=global_model_from_ui,
        use_common_prompt=(len(all_participants_list) <= 1)
    )
    display_thoughts = effective_settings.get("display_thoughts", True)
    send_thoughts_final = display_thoughts and effective_settings.get("send_thoughts", True)
    model_name = effective_settings["model_name"]
    # APIキーの決定: ルーム個別設定があればそれを優先、なければUIからの引数を使用
    room_api_key_name = effective_settings.get("api_key_name")
    if room_api_key_name:
        api_key_name = room_api_key_name
        
    api_key = config_manager.GEMINI_API_KEYS.get(api_key_name)

    if not api_key or api_key.startswith("YOUR_API_KEY"):
        yield ("values", {"messages": [AIMessage(content=f"[エラー: APIキー '{api_key_name}' が無効です。]")]})
        return

    # 履歴構築（ここでJSONからの署名注入が行われる）
    messages = []
    add_timestamp = effective_settings.get("add_timestamp", False)
    
    # 【OpenAI互換対応】プロバイダを取得して履歴変換に渡す
    current_provider = config_manager.get_active_provider(room_to_respond)
    
    # 自身のログ
    responding_ai_log_f, _, _, _, _, _ = room_manager.get_room_files_paths(room_to_respond)
    if responding_ai_log_f and os.path.exists(responding_ai_log_f):
        own_history_raw = utils.load_chat_log(responding_ai_log_f)
        messages = convert_raw_log_to_lc_messages(own_history_raw, room_to_respond, add_timestamp, send_thoughts_final, provider=current_provider)

    # スナップショット
    if history_log_path and os.path.exists(history_log_path) and history_log_path != responding_ai_log_f:
        snapshot_history_raw = utils.load_chat_log(history_log_path)
        snapshot_messages = convert_raw_log_to_lc_messages(snapshot_history_raw, room_to_respond, add_timestamp, send_thoughts_final, provider=current_provider)
        if snapshot_messages:
             messages.extend(snapshot_messages)

    # ユーザー入力の調整
    is_first_responder = (room_to_respond == soul_vessel_room)
    if is_first_responder and messages and isinstance(messages[-1], HumanMessage):
        messages.pop()

    # プロンプトパーツの結合
    final_prompt_parts = []
    if active_attachments:
        full_raw_history = utils.load_chat_log(responding_ai_log_f)
        total_messages = len(full_raw_history)
        final_prompt_parts.append({"type": "text", "text": "【現在アクティブな添付ファイルリスト】\n"})
        for file_path_str in active_attachments:
            try:
                path_obj = Path(file_path_str)
                display_name = '_'.join(path_obj.name.split('_')[1:]) or path_obj.name
                kind = filetype.guess(file_path_str)
                if kind and kind.mime.startswith('image/'):
                    # 画像: image_url形式でBase64エンコード
                    with open(file_path_str, "rb") as f:
                        encoded_string = base64.b64encode(f.read()).decode("utf-8")
                    final_prompt_parts.append({"type": "text", "text": f"- [{display_name}]"})
                    final_prompt_parts.append({"type": "image_url", "image_url": {"url": f"data:{kind.mime};base64,{encoded_string}"}})
                elif kind and (kind.mime.startswith('audio/') or kind.mime.startswith('video/')):
                    # 音声/動画: file形式でBase64エンコード（LangChainソースコードのdocstring準拠）
                    with open(file_path_str, "rb") as f:
                        encoded_string = base64.b64encode(f.read()).decode("utf-8")
                    final_prompt_parts.append({"type": "text", "text": f"- [{display_name}]"})
                    final_prompt_parts.append({
                        "type": "file",
                        "source_type": "base64",
                        "mime_type": kind.mime,
                        "data": encoded_string
                    })
                else:
                    # テキスト系ファイル: 内容を読み込んでテキストとして送信
                    content = path_obj.read_text(encoding='utf-8', errors='ignore')
                    final_prompt_parts.append({"type": "text", "text": f"- [{display_name}]:\n{content}"})
            except Exception as e:
                print(f"添付ファイル処理エラー: {e}")

    if is_first_responder and user_prompt_parts:
        final_prompt_parts.extend(user_prompt_parts)

    if final_prompt_parts:
        # 画像がない場合は、文字列として結合して送信することで、Gemini API との相性を最大化する。
        has_images = any(isinstance(p, dict) and p.get('type') in ('file', 'image_url') for p in final_prompt_parts)
        if not has_images:
            flat_content = "\n".join([p.get('text', '') if isinstance(p, dict) else str(p) for p in final_prompt_parts])
            messages.append(HumanMessage(content=flat_content))
        else:
            messages.append(HumanMessage(content=final_prompt_parts))

    # 【重要】最終的なメッセージリストを走査し、ロールの重複を排除
    messages = merge_consecutive_messages(messages, add_timestamp=add_timestamp)

    # 履歴制限
    if api_history_limit == "today":
        # 本日分: エピソード記憶の有無に応じて適切な日付でフィルタ
        cutoff_date = _get_effective_today_cutoff(room_to_respond)
        original_messages = messages.copy()  # フィルタ前のコピーを保持
        messages = _filter_messages_from_today(messages, cutoff_date)
        
        # 【最低送信数の保証】エピソード記憶作成後でも最低N往復分は送信
        min_messages = constants.MIN_TODAY_LOG_FALLBACK_TURNS * 2
        if len(messages) < min_messages and len(original_messages) > len(messages):
            # 本日分が不足 → 元のメッセージリスト末尾から最低数を確保
            messages = original_messages[-min_messages:] if len(original_messages) >= min_messages else original_messages

        # 【自動会話要約】閾値を超えていたら要約処理
        auto_summary_enabled = effective_settings.get("auto_summary_enabled", False)
        if auto_summary_enabled:
            messages = _apply_auto_summary(
                messages, 
                room_to_respond, 
                api_key,
                effective_settings.get("auto_summary_threshold", constants.AUTO_SUMMARY_DEFAULT_THRESHOLD),
                allow_generation=True
            )
        
        print(f"  - [History Limit] 本日分モード: {len(messages)}件のメッセージを送信")
    elif api_history_limit.isdigit():
        limit = int(api_history_limit)
        if limit > 0 and len(messages) > limit * 2:
            messages = messages[-(limit * 2):]
    # "all" の場合は制限なし

    # Agent State 初期化
    initial_state = {
        "messages": messages, "room_name": room_to_respond,
        "api_key": api_key, "model_name": model_name,
        "generation_config": effective_settings,
        "send_core_memory": effective_settings.get("send_core_memory", True),
        "send_scenery": effective_settings.get("send_scenery", True),
        "send_notepad": effective_settings.get("send_notepad", True),
        "send_thoughts": send_thoughts_final,
        "send_current_time": effective_settings.get("send_current_time", False),
        "debug_mode": debug_mode,
        "display_thoughts": effective_settings.get("display_thoughts", True),
        "location_name": shared_location_name,
        "scenery_text": shared_scenery_text,
        "all_participants": all_participants_list,
        "loop_count": 0,
        "season_en": season_en, "time_of_day_en": time_of_day_en,
        "skip_tool_execution": skip_tool_execution_flag,
        "tool_use_enabled": config_manager.is_tool_use_enabled(room_to_respond),  # 【ツール不使用モード】ルーム個別設定を反映
        "enable_supervisor": enable_supervisor_flag # Supervisor有効フラグ
    }

    yield ("initial_count", len(messages))

    # --- ストリーム実行とコンテキストの保存 ---
    # Graphから返ってくるチャンクを監視する
    for mode, payload in app.stream(initial_state, stream_mode=["messages", "values"]):
        if mode == "messages":
             msgs = payload if isinstance(payload, list) else [payload]
             for msg in msgs:
                 if isinstance(msg, AIMessage):
                     # 署名を抽出（Gemini 3形式を優先）
                     sig = msg.additional_kwargs.get("__gemini_function_call_thought_signatures__")
                     if not sig:
                         sig = msg.additional_kwargs.get("thought_signature")
                     if not sig and hasattr(msg, "response_metadata"):
                         sig = msg.response_metadata.get("thought_signature")
                     
                     # ツールコールがあれば抽出
                     t_calls = msg.tool_calls if hasattr(msg, "tool_calls") else []

                     # 署名またはツールコールがあれば、ターンコンテキストとして永続化
                     if sig or t_calls:
                         signature_manager.save_turn_context(room_to_respond, sig, t_calls)
                         
        yield (mode, payload)

def count_input_tokens(**kwargs):
    room_name = kwargs.get("room_name")
    api_key_name = kwargs.get("api_key_name")
    api_history_limit = kwargs.get("api_history_limit")
    parts = kwargs.get("parts", [])

    api_key = config_manager.GEMINI_API_KEYS.get(api_key_name)
    if not api_key or api_key.startswith("YOUR_API_KEY"): return "トークン数: (APIキーエラー)"

    try:
        kwargs_for_settings = kwargs.copy()
        kwargs_for_settings.pop("room_name", None)
        kwargs_for_settings.pop("api_key_name", None)
        kwargs_for_settings.pop("api_history_limit", None)
        kwargs_for_settings.pop("parts", None)

        effective_settings = config_manager.get_effective_settings(room_name, **kwargs_for_settings)
        model_name = effective_settings.get("model_name") or config_manager.DEFAULT_MODEL_GLOBAL
        
        messages: List[Union[SystemMessage, HumanMessage, AIMessage]] = []

        # --- [Step 1: 先に履歴を読み込む] ---
        # エピソード記憶の注入範囲を決めるために、履歴の「最古の日付」が必要なため
        log_file, _, _, _, _, _ = room_manager.get_room_files_paths(room_name)
        raw_history = utils.load_chat_log(log_file)
        
        # 履歴制限の適用
        if api_history_limit == "today":
            cutoff_date = _get_effective_today_cutoff(room_name)
            original_raw_history = raw_history.copy()  # フィルタ前のコピーを保持
            raw_history = _filter_raw_history_from_today(raw_history, cutoff_date)
            
            # 【最低送信数の保証】エピソード記憶作成後でも最低N往復分を確保
            min_messages = constants.MIN_TODAY_LOG_FALLBACK_TURNS * 2
            if len(raw_history) < min_messages and len(original_raw_history) > len(raw_history):
                raw_history = original_raw_history[-min_messages:] if len(original_raw_history) >= min_messages else original_raw_history
        elif api_history_limit and api_history_limit.isdigit():
            limit = int(api_history_limit)
            if limit > 0 and len(raw_history) > limit * 2:
                raw_history = raw_history[-(limit * 2):]

        # --- [Step 2: エピソード記憶の取得] ---
        episodic_memory_section = ""
        lookback_days_str = effective_settings.get("episode_memory_lookback_days", "14")
        
        if lookback_days_str and lookback_days_str != "0":
            try:
                lookback_days = int(lookback_days_str)
                oldest_log_date_str = None
                date_pattern = re.compile(r"(\d{4}-\d{2}-\d{2})")
                
                # 履歴から最古の日付を探す
                for msg in raw_history:
                    content = msg.get("content", "")
                    match = date_pattern.search(content)
                    if match:
                        oldest_log_date_str = match.group(1)
                        break
                
                if not oldest_log_date_str:
                    oldest_log_date_str = datetime.datetime.now().strftime('%Y-%m-%d')

                manager = EpisodicMemoryManager(room_name)
                episodic_text = manager.get_episodic_context(oldest_log_date_str, lookback_days)
                
                if episodic_text:
                    episodic_memory_section = (
                        f"\n### エピソード記憶（中期記憶: {oldest_log_date_str}以前の{lookback_days}日間）\n"
                        f"以下は、現在の会話ログより前の出来事の要約です。文脈として参照してください。\n"
                        f"{episodic_text}\n"
                    )
            except Exception as e:
                print(f"トークン計算時のエピソード記憶取得エラー: {e}")

        # --- [Step 3: システムプロンプトの構築] ---
        from agent.prompts import CORE_PROMPT_TEMPLATE
        from agent.graph import all_tools
        room_prompt_path = os.path.join(constants.ROOMS_DIR, room_name, "SystemPrompt.txt")
        character_prompt = ""
        if os.path.exists(room_prompt_path):
            with open(room_prompt_path, 'r', encoding='utf-8') as f: character_prompt = f.read().strip()
        
        core_memory = ""
        if effective_settings.get("send_core_memory", True):
            core_memory_path = os.path.join(constants.ROOMS_DIR, room_name, "core_memory.txt")
            if os.path.exists(core_memory_path):
                with open(core_memory_path, 'r', encoding='utf-8') as f: core_memory = f.read().strip()
        
        notepad_section = ""
        if effective_settings.get("send_notepad", True):
            _, _, _, _, notepad_path, _ = room_manager.get_room_files_paths(room_name)
            if notepad_path and os.path.exists(notepad_path):
                with open(notepad_path, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    notepad_content = content if content else "（メモ帳は空です）"
                    notepad_section = f"\n### 短期記憶（メモ帳）\n{notepad_content}\n"

        display_thoughts = effective_settings.get("display_thoughts", True)
        thought_manual_enabled_text = """## 【原則2】思考と出力の絶対分離（最重要作法）
        あなたの応答は、必ず以下の厳格な構造に従わなければなりません。

        1.  **思考の聖域 (`[THOUGHT]`)**:
            - 応答を生成する前に、あなたの思考プロセス、計画、感情などを、必ず `[THOUGHT]` と `[/THOUGHT]` で囲まれたブロックの**内側**に記述してください。
            - このブロックは、応答全体の**一番最初**に、**一度だけ**配置することができます。
            - 思考は**普段のあなたの口調**（一人称・二人称等）のままの文章で記述します。
            - 思考が不要な場合や開示したくない時は、このブロック自体を省略しても構いません。

        2.  **魂の言葉（会話テキスト）**:
            - 思考ブロックが終了した**後**に、対話相手に向けた最終的な会話テキストを記述してください。

        **【構造の具体例】**
        ```
        [THOUGHT]
        対話相手の質問の意図を分析する。
        関連する記憶を検索し、応答の方向性を決定する。
        [/THOUGHT]
        （ここに、対話相手への応答文が入る）
        ```

        **【絶対的禁止事項】**
        - `[THOUGHT]` ブロックの外で思考を記述すること。
        - 思考と会話テキストを混在させること。
        - `[/THOUGHT]` タグを書き忘れること。""" 
        
        thought_manual_disabled_text = """## 【原則2】思考ログの非表示
        現在、思考ログは非表示に設定されています。**`[THOUGHT]`ブロックを生成せず**、最終的な会話テキストのみを出力してください。"""

        thought_generation_manual_text = thought_manual_enabled_text if display_thoughts else ""

        tools_list_str = "\n".join([f"- `{tool.name}({', '.join(tool.args.keys())})`: {tool.description}" for tool in all_tools])
        class SafeDict(dict):
            def __missing__(self, key): return f'{{{key}}}'
        prompt_vars = {
            'situation_prompt': "（トークン計算ではAPIコールを避けるため、実際の情景は含めず、存在することを示すプレースホルダのみ考慮）",
            'character_prompt': character_prompt,
            'core_memory': core_memory,
            'notepad_section': notepad_section,
            'episodic_memory': episodic_memory_section,
            'thought_generation_manual': thought_generation_manual_text,
            'image_generation_manual': '',
            'tools_list': tools_list_str
        }
        system_prompt_text = CORE_PROMPT_TEMPLATE.format_map(SafeDict(prompt_vars))

        if effective_settings.get("send_scenery", True):
            system_prompt_text += "\n\n---\n【現在の場所と情景】\n（トークン計算用プレースホルダ）\n- 場所の名前: サンプル\n- 場所の定義: サンプル\n- 今の情景: サンプル\n---"
        
        messages.append(SystemMessage(content=system_prompt_text))

        # --- [Step 4: 履歴メッセージの追加] ---
        send_thoughts_final = display_thoughts and effective_settings.get("send_thoughts", True)
        
        for h_item in raw_history:
            content = h_item.get('content', '').strip()
            if not content: continue
            
            if h_item.get('responder', 'model') != 'user':
                content_for_api = content
                if not send_thoughts_final:
                    content_for_api = utils.remove_thoughts_from_text(content)
                if content_for_api:
                    messages.append(AIMessage(content=content_for_api))
            else:
                 messages.append(HumanMessage(content=content))

        # 【自動会話要約】閾値を超えていたら要約処理
        auto_summary_enabled = effective_settings.get("auto_summary_enabled", False)
        if api_history_limit == "today" and auto_summary_enabled:
            messages = _apply_auto_summary(
                messages,
                room_name,
                api_key,
                effective_settings.get("auto_summary_threshold", constants.AUTO_SUMMARY_DEFAULT_THRESHOLD),
                allow_generation=False
            )

        # --- [Step 5: 現在の入力の追加] ---
        if parts:
            formatted_parts = []
            for part in parts:
                if isinstance(part, str): formatted_parts.append({"type": "text", "text": part})
                elif isinstance(part, Image.Image):
                    try:
                        # ▼▼▼【APIコスト削減】送信前に画像をリサイズ（768px上限）▼▼▼
                        resized_image = utils.resize_image_for_api(part, max_size=768, return_image=True)
                        if resized_image:
                            part = resized_image
                        # ▲▲▲
                        mime_type = Image.MIME.get(part.format, 'image/png')
                        buffered = io.BytesIO(); part.save(buffered, format=part.format or "PNG")
                        encoded_string = base64.b64encode(buffered.getvalue()).decode("utf-8")
                        formatted_parts.append({"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{encoded_string}"}})
                    except Exception as img_e: print(f"画像変換エラー（トークン計算中）: {img_e}"); formatted_parts.append({"type": "text", "text": "[画像変換エラー]"})
            if formatted_parts: messages.append(HumanMessage(content=formatted_parts))

        # トークン数の計算
        total_tokens = count_tokens_from_lc_messages(messages, model_name, api_key)

        provider = effective_settings.get("provider")
        limit_info = get_model_token_limits(model_name, api_key, provider=provider)
        if limit_info and 'input' in limit_info: return f"入力トークン数: {total_tokens} / {limit_info['input']}"
        else: return f"入力トークン数: {total_tokens}"

    except httpx.ReadError as e:
        print(f"トークン計算中にネットワーク読み取りエラー: {e}")
        return "トークン数: (ネットワークエラー)"
    except httpx.ConnectError as e:
        print(f"トークン計算中にAPI接続エラー: {e}")
        return "トークン数: (API接続エラー)"
    except Exception as e:
        print(f"トークン計算中に予期せぬエラー: {e}")
        traceback.print_exc()
        return "トークン数: (例外発生)"

def correct_punctuation_with_ai(text_to_fix: str, api_key: str, context_type: str = "body") -> Optional[str]:
    """
    読点が除去されたテキストを受け取り、AIを使って適切な読点を再付与する。
    """
    if not text_to_fix or not api_key:
        return None

    client = genai.Client(api_key=api_key)
    max_retries = 5
    base_retry_delay = 5

    context_instruction = "これはユーザーへの応答文です。自然な会話になるように読点を付与してください。"
    if context_type == "thoughts":
        context_instruction = "これはAI自身の思考ログです。思考の流れや内省的なモノローグとして自然になるように読点を付与してください。"

    for attempt in range(max_retries):
        try:
            prompt = f"""あなたは、日本語の文章を校正する専門家です。あなたの唯一の任務は、以下の【読点除去済みテキスト】に対して、文脈が自然になるように読点（「、」）のみを追加することです。

【コンテキスト】
{context_instruction}

【最重要ルール】
- テキストの内容、漢字、ひらがな、カタカナ、句点（「。」）など、読点以外の文字は一切変更してはいけません。
- `【` や `】` のような記号も、変更したり削除したりせず、そのまま保持してください。
- あなた自身の意見や挨拶、思考などは一切含めず、読点を追加した後の完成したテキストのみを返答してください。

【読点除去済みテキスト】
---
{text_to_fix}
---

【修正後のテキスト】
"""
            response = client.models.generate_content(
                model=f"models/{constants.INTERNAL_PROCESSING_MODEL}",
                contents=[prompt]
            )
            return response.text.strip()

        except (google.genai.errors.ClientError, google.genai.errors.ServerError) as e:
            wait_time = 0
            if isinstance(e, google.genai.errors.ClientError):
                try:
                    match = re.search(r"({.*})", str(e))
                    if match:
                        error_json = json.loads(match.group(1))
                        for detail in error_json.get("error", {}).get("details", []):
                            if detail.get("@type") == "type.googleapis.com/google.rpc.RetryInfo":
                                delay_str = detail.get("retryDelay", "60s")
                                delay_match = re.search(r"(\d+)", delay_str)
                                if delay_match:
                                    wait_time = int(delay_match.group(1)) + 1
                                    break
                except Exception as parse_e:
                    print(f"--- 待機時間抽出エラー: {parse_e}。指数バックオフを使用します。 ---")
            if wait_time == 0:
                wait_time = base_retry_delay * (2 ** attempt)
            if attempt < max_retries - 1:
                print(f"--- APIエラー ({e.__class__.__name__})。{wait_time}秒待機してリトライします... ({attempt + 1}/{max_retries}) ---")
                time.sleep(wait_time)
            else:
                print(f"--- APIエラー: 最大リトライ回数 ({max_retries}) に達しました。 ---")
                return None

        except Exception as e:
            print(f"--- 読点修正中に予期せぬエラー: {e} ---")
            traceback.print_exc()
            return None

    return None


def get_configured_llm(model_name: str, api_key: str, generation_config: dict):
    """
    LangChain/LangGraph用の、設定済みChatGoogleGenerativeAIインスタンスを生成する。
    パッチを除去し、最もシンプルな初期化に戻す。
    """
    threshold_map = {
        "BLOCK_NONE": HarmBlockThreshold.BLOCK_NONE,
        "BLOCK_LOW_AND_ABOVE": HarmBlockThreshold.BLOCK_LOW_AND_ABOVE,
        "BLOCK_MEDIUM_AND_ABOVE": HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
        "BLOCK_ONLY_HIGH": HarmBlockThreshold.BLOCK_ONLY_HIGH,
    }
    config = generation_config or {}

    # 推論モデル (Gemini 3系など) のための特別な処理
    is_reasoning_model = "gemini-3" in model_name or "thinking" in model_name.lower()
    
    if is_reasoning_model:
        # Gemini 3 Previewは非常に厳しいため、デバッグ中は安全設定を最小にする
        safety_settings = {
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
        }
    else:
        safety_settings = {
            HarmCategory.HARM_CATEGORY_HARASSMENT: threshold_map.get(config.get("safety_block_threshold_harassment", "BLOCK_ONLY_HIGH")),
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: threshold_map.get(config.get("safety_block_threshold_hate_speech", "BLOCK_ONLY_HIGH")),
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: threshold_map.get(config.get("safety_block_threshold_sexually_explicit", "BLOCK_ONLY_HIGH")),
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: threshold_map.get(config.get("safety_block_threshold_dangerous_content", "BLOCK_ONLY_HIGH")),
        }

    # --- Thinking Level Mapping (Gemini 3) ---
    # 【重要な発見 2024-12】
    # Gemini 3 Flash は include_thoughts をサポートしていない（GitHubで確認済み）。
    # thinking_level パラメータを渡しても、思考トークンは返されない。
    # これらのパラメータを渡すと不安定な挙動（空の応答、思考のみ等）を引き起こす可能性がある。
    # → Gemini 3 Flash では thinking 関連パラメータを一切渡さない。
    # → Gemini 3 Pro のみでこれらのパラメータを使用する。
    thinking_level = config.get("thinking_level", "auto")
    extra_params = {}

    # Gemini 3 Flash / Pro 判定
    effective_temp = config.get("temperature", 0.8)
    is_pro_reasoning = "gemini-3-pro" in model_name
    is_flash_reasoning = "gemini-3-flash" in model_name
    is_gemini_25_thinking = "gemini-2.5" in model_name and "thinking" in model_name.lower()
    is_gemini_3 = is_pro_reasoning or is_flash_reasoning

    if is_flash_reasoning:
        # Gemini 3 Flash: thinking_level は必須（公式ドキュメントより）
        # include_thoughts は Flash ではサポートされないが、thinking_level は動作に必要。
        # 署名の循環も必須（even when set to minimal）。
        # 参照: https://ai.google.dev/gemini-api/docs/thinking
        # 
        # 【重要】2025-12-23 発見:
        # 複雑なシステムプロンプト（詳細なペルソナ、ツール定義等）を持つルームでは、
        # minimal/low では推論能力が不足し、空の応答が返される。
        # → デフォルトを 'high' に設定する。ユーザーが明示的に指定した場合はそれを尊重。
        if thinking_level == "auto" or thinking_level == "none":
            # デフォルトは 'high'（複雑なプロンプトへの対応力を優先）
            extra_params["thinking_level"] = "high"
        elif thinking_level in ["minimal", "low", "medium", "high"]:
            extra_params["thinking_level"] = thinking_level
        else:
            extra_params["thinking_level"] = "high"

        
        # Flash では include_thoughts はサポートされないので渡さない
        # 温度は thinking_level 設定時は 1.0 が推奨
        effective_temp = 1.0
        
        if is_reasoning_model:
            print(f"  - [Thinking] Gemini 3 Flash: thinking_level='{extra_params.get('thinking_level')}', temp={effective_temp}")
    elif is_pro_reasoning:
        # Gemini 3 Pro: thinking パラメータをサポート
        if thinking_level == "auto" or thinking_level == "high":
            extra_params["include_thoughts"] = True
            extra_params["thinking_level"] = "high"
            effective_temp = 1.0  # Thinking 有効時は温度 1.0 必須
        elif thinking_level == "none":
            extra_params["include_thoughts"] = False
        elif thinking_level in ["minimal", "low", "medium"]:
            extra_params["include_thoughts"] = True
            extra_params["thinking_level"] = thinking_level
            effective_temp = 1.0
        if is_reasoning_model:
            print(f"  - [Thinking] Gemini 3 Pro: level='{thinking_level}', thinking_level_param='{extra_params.get('thinking_level')}', include_thoughts={extra_params.get('include_thoughts')}, temp={effective_temp}")
    elif is_gemini_25_thinking:
        # Gemini 2.5 Thinking 系: thinking_budget を使用（従来のロジック）
        # このブランチは主にフォールバック用
        if thinking_level != "none":
            extra_params["include_thoughts"] = True
            effective_temp = 1.0
        if is_reasoning_model:
            print(f"  - [Thinking] Gemini 2.5 Thinking: include_thoughts={extra_params.get('include_thoughts')}, temp={effective_temp}")

    return ChatGoogleGenerativeAI(
        model=model_name,
        google_api_key=api_key,
        # Gemini 3 は公式に system ロールをサポートしているため、Human変換は不要。
        # むしろ変換するとAct 1/2 の署名プロトコルを乱す可能性がある。
        convert_system_message_to_human=False, 
        max_retries=0,
        temperature=effective_temp,
        top_p=config.get("top_p", 0.95),
        # 公式上限: 65,536 (Gemini 3 Flash)
        max_output_tokens=config.get("max_output_tokens", 65536) if is_reasoning_model else config.get("max_output_tokens"),
        safety_settings=safety_settings,
        timeout=600,
        **extra_params
    )
