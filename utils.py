# -*- coding: utf-8 -*-
import os
import re
import traceback
from typing import List, Dict, Optional, Tuple, Union # Added for type hints
import gradio as gr

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


def format_history_for_gradio(messages: List[Dict[str, str]]) -> List[Tuple[Optional[str], Optional[Union[str, List[Union[str, Tuple[str, str]]]]]]]:
    """
    Converts a list of message dictionaries into Gradio's chatbot history format.
    This version correctly handles user attachments, AI thoughts, AI-generated images, and main text responses,
    while providing a consistent data structure to Gradio to prevent display errors.
    """
    gradio_history: List[Tuple[Optional[str], Optional[Union[str, List[Union[str, Tuple[str, str]]]]]]] = []
    user_message_accumulator: List[Union[str, Tuple[str, str]]] = [] # Changed to list to handle multiple user parts like text and file

    # 正規表現パターンの定義
    thoughts_pattern = re.compile(r"【Thoughts】(.*?)【/Thoughts】", re.DOTALL | re.IGNORECASE)
    # Consolidated pattern for various image-related log lines to be removed from main_text
    # Corrected regex to use standard non-capturing group for newlines/end of string
    gazo_related_pattern = re.compile(r"\[(画像生成に使用されたプロンプト|画像モデルからのテキスト|ERROR)\]:.*?(?:\n\n|$)", re.DOTALL)
    image_tag_pattern = re.compile(r"\[Generated Image: (.*?)\]")
    # Pattern for user file attachments (modified from user's example to match original log format more closely if necessary)
    # The user log format was "[ファイル添付: /tmp/gradio/d3b073a2565509de5260323e6a1f41f5610d607f/test.txt;test.txt;text/plain]"
    # The regex from user was r"\[ファイル添付: (.*?);(.*?);(.*?)\]" which seems correct.
    file_attach_pattern = re.compile(r"\[ファイル添付: (.*?);(.*?);(.*?)\]")


    def create_user_display_message(text: str) -> Union[str, Tuple[str, str]]:
        """Parses user log content for cleaner display. If it's a file, returns a tuple for Gradio, otherwise text."""
        # Attempt to match file attachment first
        file_match = file_attach_pattern.search(text)
        if file_match:
            filepath, original_filename, mime_type = file_match.group(1), file_match.group(2), file_match.group(3)
            # Check if the file exists; Gradio can take a (filepath, alt_text) tuple to display images/files.
            # For non-image files, alt_text can just be the filename.
            if os.path.exists(filepath):
                # Return as a tuple, which Gradio can use to make it a downloadable link or display if image
                return (filepath, original_filename)
            else:
                return f"添付ファイル: {original_filename} (ファイルが見つかりません)"

        # If no file attachment, return the text as is.
        # (Original code had more complex parsing for other user text, e.g. "添付テキスト: ...")
        # (This version simplifies to either file tuple or raw text for user messages based on provided final code)
        return text

    for msg in messages:
        role = msg.get("role")
        content = msg.get("content", "").strip()

        if not content:
            continue

        if role == "user":
            # If there's a pending model message (shouldn't happen if logs are ordered user/model, but good for robustness)
            # or if we are processing consecutive user messages, the previous user_message_accumulator should be flushed.
            # The user's provided code implies user_message_accumulator is for the *current* turn.
            # Let's stick to the logic: if user_message_accumulator already has content from a *previous* user message
            # that hasn't been committed to history with a model response, it means we have consecutive user messages.
            # The provided code snippet for user role:
            # if user_message_accumulator: # If there's a pending user message, flush it with no AI response
            #    gradio_history.append((user_message_accumulator if len(user_message_accumulator) > 1 else user_message_accumulator[0], None))
            #    user_message_accumulator = []
            # This logic seems to be for flushing *before* processing the current user message if the accumulator is from a *prior* turn.
            # However, `user_message_accumulator` is defined *outside* the loop, so it persists.
            # Let's refine this slightly: if `user_message_accumulator` is not empty when a new user message starts,
            # it means the previous user message didn't get paired with a model message.
            if user_message_accumulator: # If it's not empty, the previous turn was also a user message
                gradio_history.append((user_message_accumulator[0] if len(user_message_accumulator) == 1 else user_message_accumulator, None))
                user_message_accumulator = []


            user_display_part = create_user_display_message(content)
            user_message_accumulator.append(user_display_part) # Append current user message part

        elif role == "model":
            model_response_parts: List[Union[str, Tuple[str, str]]] = []
            main_text = content # Start with the full content

            # 1. Thoughts
            thought_match = thoughts_pattern.search(main_text)
            if thought_match:
                thoughts_content = thought_match.group(1).strip()
                if thoughts_content:
                    thought_html_block = f"<div class='thoughts'><pre><code>{thoughts_content}</code></pre></div>"
                    model_response_parts.append(thought_html_block)
                main_text = thoughts_pattern.sub("", main_text).strip()

            # 2. Generated Image
            image_match = image_tag_pattern.search(main_text)
            if image_match:
                image_path = image_match.group(1).strip()
                if os.path.exists(image_path):
                    model_response_parts.append((image_path, os.path.basename(image_path)))
                else:
                    model_response_parts.append(f"*[表示エラー: 画像ファイルが見つかりません ({os.path.basename(image_path)})]*")
                main_text = image_tag_pattern.sub("", main_text).strip()

            # 3. Remove other image-related logs from main_text
            main_text = gazo_related_pattern.sub("", main_text).strip()

            # 4. Add remaining main_text
            if main_text: # If there's any text left after stripping tags
                model_response_parts.append(main_text)

            # 5. Determine final model output
            # Always pass a list to Gradio, or None if the list is empty.
            final_model_output = model_response_parts if model_response_parts else None

            # Add the user message (potentially multi-part) and model response to history
            current_user_message_for_display: Optional[Union[str, List[Union[str, Tuple[str,str]]]]] = None
            if user_message_accumulator:
                if len(user_message_accumulator) == 1:
                    current_user_message_for_display = user_message_accumulator[0]
                else:
                    current_user_message_for_display = list(user_message_accumulator) # Ensure it's a list copy

            gradio_history.append((current_user_message_for_display, final_model_output))
            user_message_accumulator = [] # Clear accumulator after pairing with a model response

    # After the loop, if there's any remaining user message, add it to history
    if user_message_accumulator:
        final_user_message_for_display: Optional[Union[str, List[Union[str, Tuple[str,str]]]]] = None
        if len(user_message_accumulator) == 1:
            final_user_message_for_display = user_message_accumulator[0]
        else:
            final_user_message_for_display = list(user_message_accumulator)
        gradio_history.append((final_user_message_for_display, None))

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