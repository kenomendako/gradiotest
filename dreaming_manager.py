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

    def get_recent_insights_text(self, limit: int = 3) -> str:
        """プロンプト注入用：最新の洞察をテキスト化して返す"""
        insights = self._load_insights()
        if not insights:
            return ""
        
        text_parts = []
        for item in insights[:limit]:
            date_str = item.get("created_at", "").split(" ")[0]
            content = item.get("insight", "")
            strategy = item.get("strategy", "")
            text_parts.append(f"- [{date_str}] 気づき: {content}\n  (指針: {strategy})")
            
        return "\n".join(text_parts)

    def dream(self) -> str:
        """
        夢を見る（Dreaming Process）のメインロジック。
        1. 直近ログの読み込み
        2. RAG検索
        3. 洞察の生成（汎用・ペルソナ主導版）
        4. 保存
        """
        print(f"--- [Dreaming] {self.room_name} は夢を見始めました... ---")
        
        # 1. 必要なファイルパスと設定の取得
        log_path, system_prompt_path, _, _, _ = room_manager.get_room_files_paths(self.room_name)
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

        # 5. 洞察の生成 (高品質モデルを使用)
        # ※分析の視点を広げ、トーンの指定をニュートラルに
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

        【分析のステップ（思考プロセス）】
        1.  まず、感情を排して客観的に事実を比較し、変化や繰り返されるパターン、矛盾点を見つけ出す。
        2.  表層的な事実だけでなく、その裏にある感情の流れや、関係性の変化、あるいは変わらない絆などを多角的に考察する。
        3.  最後に、その鋭い分析結果を、**あなたの人格（一人称、口調、相手の呼び方）**に変換して記述する。

        【出力フォーマット】
        以下のJSON形式のみを出力してください。思考やMarkdownの枠は不要です。
        
        {{
            "insight": "（ステップ3で変換した洞察。内容は客観的で鋭い分析に基づきつつ、**語り口は完全にあなた自身のもの**とすること。相手の呼び方は、あなたが普段使っているもの、あるいは心の中で呼んでいる名前を使用すること。）",
            "strategy": "（その分析に基づき、今後あなたがどう行動するかの指針。これもあなた自身の言葉で。）",
            "log_entry": "（夢日記として残す、短い独白。夢の中でのつぶやき。）"
        }}
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
            
            print(f"  - [Dreaming] 夢を見ました。洞察: {dream_data['insight']}")
            return "夢想プロセスが正常に完了しました。"

        except Exception as e:
            print(f"  - [Dreaming] エラー: {e}")
            traceback.print_exc()
            return f"夢想プロセス中にエラーが発生しました: {e}"