"""
Arousal正規化プロセスのテスト
"""
import sys
sys.path.insert(0, '/home/baken/nexus_ark')

import json
from pathlib import Path
import tempfile
import shutil

import constants

def test_arousal_normalization():
    """normalize_arousal()メソッドのテスト"""
    
    print("\n=== Arousal正規化テスト ===\n")
    
    # テスト用の一時ルームを作成
    test_room = "test_arousal_normalization"
    test_dir = Path(constants.ROOMS_DIR) / test_room / "memory"
    test_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        from episodic_memory_manager import EpisodicMemoryManager
        
        # テスト1: 平均Arousalが閾値以下 → 正規化しない
        print("テスト1: 平均Arousalが閾値以下（正規化なし）")
        test_episodes_low = [
            {"date": "2026-01-01", "summary": "テスト1", "arousal": 0.3},
            {"date": "2026-01-02", "summary": "テスト2", "arousal": 0.4},
            {"date": "2026-01-03", "summary": "テスト3", "arousal": 0.5},
        ]
        with open(test_dir / "episodic_memory.json", 'w', encoding='utf-8') as f:
            json.dump(test_episodes_low, f)
        
        epm = EpisodicMemoryManager(test_room)
        result = epm.normalize_arousal()
        
        assert result["normalized"] == False, f"閾値以下なのに正規化された: {result}"
        print(f"  ✅ 期待通り正規化スキップ（平均: {result['before_avg']:.2f}）")
        
        # テスト2: 平均Arousalが閾値超過 → 正規化する
        print("\nテスト2: 平均Arousalが閾値超過（正規化実行）")
        test_episodes_high = [
            {"date": "2026-01-01", "summary": "テスト1", "arousal": 0.8},
            {"date": "2026-01-02", "summary": "テスト2", "arousal": 0.7},
            {"date": "2026-01-03", "summary": "テスト3", "arousal": 0.9},
        ]
        with open(test_dir / "episodic_memory.json", 'w', encoding='utf-8') as f:
            json.dump(test_episodes_high, f)
        
        epm = EpisodicMemoryManager(test_room)
        result = epm.normalize_arousal()
        
        assert result["normalized"] == True, f"閾値超過なのに正規化されなかった: {result}"
        assert result["after_avg"] < result["before_avg"], "Arousalが減少していない"
        print(f"  ✅ 正規化実行（平均: {result['before_avg']:.2f} → {result['after_avg']:.2f}）")
        
        # 実際のファイルを読み込んで確認
        with open(test_dir / "episodic_memory.json", 'r', encoding='utf-8') as f:
            saved_data = json.load(f)
        
        for ep in saved_data:
            original = test_episodes_high[[e["date"] for e in test_episodes_high].index(ep["date"])]
            expected = round(original["arousal"] * constants.AROUSAL_NORMALIZATION_FACTOR, 3)
            assert ep["arousal"] == expected, f"Arousalの減衰が不正: {ep['arousal']} != {expected}"
        print(f"  ✅ 各エピソードに減衰係数 {constants.AROUSAL_NORMALIZATION_FACTOR} が適用されている")
        
        # テスト3: 圧縮済みエピソード（arousal_avg）も対象
        print("\nテスト3: 圧縮済みエピソード（arousal_avg）も正規化")
        test_episodes_mixed = [
            {"date": "2026-01-01", "summary": "通常", "arousal": 0.8},
            {"date": "2025-12-01~2025-12-07", "summary": "圧縮済み", "arousal_avg": 0.75, "compressed": True},
        ]
        with open(test_dir / "episodic_memory.json", 'w', encoding='utf-8') as f:
            json.dump(test_episodes_mixed, f)
        
        epm = EpisodicMemoryManager(test_room)
        result = epm.normalize_arousal()
        
        assert result["normalized"] == True, f"正規化されなかった: {result}"
        
        with open(test_dir / "episodic_memory.json", 'r', encoding='utf-8') as f:
            saved_data = json.load(f)
        
        compressed_ep = [ep for ep in saved_data if ep.get("compressed")][0]
        expected_avg = round(0.75 * constants.AROUSAL_NORMALIZATION_FACTOR, 3)
        assert compressed_ep["arousal_avg"] == expected_avg, f"arousal_avgの減衰が不正: {compressed_ep['arousal_avg']} != {expected_avg}"
        print(f"  ✅ 圧縮済みエピソードのarousal_avgも正規化された")
        
        print("\n=== 全テスト成功 ===")
        
    finally:
        # テストルームを削除
        shutil.rmtree(Path(constants.ROOMS_DIR) / test_room, ignore_errors=True)

if __name__ == "__main__":
    test_arousal_normalization()
