# episodic_memory_manager.py

import os
import json
import datetime
import traceback
import time
import re
from pathlib import Path
from typing import List, Dict, Optional

import constants
import config_manager
import utils
from gemini_api import get_configured_llm

class EpisodicMemoryManager:
    def __init__(self, room_name: str):
        self.room_name = room_name
        self.room_dir = Path(constants.ROOMS_DIR) / room_name
        self.memory_dir = self.room_dir / "memory"
        self.memory_file = self.memory_dir / "episodic_memory.json"
        
        # ディレクトリの保証
        self.memory_dir.mkdir(parents=True, exist_ok=True)

    def _load_memory(self) -> List[Dict]:
        """JSONファイルからエピソード記憶を読み込む"""
        if self.memory_file.exists():
            try:
                with open(self.memory_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except json.JSONDecodeError:
                print(f"Warning: Episodic memory file is corrupted. {self.memory_file}")
                return []
        return []

    def _save_memory(self, data: List[Dict]):
        """エピソード記憶をJSONファイルに保存する"""
        # 日付順にソートして保存
        data.sort(key=lambda x: x['date'])
        with open(self.memory_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def update_memory(self, api_key: str) -> str:
        """
        ログを解析し、未処理の過去日付について要約を作成・追記する。
        """
        print(f"--- [Episodic Memory] 更新処理開始: {self.room_name} ---")
        
        # 1. ログの読み込みと日付ごとのグループ化
        log_path = self.room_dir / "log.txt"
        if not log_path.exists():
            return "ログファイルがありません。"

        raw_logs = utils.load_chat_log(str(log_path))
        logs_by_date = {}
        
        # 日付パターン (YYYY-MM-DD)
        # ※ utils.load_chat_log はメッセージごとの辞書を返すが、日付情報は本文に含まれている場合が多い
        #    ここでは簡易的に、本文内のタイムスタンプを探して日付を特定する
        import re
        date_pattern = re.compile(r'(\d{4}-\d{2}-\d{2}) \(...\) \d{2}:\d{2}:\d{2}')
        
        current_date = None
        
        for msg in raw_logs:
            content = msg.get('content', '')
            match = date_pattern.search(content)
            if match:
                current_date = match.group(1)
            
            if current_date:
                if current_date not in logs_by_date:
                    logs_by_date[current_date] = []
                
                # 話者名と本文を整形
                role = msg.get('role', 'UNKNOWN')
                responder = msg.get('responder', '')
                speaker = "ユーザー" if role == 'USER' else (responder if responder else "AI")
                
                # 思考ログなどを除去したクリーンなテキスト
                clean_text = utils.remove_thoughts_from_text(content)
                # タイムスタンプ行を除去
                clean_text = re.sub(r'\n\n\d{4}-\d{2}-\d{2}.*$', '', clean_text).strip()
                
                if clean_text:
                    logs_by_date[current_date].append(f"{speaker}: {clean_text}")

        # 2. 処理対象の選定
        existing_memory = self._load_memory()
        existing_dates = {item['date'] for item in existing_memory}
        
        today_str = datetime.datetime.now().strftime('%Y-%m-%d')
        
        target_dates = []
        for date_str in sorted(logs_by_date.keys()):
            # 「今日」はまだ終わっていないので要約しない
            if date_str == today_str:
                continue
            # 既に要約済みの日はスキップ
            if date_str in existing_dates:
                continue
            
            target_dates.append(date_str)

        if not target_dates:
            return "新規に要約すべき過去の日付はありませんでした。"

        # 3. 要約の生成
        llm = get_configured_llm(constants.INTERNAL_PROCESSING_MODEL, api_key, {})
        new_episodes = []
        
        print(f"  - 処理対象の日付: {target_dates}")

        for date_str in target_dates:
            daily_log = "\n".join(logs_by_date[date_str])
            
            # ログが少なすぎる場合はスキップ
            if len(daily_log) < 50:
                continue
                
            print(f"  - {date_str} の要約を作成中...")
            
            prompt = f"""
あなたは、日々の出来事を記録する日記の執筆者です。
以下の会話ログは、ある一日の「ユーザー」と「AI（あなた）」のやり取りです。
この日の出来事、話題、そして感情の動きを、**後から読み返して文脈を思い出せるような「エピソード記憶」として要約**してください。

【会話ログ ({date_str})】
---
{daily_log}
---

【要約のルール】
1.  **三人称視点（だ・である調）**で記述してください。（例：ユーザーは〇〇について相談し、AIは△△と助言した。）
2.  単なる箇条書きではなく、**3〜5行程度の自然な文章**にまとめてください。
3.  特に「ユーザーの興味・関心」「決定事項」「約束」「感情的な交流」を重点的に記録してください。
4.  挨拶や定型文は省略し、会話の実質的な内容に焦点を当ててください。

【出力（要約のみ）】
"""            
            # ▼▼▼【変更】リトライ付きの呼び出しループ ▼▼▼
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    summary = llm.invoke(prompt).content.strip()
                    new_episodes.append({
                        "date": date_str,
                        "summary": summary,
                        "created_at": datetime.datetime.now().isoformat()
                    })
                    # 成功したらループを抜ける
                    break 
                except Exception as e:
                    error_str = str(e)
                    # レート制限エラーかチェック
                    if "429" in error_str or "ResourceExhausted" in error_str:
                        # エラーメッセージから待機時間を抽出
                        wait_time = 10  # デフォルト10秒
                        match = re.search(r"retry_delay {\s*seconds: (\d+)", error_str)
                        if match:
                            wait_time = int(match.group(1)) + 2 # 余裕を持って+2秒
                        
                        print(f"    -> API制限検知。{wait_time}秒待機してリトライします ({attempt+1}/{max_retries})...")
                        time.sleep(wait_time)
                    else:
                        # その他のエラーならログを出してスキップ
                        print(f"  - Error summarizing {date_str}: {e}")
                        break
                    
        # 4. 保存
        if new_episodes:
            existing_memory.extend(new_episodes)
            self._save_memory(existing_memory)
            return f"{len(new_episodes)}日分のエピソード記憶を新規作成しました。"
        else:
            return "要約対象のログが短すぎたため、保存されませんでした。"

    def get_episodic_context(self, oldest_log_date_str: str, lookback_days: int) -> str:
        """
        APIに送信する「生ログ」より前の期間のエピソード記憶を取得し、テキスト化して返す。
        
        Args:
            oldest_log_date_str: 生ログに含まれる最も古い日付 (YYYY-MM-DD)。これより前の記憶を取得する。
            lookback_days: 何日前まで遡るか。
        """
        if not oldest_log_date_str or lookback_days <= 0:
            return ""

        memory_data = self._load_memory()
        if not memory_data:
            return ""

        try:
            cutoff_date = datetime.datetime.strptime(oldest_log_date_str, '%Y-%m-%d').date()
            start_date = cutoff_date - datetime.timedelta(days=lookback_days)
        except ValueError:
            return ""

        relevant_episodes = []
        for item in memory_data:
            try:
                item_date = datetime.datetime.strptime(item['date'], '%Y-%m-%d').date()
                # 範囲チェック: (開始日) <= (エピソード日) < (生ログ開始日)
                if start_date <= item_date < cutoff_date:
                    relevant_episodes.append(f"[{item['date']}] {item['summary']}")
            except ValueError:
                continue

        if not relevant_episodes:
            return ""

        return "\n".join(relevant_episodes)