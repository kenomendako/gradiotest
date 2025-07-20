import os
import re
from typing import List, Dict, Union

import yaml


def format_response_for_display(text: str) -> str:
    """
    AIの応答から【Thought】部分を削除し、表示用に整形します。
    """
    return re.sub(r'【Thought】.*', '', text, flags=re.DOTALL).strip()


def load_chat_log(log_file: str, character_name: str) -> List[Dict[str, str]]:
    """
    指定されたキャラクターのチャットログを読み込み、リスト形式で返します。
    """
    if not os.path.exists(log_file):
        return []

    with open(log_file, 'r', encoding='utf-8') as f:
        content = f.read()

    # YAMLドキュメントを分割
    documents = content.split('---')

    messages = []
    user_header = '## user:'
    # ユーザーヘッダーを動的に取得しようと試みる
    # ログファイルから最初のユーザーヘッダーを探す
    for doc in documents:
        if 'role: user' in doc or 'role: human' in doc:
            lines = doc.strip().split('\n')
            if len(lines) > 1 and lines[1].startswith('## '):
                user_header = lines[1].strip()
                break

    ai_header = f"## {character_name}:"

    for doc in documents:
        if not doc.strip():
            continue

        # 各ドキュメントのヘッダーを判定
        if ai_header in doc:
            role = 'model'
            # ヘッダー以降の内容を抽出
            message_content = doc.split(ai_header, 1)[1].strip()
        elif user_header in doc:
            role = 'user'
            message_content = doc.split(user_header, 1)[1].strip()
        else:
            # 不明な形式のドキュメントはスキップ
            continue

        messages.append({'role': role, 'content': message_content})

    return messages


def format_history_for_gradio(messages: List[Dict[str, str]]) -> List[Dict[str, Union[str, tuple, None]]]:
    """
    チャットログをGradio Chatbotの `messages` 形式に変換します。
    【Thought】タグ、AI生成画像、ユーザー添付ファイル（複数対応）を適切に処理します。
    """
    if not messages:
        return []

    gradio_history = []
    # 正規表現パターンを関数の先頭でコンパイル
    ai_image_tag_pattern = re.compile(r"\[Generated Image: (.*?)\]")
    user_file_attach_pattern = re.compile(r"\[ファイル添付: (.*?)\]")

    for msg in messages:
        role = "assistant" if msg.get("role") == "model" else "user"
        content = msg.get("content", "").strip()

        if not content:
            # contentが空の場合は、表示しないか、空のメッセージとして追加
            # gradio_history.append({"role": role, "content": None})
            continue

        # ★★★ ここからが修正箇所 ★★★
        # メッセージを改行で分割し、各行を個別に処理
        lines = content.splitlines()
        text_buffer = []

        for line in lines:
            # ユーザー添付ファイルのタグを処理
            file_match = user_file_attach_pattern.fullmatch(line.strip())
            if file_match:
                # テキストバッファがあれば先に出力
                if text_buffer:
                    gradio_history.append({"role": role, "content": "\n".join(text_buffer)})
                    text_buffer = []

                # ファイルを出力
                filepath = file_match.group(1).strip()
                original_filename = os.path.basename(filepath)
                absolute_filepath = os.path.abspath(filepath)
                if os.path.exists(absolute_filepath):
                    gradio_history.append({"role": role, "content": (absolute_filepath, original_filename)})
                else:
                    gradio_history.append({"role": role, "content": f"*[表示エラー: ファイル '{original_filename}' が見つかりません]*"})
                continue

            # AI生成画像のタグを処理
            image_match = ai_image_tag_pattern.fullmatch(line.strip())
            if image_match:
                 # テキストバッファがあれば先に出力
                if text_buffer:
                    gradio_history.append({"role": role, "content": format_response_for_display("\n".join(text_buffer))})
                    text_buffer = []

                # 画像を出力
                image_path = image_match.group(1).strip()
                absolute_image_path = os.path.abspath(image_path)
                if os.path.exists(absolute_image_path):
                    gradio_history.append({"role": role, "content": (absolute_image_path, os.path.basename(image_path))})
                else:
                    gradio_history.append({"role": role, "content": f"*[表示エラー: 画像 '{os.path.basename(image_path)}' が見つかりません]*"})
                continue

            # タグに一致しない行はテキストバッファに追加
            text_buffer.append(line)

        # ループ終了後に残ったテキストバッファを出力
        if text_buffer:
            final_text = "\n".join(text_buffer)
            # AIの応答の場合は【Thoughts】タグを処理する
            formatted_text = format_response_for_display(final_text) if role == "assistant" else final_text
            gradio_history.append({"role": role, "content": formatted_text})
        # ★★★ 修正ここまで ★★★

    return gradio_history


def load_character_settings(character_name: str) -> Dict:
    """
    キャラクターの設定ファイルを読み込みます。
    """
    # この関数は character_manager に移動しました。
    # 互換性のために残していますが、将来的には削除される可能性があります。
    from character_manager import load_character_settings as load_settings
    return load_settings(character_name)


def get_available_characters() -> List[str]:
    """
    利用可能なキャラクターのリストを取得します。
    """
    # この関数は character_manager に移動しました。
    from character_manager import get_available_characters as get_chars
    return get_chars()


def load_common_prompts() -> Dict[str, str]:
    """
    共通プロンプトファイルを読み込みます。
    """
    common_prompts_path = os.path.join('characters', 'common', 'common_prompts.yaml')
    if os.path.exists(common_prompts_path):
        with open(common_prompts_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    return {}
