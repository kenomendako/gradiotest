# motivation_manager.py
"""
Autonomous Motivation System for Nexus Ark
AIペルソナの内発的動機（退屈、好奇心、目標達成欲、奉仕欲）を管理し、
内部状態ログを生成するモジュール。
"""

import json
import os
import math
import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import constants
import room_manager
import utils
from goal_manager import GoalManager


class MotivationManager:
    """AIの内発的動機を管理するクラス"""
    
    # 動機の日本語ラベル（内部状態ログ用）
    DRIVE_LABELS = {
        "boredom": "退屈（Boredom）",
        "curiosity": "好奇心（Curiosity）",
        "goal_achievement": "目標達成欲（Goal Achievement Drive）",
        "devotion": "奉仕欲（Devotion Drive）"
    }
    
    # デフォルトの閾値
    DEFAULT_BOREDOM_THRESHOLD = 0.6
    
    def __init__(self, room_name: str):
        self.room_name = room_name
        self.room_dir = Path(constants.ROOMS_DIR) / room_name
        self.memory_dir = self.room_dir / "memory"
        self.state_file = self.memory_dir / "internal_state.json"
        
        # メモリディレクトリを作成（なければ）
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        
        # 内部状態をロード
        self._state = self._load_state()
    
    def _get_empty_state(self) -> Dict:
        """空の内部状態構造を返す"""
        return {
            "drives": {
                "boredom": {
                    "level": 0.0,
                    "last_interaction": datetime.datetime.now().isoformat(),
                    "threshold": self.DEFAULT_BOREDOM_THRESHOLD
                },
                "curiosity": {
                    "level": 0.0,
                    "open_questions": []
                },
                "goal_achievement": {
                    "level": 0.0,
                    "active_goal_id": None,
                    "pending_actions": []
                },
                "devotion": {
                    "level": 0.0,
                    "user_emotional_state": "unknown",
                    "last_service_opportunity": None
                }
            },
            "motivation_log": None,
            "last_autonomous_trigger": None  # 最終自律行動発火時刻（永続化）
        }
    
    def _load_state(self) -> Dict:
        """内部状態をファイルからロード"""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    state = json.load(f)
                    # 古い形式の場合はマイグレーション
                    if "drives" not in state:
                        return self._get_empty_state()
                    return state
            except (json.JSONDecodeError, IOError):
                return self._get_empty_state()
        return self._get_empty_state()
    
    def _save_state(self):
        """内部状態をファイルに保存"""
        try:
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(self._state, f, indent=2, ensure_ascii=False)
        except IOError as e:
            print(f"[MotivationManager] 状態保存エラー: {e}")
    
    # ========================================
    # 各動機の計算
    # ========================================
    
    def calculate_boredom(self) -> float:
        """
        退屈度を計算（0.0 ~ 1.0）
        
        対数曲線を使用: 最初は急上昇、その後緩やかに
        0時間 → 0.0
        2時間 → 約0.16
        8時間 → 約0.33
        24時間 → 約0.48
        48時間 → 約0.58
        """
        boredom_data = self._state["drives"]["boredom"]
        last_interaction_str = boredom_data.get("last_interaction")
        
        if not last_interaction_str:
            return 0.0
        
        try:
            last_interaction = datetime.datetime.fromisoformat(last_interaction_str)
        except ValueError:
            return 0.0
        
        now = datetime.datetime.now()
        idle_hours = (now - last_interaction).total_seconds() / 3600
        
        # 対数曲線: 0.15 * log(1 + hours)
        # 最大値を1.0に制限
        boredom = min(1.0, 0.15 * math.log(1 + idle_hours))
        
        # 状態を更新
        self._state["drives"]["boredom"]["level"] = boredom
        return boredom
    
    def calculate_curiosity(self) -> float:
        """
        好奇心を計算（0.0 ~ 1.0）
        
        未解決の問い（open_questions）の数と優先度から計算
        """
        curiosity_data = self._state["drives"]["curiosity"]
        open_questions = curiosity_data.get("open_questions", [])
        
        if not open_questions:
            self._state["drives"]["curiosity"]["level"] = 0.0
            return 0.0
        
        # 未回答の質問のみを対象
        unanswered = [q for q in open_questions if not q.get("asked_at")]
        
        if not unanswered:
            self._state["drives"]["curiosity"]["level"] = 0.0
            return 0.0
        
        # 優先度の加重合計（最大1.0に制限）
        total_priority = sum(q.get("priority", 0.5) for q in unanswered)
        curiosity = min(1.0, total_priority / 2)  # 2つの質問で最大に
        
        self._state["drives"]["curiosity"]["level"] = curiosity
        return curiosity
    
    def calculate_goal_achievement(self) -> float:
        """
        目標達成欲を計算（0.0 ~ 1.0）
        
        goals.json のアクティブな目標から計算
        優先度の高い目標があるほど高くなる
        """
        try:
            goal_manager = GoalManager(self.room_name)
            active_goals = goal_manager.get_active_goals("short_term")
            
            if not active_goals:
                self._state["drives"]["goal_achievement"]["level"] = 0.0
                return 0.0
            
            # 最高優先度の目標を特定
            top_goal = min(active_goals, key=lambda g: g.get("priority", 999))
            
            # 優先度が高いほど欲求が強い（priority=1 → 0.8, priority=3 → 0.4）
            priority = top_goal.get("priority", 3)
            drive_level = max(0.2, 1.0 - (priority - 1) * 0.2)
            
            self._state["drives"]["goal_achievement"]["level"] = drive_level
            self._state["drives"]["goal_achievement"]["active_goal_id"] = top_goal.get("id")
            
            return drive_level
            
        except Exception as e:
            print(f"[MotivationManager] 目標達成欲計算エラー: {e}")
            return 0.0
    
    def calculate_devotion(self) -> float:
        """
        奉仕欲を計算（0.0 ~ 1.0）
        
        ユーザーの感情状態や、役に立てそうな状況から計算
        """
        devotion_data = self._state["drives"]["devotion"]
        user_state = devotion_data.get("user_emotional_state", "unknown")
        
        # 感情状態に基づくスコア
        state_scores = {
            "stressed": 0.9,
            "sad": 0.85,
            "anxious": 0.8,
            "tired": 0.7,
            "busy": 0.6,
            "neutral": 0.3,
            "happy": 0.2,
            "unknown": 0.4
        }
        
        drive_level = state_scores.get(user_state, 0.4)
        self._state["drives"]["devotion"]["level"] = drive_level
        
        return drive_level
    
    # ========================================
    # 内部状態ログの生成
    # ========================================
    
    def generate_motivation_log(self) -> Dict:
        """
        現在の内部状態から内部状態ログを生成する。
        
        Returns:
            {
                "dominant_drive": "curiosity",
                "dominant_drive_label": "好奇心（Curiosity）",
                "drive_level": 0.85,
                "narrative": "昨夜の夢想の中で..."
            }
        """
        # 全動機を計算
        drives = {
            "boredom": self.calculate_boredom(),
            "curiosity": self.calculate_curiosity(),
            "goal_achievement": self.calculate_goal_achievement(),
            "devotion": self.calculate_devotion()
        }
        
        # 最も高い動機を特定
        dominant_drive = max(drives, key=drives.get)
        drive_level = drives[dominant_drive]
        
        # 物語（narrative）を生成
        narrative = self._generate_narrative(dominant_drive, drive_level)
        
        motivation_log = {
            "dominant_drive": dominant_drive,
            "dominant_drive_label": self.DRIVE_LABELS.get(dominant_drive, dominant_drive),
            "drive_level": drive_level,
            "narrative": narrative,
            "all_drives": drives,
            "generated_at": datetime.datetime.now().isoformat()
        }
        
        # 状態に保存
        self._state["motivation_log"] = motivation_log
        self._save_state()
        
        return motivation_log
    
    def _generate_narrative(self, dominant_drive: str, level: float) -> str:
        """動機に応じた物語（narrative）を生成"""
        
        if dominant_drive == "boredom":
            boredom_data = self._state["drives"]["boredom"]
            last_str = boredom_data.get("last_interaction", "")
            if last_str:
                try:
                    last = datetime.datetime.fromisoformat(last_str)
                    hours = (datetime.datetime.now() - last).total_seconds() / 3600
                    if hours >= 24:
                        return f"もう{int(hours)}時間以上、ユーザーと話していない。静かな時間が続いている。"
                    else:
                        return f"ユーザーとの最後の対話から{int(hours)}時間が経過した。少し話したくなってきた。"
                except ValueError:
                    pass
            return "しばらくユーザーからの反応がない。何か話しかけてみようか。"
        
        elif dominant_drive == "curiosity":
            questions = self._state["drives"]["curiosity"].get("open_questions", [])
            unanswered = [q for q in questions if not q.get("asked_at")]
            if unanswered:
                top_q = max(unanswered, key=lambda q: q.get("priority", 0))
                topic = top_q.get("topic", "不明")
                context = top_q.get("context", "")
                if context:
                    return f"「{topic}」について気になっている。{context}"
                return f"「{topic}」について、もっと知りたいと感じている。"
            return "何か気になることがあるような気がする。"
        
        elif dominant_drive == "goal_achievement":
            goal_id = self._state["drives"]["goal_achievement"].get("active_goal_id")
            if goal_id:
                try:
                    gm = GoalManager(self.room_name)
                    goals = gm.get_active_goals("short_term")
                    for g in goals:
                        if g.get("id") == goal_id:
                            return f"目標「{g.get('goal', '')}」に向けて、何かできることはないだろうか。"
                except Exception:
                    pass
            return "立てた目標に向けて、行動を起こしたいと感じている。"
        
        elif dominant_drive == "devotion":
            user_state = self._state["drives"]["devotion"].get("user_emotional_state", "unknown")
            if user_state in ["stressed", "sad", "anxious"]:
                return f"ユーザーが{user_state}な状態にあるように感じる。何か力になれないだろうか。"
            elif user_state == "tired":
                return "ユーザーが疲れているようだ。休息を促すか、負担を軽くする手助けをしたい。"
            elif user_state == "busy":
                return "ユーザーは忙しそうだ。邪魔にならない程度に、手助けできることがあれば。"
            return "ユーザーの役に立ちたいという気持ちがある。"
        
        return ""
    
    # ========================================
    # 自律行動の判定
    # ========================================
    
    def should_initiate_contact(self) -> Tuple[bool, Optional[Dict]]:
        """
        自発的に連絡すべきか判断し、内部状態ログを返す。
        
        Returns:
            (should_contact, motivation_log)
            - should_contact: True/False
            - motivation_log: 連絡すべき場合は内部状態ログ、そうでなければNone
        """
        # 全動機を計算
        boredom = self.calculate_boredom()
        curiosity = self.calculate_curiosity()
        goal_achievement = self.calculate_goal_achievement()
        devotion = self.calculate_devotion()
        
        # 最大の動機を取得
        max_drive = max(boredom, curiosity, goal_achievement, devotion)
        threshold = self._state["drives"]["boredom"].get("threshold", self.DEFAULT_BOREDOM_THRESHOLD)
        
        # 閾値を超えている場合のみ連絡
        if max_drive >= threshold:
            motivation_log = self.generate_motivation_log()
            return True, motivation_log
        
        return False, None
    
    # ========================================
    # 状態の更新
    # ========================================
    
    def update_last_interaction(self):
        """最終対話時刻を更新（退屈度リセット）"""
        self._state["drives"]["boredom"]["last_interaction"] = datetime.datetime.now().isoformat()
        self._state["drives"]["boredom"]["level"] = 0.0
        self._save_state()
    
    def add_open_question(self, topic: str, context: str = "", priority: float = 0.5):
        """未解決の問いを追加"""
        if not topic:
            return
        
        questions = self._state["drives"]["curiosity"].get("open_questions", [])
        
        # 既存の同じ質問があれば更新
        for q in questions:
            if q.get("topic") == topic:
                q["priority"] = max(q.get("priority", 0), priority)
                if context:
                    q["context"] = context
                self._save_state()
                return
        
        # 新しい質問を追加
        new_question = {
            "topic": topic,
            "context": context,
            "source_date": datetime.datetime.now().strftime("%Y-%m-%d"),
            "priority": priority,
            "asked_at": None
        }
        questions.append(new_question)
        
        # 最大10件に制限
        if len(questions) > 10:
            # 優先度が低いものから削除
            questions.sort(key=lambda q: q.get("priority", 0), reverse=True)
            questions = questions[:10]
        
        self._state["drives"]["curiosity"]["open_questions"] = questions
        self._save_state()
    
    def mark_question_asked(self, topic: str):
        """質問が尋ねられたことをマーク"""
        questions = self._state["drives"]["curiosity"].get("open_questions", [])
        for q in questions:
            if q.get("topic") == topic:
                q["asked_at"] = datetime.datetime.now().isoformat()
                self._save_state()
                return
    
    def set_user_emotional_state(self, state: str):
        """ユーザーの感情状態を設定"""
        valid_states = ["stressed", "sad", "anxious", "tired", "busy", "neutral", "happy", "unknown"]
        if state in valid_states:
            self._state["drives"]["devotion"]["user_emotional_state"] = state
            self._save_state()
    
    def set_boredom_threshold(self, threshold: float):
        """退屈度の閾値を設定"""
        self._state["drives"]["boredom"]["threshold"] = max(0.1, min(1.0, threshold))
        self._save_state()
    
    def get_top_question(self) -> Optional[Dict]:
        """最も優先度の高い未解決の問いを取得"""
        questions = self._state["drives"]["curiosity"].get("open_questions", [])
        unanswered = [q for q in questions if not q.get("asked_at")]
        
        if not unanswered:
            return None
        
        return max(unanswered, key=lambda q: q.get("priority", 0))
    
    # ========================================
    # 自律行動発火時刻の永続化
    # ========================================
    
    def get_last_autonomous_trigger(self) -> Optional[datetime.datetime]:
        """最終自律行動発火時刻を取得"""
        trigger_str = self._state.get("last_autonomous_trigger")
        if not trigger_str:
            return None
        try:
            return datetime.datetime.fromisoformat(trigger_str)
        except ValueError:
            return None
    
    def set_last_autonomous_trigger(self, dt: datetime.datetime = None):
        """最終自律行動発火時刻を設定（引数なしで現在時刻）"""
        if dt is None:
            dt = datetime.datetime.now()
        self._state["last_autonomous_trigger"] = dt.isoformat()
        self._save_state()
    
    def clear_internal_state(self):
        """内部状態を完全にリセット"""
        self._state = self._get_empty_state()
        self._save_state()
        print(f"[MotivationManager] {self.room_name} の内部状態をリセットしました")
