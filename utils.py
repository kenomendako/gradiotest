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


def format_history_for_gradio(messages: List[Dict[str, str]]) -> List[Tuple[Optional[str], Optional[Union[str, gr.Image, List[Union[str, gr.Image]]]]]]:
    """
    Converts a list of message dictionaries into Gradio's chatbot history format.
    User messages are strings. Model messages can be strings (Markdown)
    or lists of Gradio components (Markdown, Image, HTML) for rich content like
    displaying generated images and thoughts.

    Args:
        messages (List[Dict[str, str]]): List of message dictionaries.

    Returns:
        List containing (user_message, model_response) tuples, where elements
        can be strings or Gradio components/lists of components.
    """
    gradio_history: List[Tuple[Optional[str], Optional[Union[str, gr.Image, List[Union[str, gr.Image]]]]]] = []
    user_message_accumulator: Optional[str] = None # User messages are still accumulated as strings

    thoughts_pattern = re.compile(r"【Thoughts】(.*?)【/Thoughts】", re.DOTALL | re.IGNORECASE)
    image_tag_pattern = re.compile(r"\[Generated Image: (.*?)\]")

    for msg in messages:
        role = msg.get("role")
        content = msg.get("content", "").strip()

        if not content:
            continue

        if role == "user":
            if user_message_accumulator is not None:
                gradio_history.append((user_message_accumulator, None))

            # Process current user message for display (same logic as before for attachments)
            display_text_for_user_turn = content
            file_attach_pattern = r"(\[file_attachment:(.*?);(.*?);(.*?)\])([\s\S]*)"
            file_attach_match = re.match(file_attach_pattern, content)
            text_file_pattern = r"(\[添付テキストファイル:(.*?)\])([\s\S]*)"
            text_file_match = re.match(text_file_pattern, content)
            timestamp_str = ""

            if file_attach_match:
                original_filename = file_attach_match.group(3)
                mime_type = file_attach_match.group(4)
                timestamp_str = file_attach_match.group(5).strip()
                prefix = "添付ファイル:"
                if mime_type.startswith("image/"): prefix = "画像:"
                elif mime_type == "application/pdf": prefix = "PDF:"
                elif mime_type.startswith("audio/"): prefix = "音声:"
                elif mime_type.startswith("video/"): prefix = "動画:"
                display_text_for_user_turn = f"{prefix} {original_filename}"
            elif text_file_match:
                original_filename = text_file_match.group(2)
                timestamp_str = text_file_match.group(3).strip()
                display_text_for_user_turn = f"添付テキスト: {original_filename}"
            
            if timestamp_str:
                original_content_for_ts_check = file_attach_match.group(0) if file_attach_match else (text_file_match.group(0) if text_file_match else "")
                original_timestamp_part = file_attach_match.group(5) if file_attach_match else (text_file_match.group(3) if text_file_match else "")
                if original_timestamp_part.startswith(('\n', '\r')):
                    display_text_for_user_turn += f"\n{timestamp_str}"
                else:
                    display_text_for_user_turn += f" ({timestamp_str})" if not display_text_for_user_turn.endswith(timestamp_str) else ""

            user_message_accumulator = display_text_for_user_turn # Store as string

        elif role == "model":
            model_response_components: List[Union[gr.Markdown, gr.Image, gr.HTML]] = []

            # 1. Extract Thoughts
            # model_response_components: List[Union[str, gr.Image]] = [] # Corrected type for this list
            model_response_components: List[Union[str, gr.Image]] = []

            # --- Start of temporarily removed Thoughts processing ---
            # thought_match = thoughts_pattern.search(content)
            # if thought_match:
            #     thoughts_content = thought_match.group(1).strip()
            #     if thoughts_content: # Only add if there's actual thought content
            #         single_line_thoughts = thoughts_content.replace('\n', ' ').strip()
            #         # Optionally, add truncation:
            #         # single_line_thoughts = single_line_thoughts[:200]
            #         thought_markdown_str = f"LLM Thoughts {single_line_thoughts}"
            #         model_response_components.append(thought_markdown_str)
            # --- End of temporarily removed Thoughts processing ---

            # Main response text after removing thoughts (or from full content if thoughts are disabled)
            main_response_text = thoughts_pattern.sub("", content).strip()

            # 2. Process for Image Tags
            # model_response_components will be empty if thoughts were disabled and main_response_text is also empty

            if main_response_text:
                parts = image_tag_pattern.split(main_response_text)
                # Example: "text1 [Generated Image: path1] text2"
                # -> ['text1 ', 'path1', ' text2']

                idx = 0
                while idx < len(parts):
                    text_segment_candidate = parts[idx].strip()
                    if text_segment_candidate: # Add non-empty text segments as STRINGS
                        model_response_components.append(text_segment_candidate)

                    idx += 1
                    if idx < len(parts): # This part is an image path
                        image_path = parts[idx].strip()
                        if os.path.exists(image_path):
                            model_response_components.append(gr.Image(value=image_path, interactive=False, show_label=False, show_download_button=True))
                        else:
                            # Append "Image not found" message as a plain string (Markdown formatted)
                            model_response_components.append(f"\n\n*[Image not found: {image_path}]*\n\n")
                        idx += 1

            # Determine final_model_output based on model_response_components
            if not model_response_components:
                # This occurs if thoughts were empty AND main_response_text was empty.
                final_model_output = ""
            elif len(model_response_components) == 1:
                # If it's a single component (string or gr.Image)
                final_model_output = model_response_components[0]
            else: # Multiple components (list of strings and gr.Image)
                final_model_output = model_response_components

            user_msg_to_display = user_message_accumulator # Pass as plain string
            gradio_history.append((user_msg_to_display, final_model_output))
            user_message_accumulator = None

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