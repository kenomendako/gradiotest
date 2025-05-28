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
    hist = []; user_msg = None
    for msg in messages:
        role, content = msg.get("role"), msg.get("content", "")
        if not content: continue
        display = format_response_for_display(content) if role == "model" else content
        if role == "user":
            if user_msg is not None:
                hist.append([user_msg, None]) # 前のユーザー発言が残っていたら確定
            user_msg = display
        elif role == "model":
            if user_msg is None: # AI発言が先に来る場合（ほぼないはずだが念のため）
                hist.append([None, display])
            else:
                hist.append([user_msg, display])
            user_msg = None # AIの発言が終わったらリセット
    if user_msg is not None: hist.append([user_msg, None]) # 最後のユーザー発言が残っていれば追加
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