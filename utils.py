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


def format_history_for_gradio(messages: List[Dict[str, str]]) -> List[Tuple[Optional[Union[str, Tuple[str, str]]], Optional[Union[str, Tuple[str, str], List[Union[str, Tuple[str, str]]]]]]]:
    """
    (Definitive Final Version) Converts chat log to Gradio's history format.
    This version assumes logs are pre-summarized (by ui_handlers.py)
    and focuses on stable rendering, including splitting AI responses
    with images into separate turns.
    """
    gradio_history = []
    user_message_accumulator: Optional[Union[str, Tuple[str, str]]] = None

    thoughts_pattern = re.compile(r"【Thoughts】(.*?)【/Thoughts】", re.DOTALL | re.IGNORECASE)
    image_tag_pattern = re.compile(r"\[Generated Image: (.*?)\]")
    # For user messages, we now expect tags like "[ファイル添付: filename.jpg]"
    # or "[添付テキスト: filename.txt]" directly from the log.
    # We need to identify if a user message *is* such a file tag to potentially make it a tuple for Gradio.
    # The user's provided code for utils.py in the "integrated final version" simplified user message handling to:
    # user_message_accumulator = content
    # This implies that Gradio can render "[ファイル添付: filename.jpg]" as a string,
    # or that ui_handlers.py actually logs it as a tuple if it's a non-text file.
    # Let's re-check ui_handlers.py's text_for_log logic:
    # - For text files: text_for_log += f"\n[添付テキスト: {original_filename}]" (This is a string)
    # - For other files: text_for_log += f"\n[ファイル添付: {original_filename}]" (This is also a string)
    # So, format_history_for_gradio will receive these as strings in `content`.
    # If we want Gradio to make these actual file links/previews, utils.py *still* needs to parse them
    # and convert "[ファイル添付: ...]" into tuples if the file exists.
    # The user's LATEST utils.py code seems to have a disconnect here if it just uses `user_message_accumulator = content`.
    # I will use the user's LATEST utils.py code provided in the "統合版" (integrated version) email,
    # which includes specific parsing for these tags.

    # Patterns to identify pre-summarized tags in user messages from the log
    user_general_file_attach_pattern = re.compile(r"\[ファイル添付: (.*?)\]") # For images, pdfs etc.
    user_text_file_attach_pattern = re.compile(r"\[添付テキスト: (.*?)\]") # For text files

    for msg in messages:
        role = msg.get("role")
        content = msg.get("content", "").strip()

        if not content:
            continue

        if role == "user":
            if user_message_accumulator is not None:
                gradio_history.append((user_message_accumulator, None))

            # Now, parse the `content` which is from the log
            general_file_match = user_general_file_attach_pattern.fullmatch(content) # Use fullmatch if tag is entire content
            text_file_match = user_text_file_attach_pattern.fullmatch(content)

            if general_file_match:
                # This was logged as "[ファイル添付: original_filename]"
                # We need to find the *actual* path of this file in ATTACHMENTS_DIR.
                # This requires ui_handlers.py to have logged enough info, or we need a lookup mechanism.
                # The log from ui_handlers.py's `text_for_log += f"\n[ファイル添付: {original_filename}]"` only gives original_filename.
                # This is a problem. For Gradio to make it a clickable link/preview, it needs the *actual path*.
                #
                # Option 1: Assume `original_filename` is unique enough in `ATTACHMENTS_DIR` (bad assumption).
                # Option 2: `ui_handlers.py` needs to log the *saved path* not just original_filename for these.
                # E.g., text_for_log += f"\n[ファイル添付: {saved_attachment_path};{original_filename}]"
                # Then utils.py can parse it.
                #
                # Given the user's latest `utils.py` code block (from the "統合版"),
                # it simplified user message handling to `user_message_accumulator = content`.
                # This means it expects Gradio to just display the string "[ファイル添付: filename.jpg]".
                # This will NOT result in a clickable file or image preview.
                #
                # Let's re-evaluate the user's *latest* `utils.py` snippet for the "統合版":
                # It had:
                # user_file_attach_pattern = re.compile(r"\[ファイル添付: (.*?)\]")
                # user_text_attach_pattern = re.compile(r"\[添付テキスト: (.*?)\]") # 新しいログ形式に対応
                # # ...
                # if role == "user":
                #    if user_message_accumulator is not None:
                #        gradio_history.append((user_message_accumulator, None))
                #    # ログは既に要約されているので、そのまま表示するだけ
                #    user_message_accumulator = content
                # ```
                # This means `user_message_accumulator` will be the literal string "[ファイル添付: name.jpg]" or "[添付テキスト: name.txt]".
                user_message_accumulator = content

        elif role == "model":
            ai_text_parts = []
            ai_image_tuple = None
            main_text = content

            thought_match = thoughts_pattern.search(main_text)
            if thought_match:
                thoughts_content = thought_match.group(1).strip()
                if thoughts_content:
                    ai_text_parts.append(f"<div class='thoughts'><pre><code>{thoughts_content}</code></pre></div>")
                main_text = thoughts_pattern.sub("", main_text).strip()

            # Process AI-generated images
            image_match = image_tag_pattern.search(main_text)
            if image_match:
                image_path = image_match.group(1).strip() # This path is from [Generated Image: <path>]
                                                          # In ui_handlers, these are saved in ATTACHMENTS_DIR.
                                                          # The path logged is typically relative like "chat_attachments/uuid.png"
                                                          # or an absolute path if that's how it was saved.
                                                          # This path should be directly usable by Gradio via allowed_paths.
                if os.path.exists(image_path):
                    ai_image_tuple = (image_path, os.path.basename(image_path))
                else:
                    ai_text_parts.append(f"*[表示エラー: 画像ファイルが見つかりません ({os.path.basename(image_path)})]*")
                main_text = image_tag_pattern.sub("", main_text, 1).strip()

            if main_text:
                ai_text_parts.append(main_text)

            # Splitting logic based on user's latest utils.py in "統合版"
            user_message_for_this_turn = user_message_accumulator
            # user_message_accumulator = None # Reset for next turn (done after adding to history)

            if ai_text_parts and ai_image_tuple:
                # Both text and image: split into two turns
                final_text_output = "\n\n".join(ai_text_parts)
                gradio_history.append((user_message_for_this_turn, final_text_output))
                gradio_history.append(("", ai_image_tuple)) # Image on a new line, no user part
            elif ai_text_parts:
                # Only text
                final_text_output = "\n\n".join(ai_text_parts)
                gradio_history.append((user_message_for_this_turn, final_text_output))
            elif ai_image_tuple:
                # Only image
                gradio_history.append((user_message_for_this_turn, ai_image_tuple))
            # If neither (empty AI response), nothing is added for AI, user_message_accumulator will carry over or be handled by loop end.
            # However, an empty AI response should still clear user_message_accumulator for that turn.

            user_message_accumulator = None # Critical: reset user_message_accumulator after AI turn processing

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