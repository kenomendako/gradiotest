# session_arousal_manager.py
"""
セッションArousal管理モジュール。
会話ごとのArousalスコアを蓄積し、日次平均を提供する。
"""

import os
import json
import datetime
from typing import Dict, List, Optional
from pathlib import Path

import constants


def get_arousal_file_path(room_name: str) -> Path:
    """Arousal蓄積ファイルのパスを返す"""
    return Path(constants.ROOMS_DIR) / room_name / "memory" / "session_arousal.json"


def _load_arousal_data(room_name: str) -> Dict:
    """Arousal蓄積データを読み込む"""
    path = get_arousal_file_path(room_name)
    if not path.exists():
        return {}
    
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def _save_arousal_data(room_name: str, data: Dict):
    """Arousal蓄積データを保存する"""
    path = get_arousal_file_path(room_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except IOError as e:
        print(f"[SessionArousal] 保存エラー: {e}")


def add_arousal_score(room_name: str, arousal_score: float):
    """
    会話のArousalスコアを蓄積する。
    
    Args:
        room_name: ルーム名
        arousal_score: 会話のArousalスコア（0.0〜1.0）
    """
    today_str = datetime.datetime.now().strftime('%Y-%m-%d')
    data = _load_arousal_data(room_name)
    
    # 今日のデータがなければ初期化
    if today_str not in data:
        data[today_str] = {
            "scores": [],
            "last_updated": None
        }
    
    # スコアを追加
    data[today_str]["scores"].append(round(arousal_score, 3))
    data[today_str]["last_updated"] = datetime.datetime.now().strftime('%H:%M:%S')
    
    # 古いデータを削除（7日以上前）
    cutoff_date = (datetime.datetime.now() - datetime.timedelta(days=7)).strftime('%Y-%m-%d')
    data = {date: values for date, values in data.items() if date >= cutoff_date}
    
    _save_arousal_data(room_name, data)
    print(f"  - [SessionArousal] 蓄積: {arousal_score:.3f} (本日{len(data[today_str]['scores'])}件)")


def get_daily_average(room_name: str, date_str: Optional[str] = None) -> float:
    """
    指定日のArousal平均値を取得する。
    
    Args:
        room_name: ルーム名
        date_str: 日付文字列（デフォルト: 今日）
        
    Returns:
        平均Arousalスコア（0.0〜1.0）。データがなければ0.5を返す。
    """
    if date_str is None:
        date_str = datetime.datetime.now().strftime('%Y-%m-%d')
    
    data = _load_arousal_data(room_name)
    
    if date_str not in data:
        return 0.5  # デフォルト値
    
    scores = data[date_str].get("scores", [])
    if not scores:
        return 0.5
    
    return round(sum(scores) / len(scores), 3)


def get_daily_max(room_name: str, date_str: Optional[str] = None) -> float:
    """
    指定日のArousal最大値を取得する。
    
    Args:
        room_name: ルーム名
        date_str: 日付文字列（デフォルト: 今日）
        
    Returns:
        最大Arousalスコア。データがなければ0.5を返す。
    """
    if date_str is None:
        date_str = datetime.datetime.now().strftime('%Y-%m-%d')
    
    data = _load_arousal_data(room_name)
    
    if date_str not in data:
        return 0.5
    
    scores = data[date_str].get("scores", [])
    if not scores:
        return 0.5
    
    return max(scores)


def clear_daily_data(room_name: str, date_str: Optional[str] = None):
    """
    指定日のArousalデータをクリアする（エピソード記憶生成後に呼び出し）。
    
    Args:
        room_name: ルーム名
        date_str: 日付文字列（デフォルト: 今日）
    """
    if date_str is None:
        date_str = datetime.datetime.now().strftime('%Y-%m-%d')
    
    data = _load_arousal_data(room_name)
    
    if date_str in data:
        del data[date_str]
        _save_arousal_data(room_name, data)
        print(f"  - [SessionArousal] {date_str}のデータをクリア")
