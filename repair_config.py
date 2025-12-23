
import json
import os
import re

def repair_json(file_path):
    print(f"Attempting advanced repair: {file_path}")
    if not os.path.exists(file_path):
        print("File not found.")
        return

    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    # 1. すべての '{' の位置を探す
    starts = [m.start() for m in re.finditer('{', content)]
    
    # 2. 正常にパースできる最大のブロックを後ろから探す
    # （ファイルのお尻の方に最新かつ断片化されたデータがある可能性があるため）
    best_data = None
    
    for start in reversed(starts):
        # この開始地点から最後までを対象にする
        candidate_block = content[start:]
        # 閉じ括弧を探して一つずつ試す
        ends = [m.start() for m in re.finditer('}', candidate_block)]
        for end in reversed(ends):
            try:
                data = json.loads(candidate_block[:end+1])
                # room_name など必須キーがあるかチェック
                if "room_name" in data:
                    best_data = data
                    print(f"Recovered valid JSON starting at {start} and ending at {start+end}")
                    break
            except:
                continue
        if best_data: break

    if not best_data:
        print("Could not recover any valid Room Config JSON.")
        return

    data = best_data

    # 3. 破壊されている可能性のある特定キーをチェック/クリーニング
    if "override_settings" in data:
        overrides = data["override_settings"]
        for k, v in overrides.items():
            # 文字列化したタプルなどをリストに修正
            if isinstance(v, str) and v.startswith('(') and v.endswith(')'):
                 print(f"Cleaning suspected tuple-string for {k}: {v}")
                 try:
                     parts = v.strip('()').split(',')
                     overrides[k] = [p.strip().strip("'").strip('"') for p in parts if p.strip()]
                 except:
                     pass

    # 4. 上書き保存
    temp_path = file_path + ".repair.tmp"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    os.replace(temp_path, file_path)
    print("Repair complete.")

if __name__ == "__main__":
    target = "c:/Users/baken/OneDrive/デスクトップ/gradio_github/gradiotest/characters/ルシアン/room_config.json"
    repair_json(target)
