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

# --- ★★★ ここからが修正箇所 ★★★ ---
def format_history_for_gradio(messages: List[Dict[str, str]]) -> List[Dict[str, Union[str, tuple, None]]]:
    """
    チャットログをGradio Chatbotの `messages` 形式に変換します。
    【Thought】タグ、AI生成画像、ユーザー添付ファイルを、現在の実行環境に合わせて
    堅牢に処理します。
    """
    if not messages:
        return []

    gradio_history = []
    # --- ★★★ パス再構築のための設定 ★★★ ---
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # AI生成画像のベースディレクトリ
    generated_images_dir = os.path.join(script_dir, "chat_attachments", "generated_images")
    # ユーザー添付ファイルのベースディレクトリ（将来的にはここも統一するべきだが、一旦保留）
    # この部分は元の実装に依存するため、エラーが出ないようにGradioのキャッシュ領域などを想定
    # Gradioはアップロードされたファイルを一時ディレクトリに保存する

    image_tag_pattern = re.compile(r"\[Generated Image: (.*?)\]")
    user_file_attach_pattern = re.compile(r"\[ファイル添付: (.*?)\]")

    for msg in messages:
        role = "assistant" if msg.get("role") == "model" else "user"
        content = msg.get("content", "").strip()

        if not content:
            gradio_history.append({"role": role, "content": None})
            continue

        # --- AIの応答を処理 ---
        if role == "assistant":
            # AI応答から画像タグを分離
            image_matches = list(image_tag_pattern.finditer(content))
            text_part = image_tag_pattern.sub("", content).strip()

            # 最初にテキスト部分（思考ログ含む）を追加
            if text_part:
                formatted_content = format_response_for_display(text_part)
                gradio_history.append({"role": role, "content": formatted_content})

            # 次に画像部分をループして追加
            if image_matches:
                for match in image_matches:
                    # ログに記録された古いパスからファイル名だけを抽出
                    original_path = match.group(1).strip()
                    image_filename = os.path.basename(original_path)

                    # 現在の環境での正しい絶対パスを再構築
                    current_valid_path = os.path.join(generated_images_dir, image_filename)

                    if os.path.exists(current_valid_path):
                        gradio_history.append({"role": role, "content": (current_valid_path, image_filename)})
                    else:
                        gradio_history.append({"role": role, "content": f"*[表示エラー: 画像 '{image_filename}' が見つかりません]*"})
            continue

        # --- ユーザーのメッセージを処理 ---
        if role == "user":
            # ユーザーメッセージからファイル添付タグを分離
            file_matches = list(user_file_attach_pattern.finditer(content))
            text_part = user_file_attach_pattern.sub("", content).strip()

            # 最初にテキスト部分を追加
            if text_part:
                gradio_history.append({"role": role, "content": text_part})

            # 次にファイル部分をループして追加
            if file_matches:
                for match in file_matches:
                    # GradioのFileコンポーネントが返すパスは通常、一時キャッシュ内の絶対パス
                    # そのため、これはそのまま利用できる可能性が高い
                    filepath = match.group(1).strip()
                    original_filename = os.path.basename(filepath)

                    # このパスはGradioが管理する一時パスか、ユーザーがアクセス可能なパスなので、
                    # そのまま表示を試みるのが妥当
                    if os.path.exists(filepath):
                        gradio_history.append({"role": role, "content": (filepath, original_filename)})
                    else:
                        # もし過去ログの添付ファイルパスが永続的でない場合のエラー表示
                        gradio_history.append({"role": role, "content": f"*[表示エラー: ファイル '{original_filename}' が見つかりません]*"})
            continue

        # 上記のいずれにも当てはまらない通常のメッセージ
        gradio_history.append({"role": role, "content": content})

    return gradio_history
# --- ★★★ 修正ここまで ★★★ ---

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
