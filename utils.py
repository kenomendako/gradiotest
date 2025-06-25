# utils.py の修正版コード

import os
import re
import traceback
import html
from typing import List, Dict, Optional, Tuple, Union
import gradio as gr
import character_manager

def load_chat_log(file_path: str, character_name: str) -> List[Dict[str, str]]:
    messages: List[Dict[str, str]] = []
    if not character_name:
        print("エラー: load_chat_log - character_name が指定されていません。")
        return messages
    if not file_path:
        print("エラー: load_chat_log - file_path が指定されていません。")
        return messages
    if not os.path.exists(file_path):
        return messages

    ai_header = f"## {character_name}:"
    alarm_header = "## システム(アラーム):"

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception as e:
        print(f"エラー: ログファイル '{file_path}' の読み込み中に予期せぬエラーが発生しました: {e}")
        traceback.print_exc()
        return messages

    current_role: Optional[str] = None
    current_text_lines: List[str] = []

    for line in lines:
        stripped_line = line.strip()
        if stripped_line.startswith("## ") and stripped_line.endswith(":"):
            if current_role and current_text_lines:
                messages.append({"role": current_role, "content": "\n".join(current_text_lines).strip()})
            current_text_lines = []
            if stripped_line == ai_header:
                current_role = "model"
            elif stripped_line == alarm_header:
                current_role = "user"
            else:
                current_role = "user"
        elif current_role:
            current_text_lines.append(line.rstrip('\n'))

    if current_role and current_text_lines:
        messages.append({"role": current_role, "content": "\n".join(current_text_lines).strip()})

    return messages

def format_response_for_display(response_text: Optional[str]) -> str:
    if not response_text: return ""
    thoughts_pattern = re.compile(r"【Thoughts】(.*?)【/Thoughts】", re.DOTALL | re.IGNORECASE)
    match = thoughts_pattern.search(response_text)
    if match:
        thoughts_content = match.group(1).strip()
        escaped_content = html.escape(thoughts_content)
        content_with_breaks = escaped_content.replace('\n', '<br>')
        thought_html_block = f"<div class='thoughts'>{content_with_breaks}</div>"
        main_response_text = thoughts_pattern.sub("", response_text).strip()
        return f"{thought_html_block}\n\n{main_response_text}" if main_response_text else thought_html_block
    else:
        return response_text.strip()

# utils.py に記載する、完全に新しい format_history_for_gradio 関数

def format_history_for_gradio(messages: List[Dict[str, str]]) -> List[Dict[str, Union[str, tuple, None]]]:
    """
    チャットログをGradio Chatbotが要求する `messages` 形式に正しく変換します。
    [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]
    """
    if not messages:
        return []

    gradio_history = []
    # 正規表現パターンを関数の外で一度だけコンパイル
    image_tag_pattern = re.compile(r"\[Generated Image: (.*?)\]")
    user_file_attach_pattern = re.compile(r"\[ファイル添付: (.*?)\]")

    for msg in messages:
        # LangGraphの'human'/'ai'/'model'をGradioの'user'/'assistant'に正規化
        role = "assistant" if str(msg.get("role")).lower() in ["model", "ai", "assistant"] else "user"
        content = msg.get("content", "")

        # contentがNoneや空文字列の場合はスキップせず、Gradioの仕様通りNoneとして追加
        if not content:
            gradio_history.append({"role": role, "content": None})
            continue

        # 思考ログはHTMLに変換して分離
        thoughts_pattern = re.compile(r"【Thoughts】(.*?)【/Thoughts】", re.DOTALL | re.IGNORECASE)
        thoughts_match = thoughts_pattern.search(content)
        if thoughts_match:
            thoughts_content = thoughts_match.group(1).strip()
            escaped_content = html.escape(thoughts_content)
            content_with_breaks = escaped_content.replace('\n', '<br>')
            thought_html_block = f"<div class='thoughts'>{content_with_breaks}</div>"

            # 思考ログを独立したメッセージとして追加
            gradio_history.append({"role": role, "content": thought_html_block})

            # 残りの本文を処理対象にする
            content = thoughts_pattern.sub("", content).strip()
            if not content:  # 思考ログのみで本文がない場合はここで終了
                continue

        # 画像やファイルの処理
        # AI応答の画像
        image_match = image_tag_pattern.search(content)
        # ユーザー添付のファイル
        file_match = user_file_attach_pattern.search(content)

        if image_match:
            image_path = image_match.group(1).strip()
            text_part = image_tag_pattern.sub("", content).strip()
            if text_part:
                gradio_history.append({"role": role, "content": text_part})
            if os.path.exists(image_path):
                gradio_history.append({"role": role, "content": (image_path, os.path.basename(image_path))})
            else:
                gradio_history.append({"role": role, "content": f"*[表示エラー: 画像 '{os.path.basename(image_path)}' が見つかりません]*"})

        elif file_match:
            filepath_str = file_match.group(1).strip()
            text_part = user_file_attach_pattern.sub("", content).strip()
            if text_part:
                gradio_history.append({"role": role, "content": text_part})

            filepaths = [p.strip() for p in filepath_str.split(',') if p.strip()]
            for filepath in filepaths:
                if os.path.exists(filepath):
                    gradio_history.append({"role": role, "content": (filepath, os.path.basename(filepath))})
                else:
                    gradio_history.append({"role": role, "content": f"*[表示エラー: ファイル '{os.path.basename(filepath)}' が見つかりません]*"})
        else:
            # 通常のテキストメッセージ
            gradio_history.append({"role": role, "content": content})

    return gradio_history

def save_message_to_log(log_file_path: str, header: str, text_content: str) -> None:
    if not log_file_path:
        print("エラー: save_message_to_log - log_file_path が指定されていません。")
        return
    if not header:
        print("エラー: save_message_to_log - header が指定されていません。")
        return
    if not text_content or not text_content.strip():
        return

    try:
        needs_leading_newline = False
        if os.path.exists(log_file_path) and os.path.getsize(log_file_path) > 0:
            try:
                with open(log_file_path, "rb") as f:
                    f.seek(-1, os.SEEK_END)
                    if f.read(1) != b'\n':
                        needs_leading_newline = True
            except IOError:
                print(f"警告: ログファイル '{log_file_path}' の最終バイト確認中にエラー。")
                needs_leading_newline = True

        with open(log_file_path, "a", encoding="utf-8") as f:
            if needs_leading_newline:
                f.write("\n")
            f.write(f"{header}\n\n{text_content.strip()}\n\n")

    except Exception as e:
        print(f"エラー: ログファイル '{log_file_path}' への書き込み中に予期せぬエラーが発生しました: {e}")
        traceback.print_exc()

def _get_user_header_from_log(log_file_path: str, ai_character_name: str) -> str:
    default_user_header = "## ユーザー:"
    ai_response_header = f"## {ai_character_name}:"
    system_alarm_header = "## システム(アラーム):"

    if not log_file_path or not os.path.exists(log_file_path):
        return default_user_header

    last_identified_user_header = default_user_header
    try:
        with open(log_file_path, "r", encoding="utf-8") as f:
            for line in f:
                stripped_line = line.strip()
                if stripped_line.startswith("## ") and stripped_line.endswith(":"):
                    if stripped_line != ai_response_header and stripped_line != system_alarm_header:
                        last_identified_user_header = stripped_line
        return last_identified_user_header
    except Exception as e:
        print(f"エラー: ユーザーヘッダー取得のためログファイル '{log_file_path}' 読み込み中に予期せぬエラー: {e}")
        traceback.print_exc()
        return default_user_header

def save_log_file(character_name: str, content: str) -> None:
    if not character_name:
        print("エラー: save_log_file - character_name が指定されていません。")
        return
    try:
        log_file_path, _, _, _ = character_manager.get_character_files_paths(character_name)
        if not log_file_path:
            print(f"エラー: save_log_file - キャラクター '{character_name}' のログファイルパスを取得できませんでした。")
            return
        with open(log_file_path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        print(f"エラー: ログファイル書き込み中に予期せぬエラーが発生しました (キャラクター: {character_name}): {e}")
        traceback.print_exc()

def convert_chat_log_to_langchain_format(chat_log: List[Dict[str, str]]) -> List[Union['HumanMessage', 'AIMessage']]:
    """
    Nexus Ark形式のチャットログリストをLangChainのMessageオブジェクトのリストに変換する。
    """
    from langchain_core.messages import HumanMessage, AIMessage # 関数内インポートで循環参照を避ける

    langchain_messages = []
    for message_data in chat_log:
        role = message_data.get("role")
        content = message_data.get("content", "")
        if role == "user":
            langchain_messages.append(HumanMessage(content=content))
        elif role == "model" or role == "assistant": # assistantもmodelとして扱う
            langchain_messages.append(AIMessage(content=content))
        # 他のロールは無視するか、エラー処理を追加するか検討
    return langchain_messages
