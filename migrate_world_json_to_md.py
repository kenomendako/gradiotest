# migrate_world_json_to_md.py (最終確定版・改)
import os
import json
import re

def convert_dict_to_yaml_lines(data: dict, indent_level: int = 0) -> list:
    """Pythonの辞書を、人間が読みやすいYAML形式の文字列リストに変換する。"""
    lines = []
    indent = "  " * indent_level

    for key, value in data.items():
        key_str = str(key)
        # YAMLのキーとして問題がありそうな文字を含む場合はクォートする
        if not re.match(r'^[a-zA-Z0-9_]+$', key_str):
            key_str = f'"{key_str}"'

        if isinstance(value, dict):
            lines.append(f"{indent}{key_str}:")
            lines.extend(convert_dict_to_yaml_lines(value, indent_level + 1))
        elif isinstance(value, list):
            lines.append(f"{indent}{key_str}:")
            for item in value:
                if isinstance(item, dict):
                    dict_lines = convert_dict_to_yaml_lines(item, indent_level + 1)
                    if dict_lines:
                        # 最初の行に '- ' を付け、残りの行はインデントをさらに追加
                        first_line = dict_lines[0].lstrip()
                        lines.append(f"{indent}  - {first_line}")
                        for line in dict_lines[1:]:
                            lines.append(f"{indent}    {line.lstrip()}")
                else:
                    lines.append(f"{indent}  - {json.dumps(item, ensure_ascii=False)}")
        else:
            # 文字列の場合は、改行を含む可能性を考慮しリテラルブロック形式にする
            if isinstance(value, str) and '\n' in value:
                lines.append(f"{indent}{key_str}: |-")
                for line in value.split('\n'):
                    lines.append(f"{indent}  {line}")
            else:
                 lines.append(f"{indent}{key_str}: {json.dumps(value, ensure_ascii=False)}")
    return lines

def main():
    characters_dir = "characters"
    if not os.path.isdir(characters_dir):
        print(f"エラー: '{characters_dir}' ディレクトリが見つかりません。")
        return

    print("--- 既存の world_settings.json から .md への移行を開始します ---")

    for char_name in os.listdir(characters_dir):
        char_path = os.path.join(characters_dir, char_name)
        if not os.path.isdir(char_path): continue

        spaces_path = os.path.join(char_path, "spaces")
        json_path = os.path.join(spaces_path, "world_settings.json")
        md_path = os.path.join(spaces_path, "world_settings.md")

        if os.path.exists(json_path):
            print(f"キャラクター '{char_name}' の移行処理を実行します...")
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                md_content = ""
                for area_key, area_value in data.items():
                    md_content += f"## {area_key}\n"

                    rooms = {}
                    area_props = {}

                    if isinstance(area_value, dict):
                        for key, value in area_value.items():
                            if isinstance(value, dict) and ('description' in value or 'name' in value):
                                rooms[key] = value
                            else:
                                area_props[key] = value

                    if area_props:
                        md_content += '\n'.join(convert_dict_to_yaml_lines(area_props)) + '\n\n'

                    for room_key, room_value in rooms.items():
                         md_content += f"### {room_key}\n"
                         md_content += '\n'.join(convert_dict_to_yaml_lines(room_value)) + '\n\n'

                with open(md_path, "w", encoding="utf-8") as f:
                    f.write(md_content.strip())

                backup_path = f"{json_path}.bak"
                if os.path.exists(backup_path): os.remove(backup_path)
                os.rename(json_path, backup_path)

                print(f"  -> 成功: '{md_path}' を作成し、元のJSONをバックアップしました。")

            except Exception as e:
                print(f"  -> エラー: '{char_name}' の移行中に問題が発生しました: {e}")
                import traceback
                traceback.print_exc()
        else:
            print(f"キャラクター '{char_name}' は移行の必要がありません (JSONが存在しません)。")

    print("\n--- 移行処理が完了しました ---")

if __name__ == "__main__":
    main()
