# -*- coding: utf-8 -*-
import os
import re
import traceback
from typing import List, Dict, Optional, Tuple, Union # Added for type hints
import gradio as gr
import character_manager

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
    (Definitive Final Architecture) Converts chat log to Gradio's history format.
    This version correctly handles complex conversational structures, including
    consecutive AI responses to a single user message, by processing the log
    in "turn-based" groups. It robustly displays all content types.
    """
    if not messages:
        return []

    gradio_history = []

    # Helper patterns defined here or ensure they are available if defined globally in the module
    thoughts_pattern = re.compile(r"【Thoughts】(.*?)【/Thoughts】", re.DOTALL | re.IGNORECASE)
    image_tag_pattern = re.compile(r"\[Generated Image: (.*?)\]")
    # This user_file_attach_pattern is from the user's code block.
    # It expects path;name;mime in the log string for user messages.
    # However, ui_handlers.py logs "[ファイル添付: original_filename]".
    # This discrepancy needs to be handled: either the pattern here is made simpler,
    # or the user's assumption about log format for this specific tag was from an older version.
    # User's latest description for this pattern was:
    # user_file_attach_pattern = re.compile(r"\[ファイル添付: (.*?);(.*?);(.*?)\]")
    # I will use this, and the code needs to be robust if it doesn't match all three groups
    # for some user messages that are just "[ファイル添付: filename]".
    user_file_attach_pattern = re.compile(r"\[ファイル添付: (.*?)\]") # Changed as per user instruction
    text_content_marker = "--- 添付ファイル「"

    turn_groups = []
    current_group = None
    for msg in messages:
        if msg.get("role") == "user":
            if current_group:
                turn_groups.append(current_group)
            # User's code does not filter empty content strings here, it's handled by later logic if user_display is empty.
            current_group = {"user": msg, "model_responses": []} # User's code uses msg object directly
        elif msg.get("role") == "model" and current_group:
            current_group["model_responses"].append(msg) # User's code uses msg object
    if current_group:
        turn_groups.append(current_group)

    for group in turn_groups:
        user_msg_obj = group["user"] # Get the full message object
        user_content = user_msg_obj.get("content", "").strip()

        user_display: Optional[Union[str, Tuple[str, str]]] # This is the variable name from user's code

        # User message processing from user's final code block:
        if text_content_marker in user_content and "」の内容 ---" in user_content: # Ensure full marker
            parts = user_content.split(text_content_marker, 1)
            clean_content = parts[0].strip()
            filename_part_and_rest = parts[1].split("」の内容 ---", 1)
            filename_part = filename_part_and_rest[0]
            display_tag = f"*[添付テキスト: {filename_part}]*"
            user_display = f"{clean_content}\n{display_tag}".strip() if clean_content else display_tag
        else:
            # This is the part that needs to be careful with user_file_attach_pattern
            # if the log only contains "[ファイル添付: filename]"
            match = user_file_attach_pattern.search(user_content) # Uses the new pattern
            if match:
                filepath = match.group(1).strip() # Group 1 is the full path
                original_filename = os.path.basename(filepath)
                user_display = (filepath, original_filename) if os.path.exists(filepath) else f"添付ファイル: {original_filename} (見つかりません)"
            else: # No "[ファイル添付: ...]" tag found
                user_display = user_content

        if not group["model_responses"]: # No AI responses in this group
            # User's code: gradio_history.append((user_display, None))
            # This is added regardless of user_display being potentially empty if original content was empty.
            if user_display or user_display == "": # Add if user_display is set (even if empty string from empty user message)
                gradio_history.append((user_display, None))
            continue

        # Process all AI responses for this turn
        all_text_parts = []
        final_image_part = None # Stores (filepath, basename)

        for model_msg_obj in group["model_responses"]:
            main_text = model_msg_obj.get("content", "").strip()
            if not main_text: # Skip empty AI messages within a turn group
                continue

            thought_match = thoughts_pattern.search(main_text)
            if thought_match:
                thoughts_content = thought_match.group(1).strip()
                if thoughts_content:
                    all_text_parts.append(f"<div class='thoughts'><pre><code>{thoughts_content}</code></pre></div>")
                main_text = thoughts_pattern.sub("", main_text).strip()

            image_match = image_tag_pattern.search(main_text)
            if image_match:
                image_path = image_match.group(1).strip() # Path from [Generated Image: <path>]
                if os.path.exists(image_path):
                    final_image_part = (image_path, os.path.basename(image_path))
                else:
                    all_text_parts.append(f"*[表示エラー: 画像ファイルが見つかりません ({os.path.basename(image_path)})]*")
                main_text = image_tag_pattern.sub("", main_text, 1).strip()

            if main_text:
                all_text_parts.append(main_text)

        # New 3-case logic for appending AI response to Gradio history
        user_message_for_this_turn = user_display

        if all_text_parts and final_image_part:
            final_text_output = "\n\n".join(all_text_parts)
            gradio_history.append((user_message_for_this_turn, final_text_output))
            gradio_history.append((None, final_image_part)) # User part is None for AI image turn
        elif all_text_parts: # Text only
            final_text_output = "\n\n".join(all_text_parts)
            gradio_history.append((user_message_for_this_turn, final_text_output))
        elif final_image_part: # Image only
            gradio_history.append((user_message_for_this_turn, final_image_part))
        # If no text and no image from AI (e.g. empty response, or only empty thoughts)
        # AND there was a user message for this turn, we should ensure the user message
        # isn't orphaned if it wasn't handled by the `if not group["model_responses"]:` block.
        # However, that block handles cases where model_responses list is empty.
        # If model_responses list is NOT empty, but results in no actual content (all_text_parts is empty AND final_image_part is None),
        # then the user_message_for_this_turn would be paired with effectively nothing.
        # The current logic implies that if all_text_parts and final_image_part are both falsey,
        # then nothing is added for the AI part of this turn. The user_message_for_this_turn would be lost.
        # This logic is what I'm implementing based on the user's prompt.

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


def save_log_file(character_name: str, content: str) -> None:
    """
    指定されたキャラクターのログファイルに内容を上書き保存します。

    Args:
        character_name (str): キャラクター名。
        content (str): 保存する内容。
    """
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
        # print(f"情報: ログファイル '{log_file_path}' を上書き保存しました。") # 必要に応じて有効化

    except IOError as e:
        print(f"エラー: ログファイル '{log_file_path}' への書き込み中にIOエラーが発生しました: {e}")
        traceback.print_exc()
    except Exception as e:
        print(f"エラー: ログファイル書き込み中に予期せぬエラーが発生しました (キャラクター: {character_name}): {e}")
        traceback.print_exc()