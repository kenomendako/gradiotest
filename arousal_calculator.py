# arousal_calculator.py
"""
Arousal（感情的重要度）計算モジュール。
会話の内部状態変化からArousalスコアを計算する。

Arousalは会話の「感情的・知的インパクト」を0.0〜1.0で数値化したもの。
将来的にエピソード記憶の圧縮・検索での重み付けに使用する。
"""

from typing import Dict


def calculate_arousal(before: Dict, after: Dict) -> float:
    """
    内部状態の変化量からArousalスコアを計算する。
    
    Args:
        before: 会話開始時の内部状態スナップショット
        after: 会話終了時の内部状態スナップショット
        
    Returns:
        Arousalスコア（0.0〜1.0）
    """
    
    # --- 1. 好奇心の変化 = 知的興奮 ---
    curiosity_before = before.get("curiosity", 0.0)
    curiosity_after = after.get("curiosity", 0.0)
    curiosity_delta = abs(curiosity_after - curiosity_before)
    
    # --- 2. 奉仕欲の変化 = 深い関わり ---
    devotion_before = before.get("devotion", 0.0)
    devotion_after = after.get("devotion", 0.0)
    devotion_delta = abs(devotion_after - devotion_before)
    
    # --- 3. ユーザー感情の変化 ---
    # 感情カテゴリをスコア化（強い感情ほど高スコア）
    emotion_scores = {
        "happy": 0.6,
        "sad": 0.8,
        "stressed": 0.9,
        "anxious": 0.8,
        "tired": 0.5,
        "neutral": 0.2,
        "unknown": 0.2
    }
    
    before_emotion = before.get("user_emotional_state", "unknown")
    after_emotion = after.get("user_emotional_state", "unknown")
    
    before_score = emotion_scores.get(before_emotion, 0.2)
    after_score = emotion_scores.get(after_emotion, 0.2)
    emotion_delta = abs(after_score - before_score)
    
    # --- 4. 感情の絶対的強度も考慮 ---
    # ユーザーが強い感情を持っている場合、それ自体が重要
    emotion_intensity = max(before_score, after_score)
    if emotion_intensity >= 0.7:
        emotion_delta = max(emotion_delta, 0.3)  # 最低限の重要度を保証
    
    # --- 5. 複合Arousalスコア ---
    raw_arousal = (
        curiosity_delta * 0.30 +
        emotion_delta * 0.40 +
        devotion_delta * 0.30
    )
    
    # スケール調整（変化が小さくてもある程度のスコアが出るように）
    arousal = min(1.0, raw_arousal * 2.5)
    
    return round(arousal, 3)


def get_arousal_level(score: float) -> str:
    """
    Arousalスコアを人間が読みやすいレベルに変換する。
    
    Args:
        score: Arousalスコア（0.0〜1.0）
        
    Returns:
        レベル文字列（low, medium, high, very_high）
    """
    if score < 0.25:
        return "low"
    elif score < 0.5:
        return "medium"
    elif score < 0.75:
        return "high"
    else:
        return "very_high"
