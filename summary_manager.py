# summary_manager.py
"""
本日の会話要約を管理するモジュール。
APIコスト削減のため、長い会話履歴を圧縮して送信する。
"""

import os
import json
import datetime
import re
import time
import traceback
from typing import Optional, Dict, List
import constants


def get_summary_file_path(room_name: str) -> str:
    """要約ファイルのパスを返す"""
    return os.path.join(constants.ROOMS_DIR, room_name, "today_summary.json")


def load_today_summary(room_name: str) -> Optional[Dict]:
    """
    本日の要約を読み込む。
    日付が変わっている場合はNoneを返す（リセット）。
    """
    path = get_summary_file_path(room_name)
    if not os.path.exists(path):
        return None
    
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # 日付チェック（今日でなければリセット）
        today_str = datetime.datetime.now().strftime('%Y-%m-%d')
        if data.get("date") != today_str:
            return None
        
        return data
    except Exception as e:
        print(f"要約ファイル読み込みエラー: {e}")
        return None


def save_today_summary(room_name: str, summary_text: str, 
                        chars_summarized: int, arousal: float = 0.0) -> bool:
    """
    本日の要約を保存する。
    
    Args:
        room_name: ルーム名
        summary_text: 要約テキスト
        chars_summarized: 要約対象の文字数
        arousal: 感情的重要度スコア（0.0〜1.0）
    """
    path = get_summary_file_path(room_name)
    today_str = datetime.datetime.now().strftime('%Y-%m-%d')
    now_str = datetime.datetime.now().strftime('%H:%M:%S')
    
    data = {
        "date": today_str,
        "last_updated": now_str,
        "summary": summary_text,
        "chars_summarized": chars_summarized,
        "arousal": arousal  # 感情的重要度スコア
    }
    
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"要約ファイル保存エラー: {e}")
        return False


def clear_today_summary(room_name: str) -> bool:
    """要約ファイルを削除する（睡眠時処理後に呼び出し）"""
    path = get_summary_file_path(room_name)
    if os.path.exists(path):
        try:
            os.remove(path)
            print(f"  - [Summary Manager] 要約ファイルをクリア: {room_name}")
            return True
        except Exception as e:
            print(f"要約ファイル削除エラー: {e}")
    return False


def generate_summary(
    messages_to_summarize: List[Dict],
    existing_summary: Optional[str],
    room_name: str,
    api_key: str
) -> Optional[str]:
    """
    会話メッセージを要約する。
    既存の要約がある場合は、それと新しいメッセージを統合して再要約。
    """
    import room_manager
    from llm_factory import LLMFactory
    import config_manager
    
    # メッセージをテキストに変換
    conversation_text = ""
    for msg in messages_to_summarize:
        role = msg.get("role", "")
        responder = msg.get("responder", "")
        content = msg.get("content", "")
        
        if role == "USER":
            conversation_text += f"ユーザー: {content}\n\n"
        else:
            conversation_text += f"{responder}: {content}\n\n"
    
    # 要約対象がなければスキップ
    if not conversation_text.strip() and not existing_summary:
        return None
    
    # キャラクター名を取得
    room_config = room_manager.get_room_config(room_name)
    character_name = room_config.get("room_name", room_name) if room_config else room_name
    
    # 既存の要約があれば統合
    context_section = ""
    if existing_summary:
        context_section = f"""【これまでの要約】
{existing_summary}

【上記以降の新しい会話】
"""
    
    prompt = f"""あなたはAIアシスタントの会話記録を要約するタスクを担当しています。

【指示】
以下の会話ログを、AIペルソナ「{character_name}」の視点で要約してください。

【要約ルール】
- 三人称で記述すること（「{character_name}は〜」）
- 主語には「ユーザー」「AI」という抽象的な言葉ではなく、**ログ内で使われている固有名詞（名前、呼び名、二人称など）**をそのまま使用すること
- 重要なトピック、感情の変化、約束事、共有された情報を含めること
- 相手との関係性の変化があれば記録すること
- 2000〜3000トークン程度に収めること
- 前置き、説明、挨拶は一切不要。純粋な要約テキストのみを出力すること

{context_section}【会話ログ】
{conversation_text}

【要約】"""

    try:
        # 【マルチモデル対応】内部モデル設定（混合編成）に基づいてモデルを取得
        effective_settings = config_manager.get_effective_settings(room_name)
        llm = LLMFactory.create_chat_model(
            api_key=api_key,
            generation_config=effective_settings,
            internal_role="summarization",
            room_name=room_name
        )
        
        # invoke で呼び出し
        response = llm.invoke(prompt)
        return response.content.strip() if response and response.content else None
        
    except Exception as e:
        print(f"要約生成エラー: {e}")
        traceback.print_exc()
        return None
    
    return None


def calculate_text_length(messages: List[Dict]) -> int:
    """メッセージリストの総文字数を計算"""
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total += len(content)
    return total
