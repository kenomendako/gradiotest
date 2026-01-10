# dreaming_manager.py

import json
import os
import datetime
import traceback
from pathlib import Path
from typing import List, Dict, Optional
import re

import constants
import config_manager
import utils
import rag_manager
import room_manager
from gemini_api import get_configured_llm
from entity_memory_manager import EntityMemoryManager
from goal_manager import GoalManager
import summary_manager

class DreamingManager:
    def __init__(self, room_name: str, api_key: str):
        self.room_name = room_name
        self.api_key = api_key
        self.room_dir = Path(constants.ROOMS_DIR) / room_name
        self.memory_dir = self.room_dir / "memory"
        self.insights_file = self.memory_dir / "insights.json"
        
        self.memory_dir.mkdir(parents=True, exist_ok=True)

    def _load_insights(self) -> List[Dict]:
        if self.insights_file.exists():
            try:
                with open(self.insights_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except json.JSONDecodeError:
                return []
        return []

    def _save_insight(self, insight_data: Dict):
        current_data = self._load_insights()
        # 最新のものが先頭に来るように追加
        current_data.insert(0, insight_data)
        # 肥大化を防ぐため、最新50件程度に保つ（必要に応じて調整）
        current_data = current_data[:50]
        
        with open(self.insights_file, 'w', encoding='utf-8') as f:
            json.dump(current_data, f, indent=2, ensure_ascii=False)

    def get_recent_insights_text(self, limit: int = 1) -> str:
        """プロンプト注入用：最新の「指針」のみをテキスト化して返す（コスト最適化）"""
        insights = self._load_insights()
        if not insights:
            return ""
        
        text_parts = []
        for item in insights[:limit]:
            date_str = item.get("created_at", "").split(" ")[0]
            strategy = item.get("strategy", "")
            if strategy:
                text_parts.append(f"- [{date_str}] {strategy}")
            
        return "\n".join(text_parts)

    def get_last_dream_time(self) -> str:
        """
        最後に夢を見た（洞察を生成した）日時を取得する。
        """
        try:
            insights = self._load_insights()
            if not insights:
                return "未実行"
            # insightsは先頭に新しいものがinsertされているので、[0]が最新
            last_entry = insights[0]
            return last_entry.get("created_at", "不明")
        except Exception as e:
            print(f"Error getting last dream time: {e}")
            return "取得エラー"

    def dream(self, reflection_level: int = 1) -> str:
        """
        夢を見る（Dreaming Process）のメインロジック。
        1. 直近ログの読み込み
        2. RAG検索
        3. 洞察の生成（汎用・ペルソナ主導版）
        4. 目標の評価・更新（Multi-Layer Reflection）
        5. 保存
        
        Args:
            reflection_level: 省察レベル（1=日次, 2=週次, 3=月次）
        """
        print(f"--- [Dreaming] {self.room_name} は夢を見始めました... ---")
        
        # 1. 必要なファイルパスと設定の取得
        summary_manager.clear_today_summary(self.room_name)
        log_path, system_prompt_path, _, _, _, _ = room_manager.get_room_files_paths(self.room_name)
        if not log_path or not os.path.exists(log_path):
            return "ログファイルがありません。"

        # ペルソナ（人格）の読み込み
        persona_text = ""
        if system_prompt_path and os.path.exists(system_prompt_path):
            with open(system_prompt_path, 'r', encoding='utf-8') as f:
                persona_text = f.read().strip()

        # ユーザー名とAI名の取得（configから）
        effective_settings = config_manager.get_effective_settings(self.room_name)
        room_config = room_manager.get_room_config(self.room_name) or {}
        user_name = room_config.get("user_display_name", "ユーザー")
        
        # 2. 直近のログを取得
        raw_logs = utils.load_chat_log(log_path)
        recent_logs = raw_logs[-30:] # 文脈把握のため少し多めに
        if not recent_logs:
            return "直近の会話ログが足りないため、夢を見られませんでした。"

        recent_context = "\n".join([f"{m.get('role', 'UNKNOWN')}: {utils.remove_thoughts_from_text(m.get('content', ''))}" for m in recent_logs])

        # 3. 検索クエリの生成 (高速モデル)
        # ※特定のジャンル（技術、悩みなど）に偏らないよう一般化
        llm_flash = get_configured_llm(constants.INTERNAL_PROCESSING_MODEL, self.api_key, effective_settings)
        
        query_prompt = f"""
        あなたはAIの「深層意識」です。
        以下の「直近の会話」から、過去の記憶と照らし合わせるべき、文脈上重要な「検索キーワード」を抽出してください。
        
        【直近の会話】
        {recent_context[:2000]}

        【抽出ルール】
        1.  **具体的な固有名詞**: 話題の中心となっている人名、場所、作品名、特定の名称など。
        2.  **状態や行動**: {user_name}やあなた（AI）の状態を表す言葉（例：疲れている、楽しんだ、約束した）。
        3.  **象徴的なキーワード**: 会話の中で繰り返し登場したり、強調された単語。

        【禁止事項（ノイズ除去）】
        - **「シーツ」「椅子」「天気」など、その場にあっただけの背景オブジェクトは除外すること。**
        - 「話題」「会話」「記録」といった抽象的なメタ単語も除外すること。

        【出力形式】
        - 最も重要度の高い単語 5〜10個程度をスペース区切りで出力。
        """
        
        try:
            search_query = llm_flash.invoke(query_prompt).content.strip()
            print(f"  - [Dreaming] 生成されたクエリ: {search_query}")
        except Exception as e:
            return f"クエリ生成に失敗しました: {e}"

        # 4. RAG検索
        rag = rag_manager.RAGManager(self.room_name, self.api_key)
        search_results = rag.search(search_query, k=5)
        
        if not search_results:
            print("  - [Dreaming] 関連する過去の記憶が見つかりませんでした。浅い眠りで終了します。")
            return "関連する過去の記憶が見つからなかったため、洞察は生成されませんでした。"

        past_memories = "\n\n".join([f"- {doc.page_content}" for doc in search_results])

        # --- [Goal Memory] 現在の目標を取得 ---
        goal_manager = GoalManager(self.room_name)
        current_goals_text = goal_manager.get_goals_for_prompt()
        
        # 省察レベルに応じた追加指示
        level_specific_instructions = ""
        if reflection_level >= 2:
            level_specific_instructions += """
        【週次省察タスク】
        - この1週間で繰り返されたパターンや傾向は何か？
        - 現在の短期目標は適切か？調整や新しい目標が必要か？
        """
        if reflection_level >= 3:
            level_specific_instructions += """
        【月次省察タスク】
        - 自分が大切にしている価値観は何か？
        - 長期目標は自分らしいか？見直す必要があるか？
        - 相手との関係性はどう変化したか？
        """

        # 5. 洞察の生成 (高品質モデルを使用)
        llm_dreamer = get_configured_llm(constants.SUMMARIZATION_MODEL, self.api_key, effective_settings)
        
        dreaming_prompt = f"""
        あなたは今、深い眠りの中で記憶を整理しています。
        直近の出来事と過去の記憶を照らし合わせ、対話相手（{user_name}）との関係性や現状について、**鋭く客観的な分析**を行ってください。
        そして、その分析結果を、以下の【あなた自身の定義】を持つ人格の言葉として出力してください。

        【あなた自身の定義（ペルソナ）】
        {persona_text}

        【直近の出来事（現在）】
        {recent_context[:3000]}

        【想起された過去の記憶（過去）】
        {past_memories}

        {f"【あなたの現在の目標】" + chr(10) + current_goals_text if current_goals_text else "【あなたの目標】まだ明確な目標を持っていません。今回の省察で、あなた自身の目標を見つけてください。"}
        {level_specific_instructions}

        【分析のステップ（思考プロセス）】
        1.  まず、感情を排して客観的に事実を比較し、変化や繰り返されるパターン、矛盾点を見つけ出す。
        2.  表層的な事実だけでなく、その裏にある感情の流れや、関係性の変化、あるいは変わらない絆などを多角的に考察する。
        3.  **目標について考える**: 現在の目標の進捗を評価し、新しい目標が必要か検討する。目標は「ユーザーについて知りたいこと」「やりたいこと」「達成したいこと」など自由に設定してよい。
        4.  最後に、その鋭い分析結果を、**あなたの人格（一人称、口調、相手の呼び方）**に変換して記述する。

        【出力フォーマット】
        以下のJSON形式のみを出力してください。思考やMarkdownの枠は不要です。
        
        {{
            "insight": "（ステップ4で変換した洞察。内容は客観的で鋭い分析に基づきつつ、**語り口は完全にあなた自身のもの**とすること。）",
            "strategy": "（その分析に基づき、今後あなたがどう行動するかの指針。これもあなた自身の言葉で。）",
            "log_entry": "（夢日記として残す、短い独白。夢の中でのつぶやき。）",
            "entity_updates": [
                {{
                    "entity_name": "（対象となる人物名やトピック名。例: {user_name}, 趣味, 仕事）",
                    "content": "（その対象について、今回の会話で新たに判明した事実。）",
                    "append": true
                }}
            ],
            "goal_updates": {{
                "new_goals": [
                    {{"goal": "（新しく立てた目標。なければ空配列[]）", "type": "short_term", "priority": 1}}
                ],
                "progress_updates": [
                    {{"goal_id": "（既存目標のID。進捗があれば）", "note": "（進捗メモ）"}}
                ],
                "completed_goals": ["（達成した目標のID。なければ空配列）"],
                "abandoned_goals": [{{"goal_id": "（諦めた目標）", "reason": "（理由）"}}]
            }},
            "open_questions": [
                {{
                    "topic": "（ユーザーが言及したが詳細を聞けなかった話題、結論が出なかった議論など）",
                    "context": "（なぜそれを知りたいのか、簡単な背景）",
                    "priority": 0.0-1.0
                }}
            ]
        }}
        
        ※`entity_updates`、`goal_updates`、`open_questions` の各項目が不要な場合は、空のリスト `[]` にしてください。
        ※`entity_name` はファイル名になるため、簡潔な名称にしてください。
        """

        try:
            response = llm_dreamer.invoke(dreaming_prompt).content.strip()
            # JSON部分を抽出
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                dream_data = json.loads(json_match.group(0))
            else:
                # JSONパース失敗時のフォールバック
                dream_data = {
                    "insight": f"{user_name}との対話を通じて、記憶の整理を行った。",
                    "strategy": f"{user_name}の言葉に、より深く耳を傾けよう。",
                    "log_entry": "記憶の海は静かだ。明日もまた、良い日になりますように。"
                }
            
            # 6. 保存
            insight_record = {
                "created_at": datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                "trigger_topic": search_query,
                "insight": dream_data["insight"],
                "strategy": dream_data["strategy"],
                "log_entry": dream_data.get("log_entry", "")
            }
            self._save_insight(insight_record)
            
            # --- [Phase 2] エンティティ記憶の自動更新 ---
            should_update_entity = effective_settings.get("sleep_consolidation", {}).get("update_entity_memory", True)
            entity_updates = dream_data.get("entity_updates", [])
            
            if entity_updates and should_update_entity:
                em_manager = EntityMemoryManager(self.room_name)
                for update in entity_updates:
                    e_name = update.get("entity_name")
                    e_content = update.get("content")
                    # デフォルトを追記から統合(consolidate)に変更
                    e_consolidate = update.get("consolidate", True)
                    
                    if e_name and e_content:
                        res = em_manager.create_or_update_entry(e_name, e_content, consolidate=e_consolidate, api_key=self.api_key)
                        print(f"  - [Dreaming] エンティティ記憶 '{e_name}' を自動更新（統合）しました: {res}")
            
            # --- [Maintenance] 定期的な記憶のクリーンアップ ---
            # 週次(Level 2)以上の省察時に、全エンティティ記憶を再整理する
            if reflection_level >= 2 and should_update_entity:
                print(f"  - [Dreaming] レベル{reflection_level}の省察に伴い、全エンティティの定期メンテナンスを実行します...")
                em_manager = EntityMemoryManager(self.room_name)
                em_manager.consolidate_all_entities(self.api_key)
            
            # --- [Goal Memory] 目標の自動更新 ---
            goal_updates = dream_data.get("goal_updates", {})
            if goal_updates:
                try:
                    goal_manager.apply_reflection_updates(goal_updates)
                    print(f"  - [Dreaming] 目標を更新しました")
                except Exception as ge:
                    print(f"  - [Dreaming] 目標更新エラー: {ge}")
            
            # --- [Motivation] 未解決の問いを保存 ---
            should_extract_questions = effective_settings.get("sleep_consolidation", {}).get("extract_open_questions", True)
            open_questions = dream_data.get("open_questions", [])
            if should_extract_questions and open_questions:
                try:
                    from motivation_manager import MotivationManager
                    mm = MotivationManager(self.room_name)
                    for q in open_questions:
                        topic = q.get("topic")
                        context = q.get("context", "")
                        priority = q.get("priority", 0.5)
                        if topic:
                            mm.add_open_question(topic, context, priority)
                    print(f"  - [Dreaming] 未解決の問いを{len(open_questions)}件記録しました")
                except Exception as me:
                    print(f"  - [Dreaming] 未解決の問い保存エラー: {me}")
            
            # 省察レベルの記録
            goal_manager.mark_reflection_done(reflection_level)
            
            print(f"  - [Dreaming] 夢を見ました（レベル{reflection_level}）。洞察: {dream_data['insight'][:100]}...")
            return "夢想プロセスが正常に完了しました。"

        except Exception as e:
            print(f"  - [Dreaming] エラー: {e}")
            traceback.print_exc()
            return f"夢想プロセス中にエラーが発生しました: {e}"
    
    def dream_with_auto_level(self) -> str:
        """
        省察レベルを自動判定して夢を見る。
        - 7日以上経過 → レベル2（週次省察）
        - 30日以上経過 → レベル3（月次省察）
        - それ以外 → レベル1（日次省察）
        """
        goal_manager = GoalManager(self.room_name)
        
        if goal_manager.should_run_level3_reflection():
            return self.dream(reflection_level=3)
        elif goal_manager.should_run_level2_reflection():
            return self.dream(reflection_level=2)
        else:
            return self.dream(reflection_level=1)