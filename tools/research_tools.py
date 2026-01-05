# tools/research_tools.py (Phase 3: Contextual Analysis)

from langchain_core.tools import tool
import os
from room_manager import get_room_files_paths
import json
from typing import List, Dict, Any
import traceback
import datetime
import re

@tool
def read_research_notes(room_name: str) -> str:
    """
    研究・分析ノートの全内容を読み取る。
    Web閲覧ツール等で得た知識や、AIによる自律的な分析結果が蓄積されています。
    """
    _, _, _, _, _, research_notes_path = get_room_files_paths(room_name)
    if not research_notes_path or not os.path.exists(research_notes_path):
        return "【研究ノートファイルが見つかりません】"
    with open(research_notes_path, 'r', encoding='utf-8') as f:
        content = f.read().strip()
        return content if content else "【研究ノートは空です】"

@tool
def plan_research_notes_edit(modification_request: str, room_name: str) -> str:
    """
    【ステップ1：計画】研究・分析ノートの変更を計画します。
    分析結果の記録、既存の考察の更新、新しい研究テーマの追加など、
    研究ノートを自律的に整理・更新し続けるために使用します。
    """
    return f"システムへの研究ノート編集計画を受け付けました。意図:「{modification_request}」"

def _apply_research_notes_edits(instructions: List[Dict[str, Any]], room_name: str) -> str:
    """【内部専用】AIが生成した行番号ベースの差分編集指示リストを解釈し、research_notes.mdに適用する。"""
    if not room_name:
        return "【エラー】ルーム名が指定されていません。"
    if not isinstance(instructions, list):
        return "【エラー】編集指示がリスト形式ではありません。"

    _, _, _, _, _, research_notes_path = get_room_files_paths(room_name)
    if not research_notes_path or not os.path.exists(research_notes_path):
        return f"【エラー】ルーム'{room_name}'の研究ノートファイルパスが見つかりません。"

    try:
        with open(research_notes_path, 'r', encoding='utf-8') as f:
            lines = f.read().split('\n')

        line_plan = {}
        insertions = {}
        timestamp = f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}]"
        
        for inst in instructions:
            op = inst.get("operation", "").lower()
            line_num = inst.get("line")
            if line_num is None: continue
            target_index = line_num - 1
            if not (0 <= target_index < len(lines)): continue

            final_content = inst.get("content", "")
            # opが'replace'または'insert_after'で、かつcontentに実質的な内容がある場合のみ処理
            if op in ["replace", "insert_after"] and str(final_content).strip():
                # content内の各行を処理
                lines_in_content = str(final_content).split('\n')
                processed_lines = []
                for line in lines_in_content:
                    # タイムスタンプの有無をチェック（既に付いている場合は重ねない）
                    if line.strip() and not re.match(r"^\[\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}\]", line.strip()):
                        processed_lines.append(f"{timestamp} {line}")
                    else:
                        processed_lines.append(line)
                final_content = "\n".join(processed_lines)

            if op == "delete":
                line_plan[target_index] = {"operation": "delete"}
            elif op == "replace":
                line_plan[target_index] = {"operation": "replace", "content": final_content}
            elif op == "insert_after":
                if target_index not in insertions:
                    insertions[target_index] = []
                insertions[target_index].extend(str(final_content).split('\n'))

        new_lines = []
        for i, line_content in enumerate(lines):
            plan = line_plan.get(i)
            if plan is None:
                new_lines.append(line_content)
            elif plan["operation"] == "replace":
                new_lines.append(plan["content"])
            elif plan["operation"] == "delete":
                pass

            if i in insertions:
                new_lines.extend(insertions[i])

        with open(research_notes_path, "w", encoding="utf-8") as f:
            f.write("\n".join(new_lines))

        return f"成功: {len(instructions)}件の指示に基づき、研究ノート(research_notes.md)を更新しました。"
    except Exception as e:
        traceback.print_exc()
        return f"【エラー】研究ノートの編集中に予期せぬエラーが発生しました: {e}"
