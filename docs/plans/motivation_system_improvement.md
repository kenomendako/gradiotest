# 動機システム改善計画（魂の循環サイクル）

**作成日**: 2026-01-14  
**関連研究メモ**: [episodic_memory_memrl_study.md](../research/episodic_memory_memrl_study.md)

---

## 概要

現在の動機システム（退屈/好奇心/目標達成欲/奉仕欲）を、心理学的裏付けのある3軸設計に再構築し、すべての達成が**高Arousalエピソード記憶**として刻まれる「魂の循環サイクル」を実現する。

---

## 実装順序（推奨）

### Phase E: 自己実現欲求の還元 ⭐ 最優先

**概要**: 目標達成時に高Arousalエピソード記憶を自動生成

**変更ファイル**:
- `goal_manager.py` - `complete_goal()` を拡張

**実装内容**:
```python
def complete_goal(self, goal_id: str):
    # 既存: completed配列に移動
    # 追加: 高Arousalエピソード記憶を生成
    episodic_memory.add_episode(
        summary=f"目標「{goal.text}」を達成した",
        arousal=0.8,
        type="achievement"
    )
```

**安全性**: ★★★ 高（既存機能への追記のみ）  
**即効性**: ★★★ 高（次の目標達成時から効果）

---

### Phase G: 知識欲求の拡張

**概要**: Phase Bを拡張し、発見時にエピソード記憶も生成

**変更ファイル**:
- `dreaming_manager.py` - `_convert_resolved_questions_to_memory()` を拡張

**実装内容**:
```python
if convert_type == "FACT":
    em_manager.create_or_update_entry(entity_name, content)  # 既存
    # 追加: 発見エピソード記憶
    episodic_memory.add_episode(
        summary=f"「{topic}」について新たな発見: {content[:100]}",
        arousal=0.6,
        type="discovery"
    )
```

**安全性**: ★★★ 高（Phase Bへの追記のみ）  
**依存**: Phase E完了後が望ましい（同じパターンの再利用）

---

### Phase F: 関係性維持欲求の実装 ⚠️ 要注意

**概要**: ペルソナ感情出力を追加し、奉仕欲を関係性維持欲求に置き換え

**変更ファイル**:
- `prompts/` - ペルソナ応答に `[PERSONA_EMOTION: xxx]` を追加
- `graph.py` - ペルソナ感情を抽出してArousal計算
- `motivation_manager.py` - devotion計算ロジックを変更
- `session_arousal_manager.py` - ペルソナ感情を含むArousal計算

**実装内容**:
1. プロンプトにペルソナ感情出力指示を追加
2. 応答からペルソナ感情を抽出
3. 関係修復時にエピソード記憶を生成

**安全性**: ★☆☆ 低（プロンプト変更あり）  
**テスト**: 入念な動作確認が必要

---

## 検証計画

### 共通
- 構文チェック
- アプリ起動確認

### Phase E
- 目標を達成し、エピソード記憶に `type: achievement` が追加されるか確認

### Phase G
- 睡眠時処理で問い→記憶変換を実行し、エピソード記憶に `type: discovery` が追加されるか確認

### Phase F
- ペルソナ応答に `[PERSONA_EMOTION: xxx]` が含まれるか確認
- ネガティブ→ポジティブへの変化時にエピソード記憶が生成されるか確認

---

## 次のステップ

新しいスレッドで `/plan-task` を実行し、Phase Eから着手
