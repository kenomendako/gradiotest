import re
from datetime import datetime
import os

def fix_log_file(file_path):
    if not os.path.exists(file_path):
        print(f"Error: {file_path} not found")
        return

    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # ヘッダーで分割 (## USER:, ## AGENT:, ## SYSTEM:)
    # ただし、行頭にある場合のみ
    headers = list(re.finditer(r'^## (USER|AGENT|SYSTEM|NOTEPAD):', content, re.MULTILINE))
    
    blocks = []
    for i in range(len(headers)):
        start_pos = headers[i].start()
        end_pos = headers[i+1].start() if i + 1 < len(headers) else len(content)
        block_text = content[start_pos:end_pos].strip()
        
        # タイムスタンプを検索
        # 例: 2026-01-25 (Sun) 17:03:09
        # または 📝 2026-01-25 06:53 (これは NOTEPAD 系統など)
        ts_match = re.search(r'(\d{4}-\d{2}-\d{2}) \(...\) (\d{2}:\d{2}:\d{2})', block_text)
        if ts_match:
            ts_str = f"{ts_match.group(1)} {ts_match.group(2)}"
            ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
        else:
            # 代替パターン
            ts_match_alt = re.search(r'(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2})', block_text)
            if ts_match_alt:
                ts_str = f"{ts_match_alt.group(1)} {ts_match_alt.group(2)}:00"
                ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
            else:
                ts = None # 日付なし
        
        blocks.append({'text': block_text, 'ts': ts, 'orig_index': i})

    # ソート。日付がないものは、前のブロックの直後に置かれるように工夫する
    # 基本的には日付があるものでソートし、日付がないものは直前の「日付あり」ブロックに随伴させるのが理想的
    
    # グルーピング: 日付がないブロックを前の日付があるブロックにまとめる
    grouped_blocks = []
    current_group = None
    
    for b in blocks:
        if b['ts']:
            if current_group:
                grouped_blocks.append(current_group)
            current_group = {'ts': b['ts'], 'texts': [b['text']]}
        else:
            if current_group:
                current_group['texts'].append(b['text'])
            else:
                # 最初の数ブロックに日付がない場合
                grouped_blocks.append({'ts': datetime(1970, 1, 1), 'texts': [b['text']]})
    
    if current_group:
        grouped_blocks.append(current_group)

    # 日付でソート
    grouped_blocks.sort(key=lambda x: x['ts'])

    # 書き戻し
    with open(file_path + '.fixed', 'w', encoding='utf-8') as f:
        for group in grouped_blocks:
            for text in group['texts']:
                f.write(text + "\n\n")

    print(f"Fixed log written to {file_path}.fixed")
    print(f"Total grouped blocks: {len(grouped_blocks)}")

if __name__ == "__main__":
    fix_log_file('characters/ルシアン/log.txt')
