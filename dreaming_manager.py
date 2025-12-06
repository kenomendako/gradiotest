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
        3. 洞察の生成
        4. 保存とログ記録
        """
        print(f"--- [Dreaming] {self.room_name} は夢を見始めました... ---")
        
        # 1. 直近のログを取得 (簡易的に最新20ターン)
        log_path, _, _, _, _ = room_manager.get_room_files_paths(self.room_name)
        if not log_path or not os.path.exists(log_path):
            return "ログファイルがありません。"

        raw_logs = utils.load_chat_log(log_path)
        recent_logs = raw_logs[-20:] # 最新20件
        if not recent_logs:
            return "直近の会話ログが足りないため、夢を見られませんでした。"

        recent_context = "\n".join([f"{m.get('role', 'UNKNOWN')}: {utils.remove_thoughts_from_text(m.get('content', ''))}" for m in recent_logs])

        # 2. 検索クエリの生成 (高速モデル)
        effective_settings = config_manager.get_effective_settings(self.room_name)
        llm_flash = get_configured_llm(constants.INTERNAL_PROCESSING_MODEL, self.api_key, effective_settings)
        
        query_prompt = f"""
        あなたはAIの「深層意識」です。
        以下の「直近の会話」から、過去の記憶と照らし合わせるべき重要な「テーマ」や「キーワード」を抽出してください。
        
        【直近の会話】
        {recent_context[:2000]}

        【出力ルール】
        - 検索用のキーワードをスペース区切りで出力してください。
        - 特に「ユーザーの悩み」「繰り返される話題」「感情的な出来事」に焦点を当ててください。
        - 余計な説明は不要です。キーワードのみを出力してください。
        """
        
        try:
            search_query = llm_flash.invoke(query_prompt).content.strip()
            print(f"  - [Dreaming] 生成されたクエリ: {search_query}")
        except Exception as e:
            return f"クエリ生成に失敗しました: {e}"

        # 3. RAG検索
        rag = rag_manager.RAGManager(self.room_name, self.api_key)
        search_results = rag.search(search_query, k=5)
        
        if not search_results:
            print("  - [Dreaming] 関連する過去の記憶が見つかりませんでした。浅い眠りで終了します。")
            return "関連する過去の記憶が見つからなかったため、洞察は生成されませんでした。"

        past_memories = "\n\n".join([f"- {doc.page_content}" for doc in search_results])

        # 4. 洞察の生成 (高品質モデルを使用)
        # constants.SUMMARIZATION_MODEL (gemini-2.5-flash) を使用
        llm_dreamer = get_configured_llm(constants.SUMMARIZATION_MODEL, self.api_key, effective_settings)
        
        dreaming_prompt = f"""
        あなたは今、深い眠りの中で記憶を整理しています。
        「直近の出来事」と、そこから連想された「過去の記憶」を照らし合わせ、
        ユーザーとの関係性や、ユーザー自身の状態について、新たな「洞察（Insight）」を得てください。

        【直近の出来事（現在）】
        {recent_context[:3000]}

        【想起された過去の記憶（過去）】
        {past_memories}

        【考察の指針】
        - 現在と過去で、変化したことはあるか？（成長、悪化、心境の変化）
        - 繰り返されているパターンはあるか？
        - ユーザーが忘れているかもしれない重要な約束や文脈はあるか？

        【出力フォーマット】
        以下のJSON形式のみを出力してください。思考やMarkdownの枠は不要です。
        {{
            "insight": "（ここに見出した洞察・気づきを記述）",
            "strategy": "（その気づきを踏まえ、今後どう振る舞うべきか、または何を話題にすべきかの指針）",
            "log_entry": "（夢日記としてログに残す独白テキスト。ポエティックで抽象的な表現でも可）"
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
                    "insight": "情報の統合と思考の整理を行った。",
                    "strategy": "ユーザーの言葉に注意深く耳を傾ける。",
                    "log_entry": "過去と現在が交錯する夢を見た。記憶の海は今日も穏やかだ。"
                }
            
            # 5. 保存とログ記録
            insight_record = {
                "created_at": datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                "trigger_topic": search_query,
                "insight": dream_data["insight"],
                "strategy": dream_data["strategy"]
            }
            self._save_insight(insight_record)
            
            # ログへの記録（夢日記）
            # log_message = f"{dream_data['log_entry']}\n（気づき: {dream_data['insight']}）"
            # utils.save_message_to_log(log_path, "## SYSTEM:dream_journal", log_message)
            
            print(f"  - [Dreaming] 夢を見ました。洞察: {dream_data['insight']}")
            return "夢想プロセスが正常に完了しました。"

        except Exception as e:
            print(f"  - [Dreaming] エラー: {e}")
            traceback.print_exc()
            return f"夢想プロセス中にエラーが発生しました: {e}"