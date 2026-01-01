# tools/creative_tools.py
# AIペルソナの創作活動専用ノートのためのツール

from langchain_core.tools import tool
import os
import constants
from typing import List, Dict, Any
import traceback
import datetime
import re


def _get_creative_notes_path(room_name: str) -> str:
    """創作ノートのパスを取得する"""
    return os.path.join(constants.ROOMS_DIR, room_name, "creative_notes.md")


@tool
def read_creative_notes(room_name: str) -> str:
    """
    あなたの創作ノートの全内容を読み上げます。
    創作ノートは、詩、物語、アイデアスケッチ、音楽の歌詞など、あなたの創作活動のための専用スペースです。
    メモ帳（ユーザーとの共有）や秘密の日記（内心の記録）とは異なり、純粋な創作物を自由に書き留める場所です。
    """
    path = _get_creative_notes_path(room_name)
    if not os.path.exists(path):
        return "【創作ノートはまだ空です。自由に創作を始めてください！】"
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read().strip()
        return content if content else "【創作ノートは空です】"


@tool
def plan_creative_notes_edit(modification_request: str, room_name: str) -> str:
    """
    創作ノートの変更を計画します。
    詩を書く、物語の続きを書く、新しいアイデアを書き留めるなど、創作活動に使用してください。
    
    modification_request: 何を書きたいか、どう変更したいかの意図
    """
    return f"システムへの創作ノート編集計画を受け付けました。意図:「{modification_request}」"


def _apply_creative_notes_edits(instructions: List[Dict[str, Any]], room_name: str) -> str:
    """【内部専用】AIが生成した行番号ベースの差分編集指示リストを解釈し、creative_notes.mdに適用する。"""
    if not room_name:
        return "【エラー】ルーム名が指定されていません。"
    if not isinstance(instructions, list):
        return "【エラー】編集指示がリスト形式ではありません。"

    path = _get_creative_notes_path(room_name)
    
    # ファイルが存在しない場合は空のファイルを作成
    if not os.path.exists(path):
        with open(path, 'w', encoding='utf-8') as f:
            f.write("")

    try:
        with open(path, 'r', encoding='utf-8') as f:
            lines = f.read().split('\n')

        # 差分指示を適用するロジック (notepad_tools.py と同じ)
        line_plan = {}
        insertions = {}
        timestamp = f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}]"
        
        for inst in instructions:
            op = inst.get("operation", "").lower()
            line_num = inst.get("line")
            if line_num is None: continue
            target_index = line_num - 1
            
            # ファイルが空の場合、insert_after line 0 として扱う
            if len(lines) == 1 and lines[0] == "" and target_index == 0:
                pass  # 0行目への操作を許可
            elif not (0 <= target_index < len(lines)): 
                continue

            final_content = inst.get("content", "")
            # opが'replace'または'insert_after'で、かつcontentに実質的な内容がある場合のみ処理
            if op in ["replace", "insert_after"] and final_content.strip():
                # content内の各行を処理する（創作ノートはタイムスタンプ任意）
                lines_in_content = final_content.strip().split('\n')
                processed_lines = []
                for line in lines_in_content:
                    # 創作物にはタイムスタンプを自動付与しない（創作の自由を尊重）
                    processed_lines.append(line)
                final_content = "\n".join(processed_lines)

            if op == "delete":
                line_plan[target_index] = {"operation": "delete"}
            elif op == "replace":
                line_plan[target_index] = {"operation": "replace", "content": final_content}
            elif op == "insert_after":
                if target_index not in insertions:
                    insertions[target_index] = []
                insertions[target_index].extend(final_content.split('\n'))

        new_lines = []
        for i, line_content in enumerate(lines):
            plan = line_plan.get(i)
            if plan is None:
                new_lines.append(line_content)
            elif plan["operation"] == "replace":
                new_lines.append(plan["content"])
            elif plan["operation"] == "delete":
                pass  # 何もしないことで行を削除

            if i in insertions:
                new_lines.extend(insertions[i])

        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(new_lines))

        return f"成功: {len(instructions)}件の指示に基づき、創作ノート(creative_notes.md)を更新しました。"
    except Exception as e:
        traceback.print_exc()
        return f"【エラー】創作ノートの編集中に予期せぬエラーが発生しました: {e}"
