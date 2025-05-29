# -*- coding: utf-8 -*-
import os
import re
import traceback

# --- ユーティリティ関数 ---
def load_chat_log(file_path, character_name):
    messages = []
    if not character_name or not file_path or not os.path.exists(file_path): return messages
    ai_hdr, alarm_hdr = f"## {character_name}:", "## システム(アラーム):"
    try:
        with open(file_path, "r", encoding="utf-8") as f: lines = f.readlines()
    except Exception as e: print(f"ログファイル '{file_path}' の読み込み中にエラーが発生しました: {e}"); return messages
    role, txt = None, []
    for line in lines:
        s = line.strip()
        if s.startswith("## ") and s.endswith(":"):
            if role and txt: messages.append({"role": role, "content": "\n".join(txt).strip()})
            txt = []
            if s == ai_hdr: role = "model"
            elif s == alarm_hdr: role = "user" # システムアラームもユーザー扱いにする
            else: role = "user"
        elif role:
            txt.append(line.rstrip('\n'))
    if role and txt: messages.append({"role": role, "content": "\n".join(txt).strip()})
    return messages

def format_response_for_display(response_text):
    if not response_text:
        return ""
    match = re.search(r"【Thoughts】(.*?)【/Thoughts】", response_text, re.DOTALL | re.IGNORECASE)
    if match:
        # Thoughts部分を<pre><code>...</code></pre>でラップし、折り返し有効＋段落間余白を調整
        thoughts_content = match.group(1).strip()
        thought = (
            "<div class='thoughts' style='white-space:pre-wrap;overflow-x:auto;word-break:break-word; margin-bottom:0.5em;'>"
            "<pre style='white-space:pre-wrap;overflow-x:auto;word-break:break-word; margin:0 0 0.3em 0; line-height:1.5;'><code style='white-space:pre-wrap;word-break:break-word; margin:0; padding:0; line-height:1.5;'>{}</code></pre></div>"
        ).format(thoughts_content.replace('\n', '\n'))
        main_resp = re.sub(r"【Thoughts】.*?【/Thoughts】\s*", "", response_text, flags=re.DOTALL | re.IGNORECASE).strip()
        # 本文はそのままマークダウンとして返す
        return f"{thought}\n\n{main_resp}" if main_resp else thought
    # Thoughtsが無い場合もそのまま返す（マークダウン解釈用）
    return response_text.strip()

def format_history_for_gradio(messages):
    hist = []
    user_msg_accumulator = None # To hold the current user message (text or image path)

    for msg in messages:
        role = msg.get("role")
        content = msg.get("content", "")

        if not content:
            continue

        if role == "user":
            # If there's an accumulated user message, it means the previous message was also from the user
            # or it's the start. We finalize the previous user message before processing the new one if it was waiting for a model response.
            # This logic is tricky with consecutive user messages if not handled carefully.
            # The original logic implied a user message is only added to hist when a model message follows, or at the end.
            # Let's refine to handle image attachments specifically.

            image_match = re.fullmatch(r"\[image_attachment:(.*?)\]", content)
            if image_match:
                attachment_path = image_match.group(1)
                # If a user message (text) was pending, add it with no model response yet
                if user_msg_accumulator is not None:
                    hist.append([user_msg_accumulator, None])
                # Add the image as a new user message
                user_msg_accumulator = (attachment_path, "添付画像")
            else: # Regular text message from user
                # If a user message (image) was pending, add it
                if user_msg_accumulator is not None:
                     hist.append([user_msg_accumulator, None]) # Add pending message (could be image or text)
                user_msg_accumulator = content # Store as current user message

        elif role == "model":
            display_content = format_response_for_display(content)
            if user_msg_accumulator is not None:
                # Pair the accumulated user message with this model message
                hist.append([user_msg_accumulator, display_content])
                user_msg_accumulator = None # Reset accumulator
            else:
                # Model message without a preceding user message (should be rare, but handle)
                hist.append([None, display_content])

    # If there's any uncommitted user message at the end (e.g., last message in log is from user)
    if user_msg_accumulator is not None:
        hist.append([user_msg_accumulator, None])

    return hist

def save_message_to_log(log_file, header, text):
    if not text or not text.strip() or not log_file or not header: return
    try:
        nl = os.path.exists(log_file) and os.path.getsize(log_file) > 0
        if nl:
            with open(log_file, "rb") as f: f.seek(-1, os.SEEK_END); nl = (f.read(1) != b'\n')
        with open(log_file, "a", encoding="utf-8") as f:
            if nl: f.write("\n")
            f.write(f"{header}\n\n{text.strip()}\n\n")
    except Exception as e: print(f"ログファイル '{log_file}' への書き込み中にエラー: {e}"); traceback.print_exc()

def _get_user_header_from_log(log_file, ai_name):
    dflt, ai, alrm = "## ユーザー:", f"## {ai_name}:", "## システム(アラーム):"
    if not log_file or not os.path.exists(log_file): return dflt
    try:
        last_user_header = dflt
        with open(log_file, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if s.startswith("## ") and s.endswith(":") and s != ai and s != alrm:
                    last_user_header = s
        return last_user_header
    except Exception: return dflt