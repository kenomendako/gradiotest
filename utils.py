# -*- coding: utf-8 -*-
import os
import re
import traceback
from typing import List, Dict, Optional, Tuple # Added for type hints

# --- ユーティリティ関数 ---

def load_chat_log(file_path: str, character_name: str) -> List[Dict[str, str]]:
    """
    指定されたファイルパスからチャットログを読み込み、メッセージのリストとして返します。
    各メッセージは {'role': 'user'/'model', 'content': 'text'} の形式の辞書です。

    Args:
        file_path (str): ログファイルのパス。
        character_name (str): AIキャラクターの名前（ログヘッダーの解析に使用）。

    Returns:
        List[Dict[str, str]]: メッセージのリスト。エラー時は空のリストを返します。
    """
    messages: List[Dict[str, str]] = []
    if not character_name:
        print("エラー: load_chat_log - character_name が指定されていません。")
        return messages
    if not file_path:
        print("エラー: load_chat_log - file_path が指定されていません。")
        return messages
    if not os.path.exists(file_path):
        # print(f"情報: ログファイル '{file_path}' は存在しません。空の履歴を返します。") # 通常は新規作成などで呼ばれる
        return messages

    # ヘッダー定義:
    # AIの応答ヘッダー (例: "## <キャラクター名>:")
    ai_header = f"## {character_name}:"
    # システムアラームヘッダー (例: "## システム(アラーム):") - これもユーザー入力として扱う
    alarm_header = "## システム(アラーム):"
    # その他の "## <名前>:" 形式のヘッダーはユーザー入力として扱われる

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"エラー: ログファイル '{file_path}' が見つかりません。")
        return messages
    except IOError as e:
        print(f"エラー: ログファイル '{file_path}' の読み込み中にIOエラーが発生しました: {e}")
        traceback.print_exc()
        return messages
    except Exception as e: # その他の予期せぬエラー
        print(f"エラー: ログファイル '{file_path}' の読み込み中に予期せぬエラーが発生しました: {e}")
        traceback.print_exc()
        return messages

    current_role: Optional[str] = None
    current_text_lines: List[str] = []

    for line in lines:
        stripped_line = line.strip()
        # ヘッダー行の判定 (例: "## User:", "## MyCharName:", "## システム(アラーム):")
        if stripped_line.startswith("## ") and stripped_line.endswith(":"):
            if current_role and current_text_lines: # 前のブロックを確定
                messages.append({"role": current_role, "content": "\n".join(current_text_lines).strip()})

            current_text_lines = [] # 新しいブロックのためにリセット
            if stripped_line == ai_header:
                current_role = "model"
            elif stripped_line == alarm_header: # システムアラームもユーザー入力として扱う
                current_role = "user"
            else: # AIヘッダー、アラームヘッダー以外はユーザーヘッダーとみなす
                current_role = "user"
        elif current_role: # ヘッダー行ではなく、かつロールが設定されていれば本文とみなす
            # rstrip('\n') は不要、どうせ join で再結合するため。strip() は最終的な content で行う。
            current_text_lines.append(line.rstrip('\n'))

    # ファイル末尾に残っている最後のブロックを処理
    if current_role and current_text_lines:
        messages.append({"role": current_role, "content": "\n".join(current_text_lines).strip()})

    return messages


def format_response_for_display(response_text: Optional[str]) -> str:
    """
    AIの応答テキストをGradio表示用にフォーマットします。
    "【Thoughts】...【/Thoughts】"部分を抽出し、HTMLで装飾して本文と分離します。

    Args:
        response_text (Optional[str]): AIからの応答テキスト。

    Returns:
        str: Gradioチャットボット表示用にフォーマットされたHTML文字列。
    """
    if not response_text:
        return ""

    # Thoughtsの正規表現パターン (大文字・小文字を区別せず、複数行にまたがる内容もキャプチャ)
    thoughts_pattern = re.compile(r"【Thoughts】(.*?)【/Thoughts】", re.DOTALL | re.IGNORECASE)
    match = thoughts_pattern.search(response_text)

    if match:
        thoughts_content = match.group(1).strip()
        # HTMLエスケープはGradioのMarkdownコンポーネントがある程度行うが、
        # <pre><code> 内では特殊文字がそのまま表示されることを期待。
        # thoughts_html = thoughts_content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") # 基本的なエスケープ

        # GradioのチャットボットはMarkdownをサポート。インラインスタイルよりクラスベースが良いが、ここでは既存を踏襲。
        # CSSはlog2gemini.pyのcustom_cssで定義されていることを前提とする。
        thought_html_block = (
            f"<div class='thoughts'>"
            f"<pre><code>{thoughts_content}</code></pre>" # pre/codeで整形済みテキストとして表示
            f"</div>"
        )

        # Thoughts部分を応答テキストから除去
        main_response_text = thoughts_pattern.sub("", response_text).strip()

        # Thoughtsブロックと本文を結合して返す (間に空行を挟むことが多い)
        if main_response_text:
            return f"{thought_html_block}\n\n{main_response_text}"
        else: # Thoughtsのみで本文がない場合
            return thought_html_block
    else:
        # Thoughtsがない場合は、元のテキストをそのまま返す (GradioがMarkdownとして解釈)
        return response_text.strip()


def format_history_for_gradio(messages: List[Dict[str, str]]) -> List[Tuple[Optional[str], Optional[str]]]:
    """
    Converts a list of message dictionaries (from load_chat_log) into Gradio's
    chatbot history format, which is a list of (user_message, bot_message) tuples.
    It handles formatting for attachments and accumulates consecutive user messages
    if necessary (though typical log format is alternating).

    Args:
        messages (List[Dict[str, str]]): List of message dictionaries.

    Returns:
        List[Tuple[Optional[str], Optional[str]]]: History formatted for Gradio chatbot.
    """
    gradio_history: List[Tuple[Optional[str], Optional[str]]] = []
    user_message_accumulator: Optional[str] = None

    for msg in messages:
        role = msg.get("role")
        content = msg.get("content", "").strip() # Ensure content is stripped initially

        if not content: # Skip empty messages
            continue

        if role == "user":
            # Current message is from the user.
            # If there was a previously accumulated user message, it means it didn't get paired
            # with a model response (e.g., two user messages in a row, or user message at end of log).
            # We add it to history with no model response.
            if user_message_accumulator is not None:
                gradio_history.append((user_message_accumulator, None))

            # Process current user message for display
            display_text_for_user_turn = content

            # Regex for general file_attachment: [file_attachment:path;filename;mime]timestamp_info
            # Group 1: Full tag e.g., [file_attachment:path;filename.png;image/png]
            # Group 2: Path (captured but not directly used in display text)
            # Group 3: Original filename
            # Group 4: Mime type
            # Group 5: Any trailing characters including potential timestamp (e.g., "\n2023-01-01...")
            file_attach_pattern = r"(\[file_attachment:(.*?);(.*?);(.*?)\])([\s\S]*)"
            file_attach_match = re.match(file_attach_pattern, content)
            
            # Regex for text file placeholder: [添付テキストファイル:filename.txt]timestamp_info
            # Group 1: Full tag e.g., [添付テキストファイル:notes.txt]
            # Group 2: Original filename
            # Group 3: Any trailing characters including potential timestamp
            text_file_pattern = r"(\[添付テキストファイル:(.*?)\])([\s\S]*)"
            text_file_match = re.match(text_file_pattern, content)

            timestamp_str = "" # Holds the extracted timestamp if any

            if file_attach_match:
                original_filename = file_attach_match.group(3)
                mime_type = file_attach_match.group(4)
                timestamp_str = file_attach_match.group(5).strip() # Get timestamp, strip surrounding whitespace

                prefix = "添付ファイル:"
                if mime_type.startswith("image/"): prefix = "画像:"
                elif mime_type == "application/pdf": prefix = "PDF:"
                elif mime_type.startswith("audio/"): prefix = "音声:"
                elif mime_type.startswith("video/"): prefix = "動画:"
                
                display_text_for_user_turn = f"{prefix} {original_filename}"
            
            elif text_file_match:
                original_filename = text_file_match.group(2)
                timestamp_str = text_file_match.group(3).strip() # Get timestamp
                display_text_for_user_turn = f"添付テキスト: {original_filename}"
            
            # Append timestamp if it exists and is not just whitespace
            if timestamp_str:
                # Check if original content had a newline before timestamp, to preserve formatting
                original_content_for_ts_check = file_attach_match.group(0) if file_attach_match else (text_file_match.group(0) if text_file_match else "")
                original_timestamp_part = file_attach_match.group(5) if file_attach_match else (text_file_match.group(3) if text_file_match else "")

                if original_timestamp_part.startswith(('\n', '\r')):
                    display_text_for_user_turn += f"\n{timestamp_str}"
                else:
                    display_text_for_user_turn += f" ({timestamp_str})" if not display_text_for_user_turn.endswith(timestamp_str) else ""


            user_message_accumulator = display_text_for_user_turn

        elif role == "model":
            # Current message is from the model.
            # Format it for display (e.g., extracting thoughts).
            formatted_model_response = format_response_for_display(content)

            if user_message_accumulator is not None:
                # Pair the accumulated user message with this model response.
                gradio_history.append((user_message_accumulator, formatted_model_response))
                user_message_accumulator = None # Reset for the next user message.
            else:
                # This means a model message appeared without a preceding user message in this batch.
                # This can happen if the log starts with a model message or has errors.
                # Add it as a model response with no corresponding user message for this turn.
                gradio_history.append((None, formatted_model_response))

    # After the loop, if there's an uncommitted user message (i.e., the log ended with a user message),
    # add it to the history with no model response.
    if user_message_accumulator is not None:
        gradio_history.append((user_message_accumulator, None))

    return gradio_history


def save_message_to_log(log_file_path: str, header: str, text_content: str) -> None:
    """
    指定されたログファイルに、ヘッダーとテキスト内容を追記します。
    ファイル末尾が改行でない場合のみ、追記前に改行を挿入します。

    Args:
        log_file_path (str): ログファイルのパス。
        header (str): メッセージのヘッダー (例: "## User:", "## MyCharName:").
        text_content (str): 保存するテキスト内容。
    """
    if not log_file_path:
        print("エラー: save_message_to_log - log_file_path が指定されていません。")
        return
    if not header:
        print("エラー: save_message_to_log - header が指定されていません。")
        return
    if not text_content or not text_content.strip():
        # print("情報: save_message_to_log - 保存するテキスト内容が空です。スキップします。") # ログレベルに応じて
        return

    try:
        # Determine if a preceding newline is needed.
        # This logic ensures that a new entry doesn't start on the same line as a previous one,
        # and also avoids creating excessive blank lines if the file already ends with newlines.
        needs_leading_newline = False
        if os.path.exists(log_file_path) and os.path.getsize(log_file_path) > 0:
            # File exists and is not empty, check if the last character is a newline.
            try:
                with open(log_file_path, "rb") as f: # Open in binary mode to read the last byte
                    f.seek(-1, os.SEEK_END) # Go to the last byte
                    if f.read(1) != b'\n':
                        needs_leading_newline = True # Last char is not a newline, so we need one.
            except IOError: # Handle potential errors during the check, e.g., if seek fails
                # If we can't check, assume a newline might be needed to be safe.
                # Or, decide to just append and risk an occasional joined line if this check fails.
                # For robustness, let's assume it might be needed if check fails.
                print(f"警告: ログファイル '{log_file_path}' の最終バイト確認中にエラー。念のため改行を挿入する可能性があります。")
                needs_leading_newline = True # Default to true if check fails

        # else: file doesn't exist or is empty, no preceding newline needed.

        with open(log_file_path, "a", encoding="utf-8") as f:
            if needs_leading_newline:
                f.write("\n") # Add a newline only if the file exists, is not empty, and doesn't end with one.

            # Write the header, two newlines, the stripped text, and two newlines for separation.
            f.write(f"{header}\n\n{text_content.strip()}\n\n")

    except IOError as e:
        print(f"エラー: ログファイル '{log_file_path}' への書き込み中にIOエラーが発生しました: {e}")
        traceback.print_exc()
    except Exception as e: # Catch any other unexpected errors during file write
        print(f"エラー: ログファイル '{log_file_path}' への書き込み中に予期せぬエラーが発生しました: {e}")
        traceback.print_exc()


def _get_user_header_from_log(log_file_path: str, ai_character_name: str) -> str:
    """
    ログファイルを読み込み、最後に見つかったユーザーヘッダーを返します。
    ユーザーヘッダーは "## <名前>:" の形式で、AIキャラクター名やシステムアラームヘッダーは除外されます。
    見つからない場合やエラー時はデフォルトの "## ユーザー:" を返します。

    Note:
        この関数はログ全体を読み込むため、非常に大きなログファイルではパフォーマンスに影響する可能性があります。
        ただし、ユーザーが最後に使用したヘッダーを取得するという目的のためには、現状この方法が確実です。

    Args:
        log_file_path (str): ログファイルのパス。
        ai_character_name (str): AIキャラクターの名前（この名前のヘッダーは無視するため）。

    Returns:
        str: 最後に見つかったユーザーヘッダー文字列。
    """
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
                # Check if the line looks like a header
                if stripped_line.startswith("## ") and stripped_line.endswith(":"):
                    # Exclude known non-user headers
                    if stripped_line != ai_response_header and stripped_line != system_alarm_header:
                        last_identified_user_header = stripped_line
        return last_identified_user_header
    except IOError as e:
        print(f"エラー: ユーザーヘッダー取得のためログファイル '{log_file_path}' 読み込み中にIOエラー: {e}")
        traceback.print_exc()
        return default_user_header # Return default on error
    except Exception as e:
        print(f"エラー: ユーザーヘッダー取得のためログファイル '{log_file_path}' 読み込み中に予期せぬエラー: {e}")
        traceback.print_exc()
        return default_user_header # Return default on unexpected error