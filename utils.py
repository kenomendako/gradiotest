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


def format_history_for_gradio(messages: List[Dict[str, str]]) -> List[Tuple[Optional[Union[str, Tuple[str,str]]], Optional[str]]]:
    """
    Converts chat log to Gradio's history format.
    This definitive version avoids complex lists for the AI response by building a single,
    robust Markdown string, which prevents file caching errors in Gradio.
    """
    gradio_history = []
    user_message_accumulator: Optional[Union[str, Tuple[str,str]]] = None # Can be a string or a (filepath, alt_text) tuple for user's turn

    # 正規表現パターンの定義
    thoughts_pattern = re.compile(r"【Thoughts】(.*?)【/Thoughts】", re.DOTALL | re.IGNORECASE)
    image_tag_pattern = re.compile(r"\[Generated Image: (.*?)\]")
    # ユーザーの添付ファイル表示用のパターン
    user_file_attach_pattern = re.compile(r"\[ファイル添付: (.*?);(.*?);(.*?)\]") # filepath;original_filename;mimetype

    for msg in messages:
        role = msg.get("role")
        content = msg.get("content", "").strip()

        if not content:
            continue

        if role == "user":
            if user_message_accumulator is not None: # If there was a previous user message not yet added
                gradio_history.append((user_message_accumulator, None))
                user_message_accumulator = None # Reset for current message

            # ユーザーメッセージを解析
            file_match = user_file_attach_pattern.search(content)
            if file_match:
                filepath, original_filename, _ = file_match.groups() # Mime type is available if needed later
                # ユーザーの添付ファイルはタプル形式で表示
                user_message_accumulator = (filepath, original_filename) if os.path.exists(filepath) else f"添付ファイル: {original_filename} (見つかりません)"
            else:
                user_message_accumulator = content

        elif role == "model":
            # AIの応答の各部分を格納するリスト
            response_parts = [] # List to hold parts of the AI's response (HTML for thoughts, Markdown for image, plain text)
            main_text = content # Start with full content

            # 1. 思考ログを抽出し、HTMLとしてpartsに追加
            thought_match = thoughts_pattern.search(main_text)
            if thought_match:
                thoughts_content = thought_match.group(1).strip()
                if thoughts_content: # Ensure there's actual content within thoughts
                    thought_html = f"<div class='thoughts'><pre><code>{thoughts_content}</code></pre></div>"
                    response_parts.append(thought_html)
                main_text = thoughts_pattern.sub("", main_text).strip() # Remove thoughts from main_text

            # 2. 生成画像を抽出し、Markdown形式の画像リンクとしてpartsに追加
            # Need to handle multiple images if they exist
            processed_text_for_images = main_text
            temp_image_parts = []
            while True:
                image_match = image_tag_pattern.search(processed_text_for_images)
                if image_match:
                    image_path = image_match.group(1).strip()
                    if os.path.exists(image_path):
                        # Gradio uses file= for local files in Markdown
                        image_markdown = f"![{os.path.basename(image_path)}](file={image_path})"
                        temp_image_parts.append(image_markdown)
                    else:
                        temp_image_parts.append(f"*[表示エラー: 画像ファイルが見つかりません ({os.path.basename(image_path)})]*")
                    # Remove the processed image tag by replacing only the first occurrence
                    processed_text_for_images = image_tag_pattern.sub("", processed_text_for_images, 1)
                else:
                    break

            if temp_image_parts:
                response_parts.extend(temp_image_parts)
            main_text = processed_text_for_images.strip() # Update main_text after all images are processed


            # 3. 画像関連の他のログタグ（プロンプト、モデルテキスト、エラー）を本文から削除
            # This was in previous user versions, but the "final確定版" prompt's code
            # did not explicitly include gazo_related_pattern or similar for removal from main_text
            # *after* thoughts and images were extracted.
            # The user's final code implies these are handled by not being thoughts or images.
            # Let's re-verify the provided "final確定版" code structure.
            # The "final確定版" code snippet was:
            #   main_text = thoughts_pattern.sub("", main_text).strip()
            #   image_match = image_tag_pattern.search(main_text) ... main_text = image_tag_pattern.sub("", main_text).strip()
            #   if main_text: response_parts.append(main_text)
            # This implies that other tags like [画像モデルからのテキスト] will remain in main_text if not caught by thoughts/image.
            # This is a key difference from some intermediate versions.
            # For this subtask, I will strictly follow the user's LATEST provided "final確定版" code structure
            # which does *not* have a separate gazo_related_pattern.sub() call here.
            # Such tags, if not part of thoughts or image tags, will naturally fall into `main_text`.

            # 4. 本文が残っていればpartsに追加
            if main_text:
                response_parts.append(main_text)

            # 5. 全てのpartsを改行2つで連結し、単一のMarkdown文字列を生成
            # If response_parts is empty (e.g. model sent only an empty message or only tags that were stripped),
            # final_model_output should be an empty string or None.
            # The user's code implies join, which would be empty string if parts is empty.
            final_model_output = "\n\n".join(response_parts) if response_parts else "" # Ensure empty string if no parts

            # 履歴に追加
            # user_message_accumulator should be committed here.
            # It could be None if the very first message is from the model (unlikely in normal chat flow).
            gradio_history.append((user_message_accumulator, final_model_output))
            user_message_accumulator = None # Reset after pairing with a model response

    # ループ後に残っている最後のユーザーメッセージを処理
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