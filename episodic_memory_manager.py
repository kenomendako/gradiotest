# episodic_memory_manager.py

import os
import json
import datetime
import traceback
from pathlib import Path
from typing import List, Dict, Optional
import time
import re
import glob # <--- 追加

import constants
import config_manager
import utils

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
        全ログ（現行＋アーカイブ）を解析し、未処理の過去日付について要約を作成・追記する。
        【v3: 名前解決・逐次保存版】
        """
        from gemini_api import get_configured_llm

        print(f"--- [Episodic Memory] 更新処理開始: {self.room_name} ---")
        
        import room_manager
        room_config = room_manager.get_room_config(self.room_name) or {}
        user_name = room_config.get("user_display_name", "ユーザー")
        agent_name = room_config.get("agent_display_name") or room_config.get("room_name", "AI")
        
        # 1. 全ログファイルの収集
        log_files = []
        current_log = self.room_dir / "log.txt"
        if current_log.exists(): log_files.append(str(current_log))
        archives_dir = self.room_dir / "log_archives"
        if archives_dir.exists(): log_files.extend(glob.glob(str(archives_dir / "*.txt")))

        if not log_files: return "ログファイルが見つかりません。"

        print(f"  - 読み込み対象ファイル数: {len(log_files)}")

        # 2. ログの読み込みと日付ごとのグループ化
        logs_by_date = {}
        date_pattern = re.compile(r'(\d{4}-\d{2}-\d{2}) \(...\) \d{2}:\d{2}:\d{2}')
        
        for file_path in log_files:
            try:
                raw_logs = utils.load_chat_log(file_path)
                for msg in raw_logs:
                    content = msg.get('content', '')
                    match = date_pattern.search(content)
                    current_date = match.group(1) if match else None
                    
                    if current_date:
                        if current_date not in logs_by_date:
                            logs_by_date[current_date] = []
                        
                        role = msg.get('role', 'UNKNOWN')
                        responder = msg.get('responder', '')
                        
                        # ▼▼▼【修正】固定の「ユーザー/AI」ではなく、設定された名前を使う ▼▼▼
                        if role == 'USER':
                            speaker = user_name
                        else:
                            # responderが具体的な名前ならそれを使う、なければ設定上の名前
                            speaker = responder if responder and responder != "model" else agent_name
                        # ▲▲▲【修正ここまで】▲▲▲
                        
                        clean_text = utils.remove_thoughts_from_text(content)
                        clean_text = re.sub(r'\n\n\d{4}-\d{2}-\d{2}.*$', '', clean_text).strip()
                        
                        if clean_text:
                            logs_by_date[current_date].append(f"{speaker}: {clean_text}")
            except Exception as e:
                print(f"  - Error reading {file_path}: {e}")

        # 3. 処理対象の選定
        existing_memory = self._load_memory()
        existing_dates = {item['date'] for item in existing_memory}
        today_str = datetime.datetime.now().strftime('%Y-%m-%d')
        
        target_dates = []
        for date_str in sorted(logs_by_date.keys()):
            if date_str == today_str: continue
            if date_str in existing_dates: continue
            target_dates.append(date_str)

        if not target_dates:
            return "新規に要約すべき過去の日付はありませんでした（全ての過去ログは処理済みです）。"

        # 4. 要約の生成と逐次保存
        effective_settings = config_manager.get_effective_settings(self.room_name)
        llm = get_configured_llm(constants.SUMMARIZATION_MODEL, api_key, effective_settings)
        
        success_count = 0
        error_count = 0
        
        print(f"  - 処理対象の日付: {target_dates}")

        for date_str in target_dates:
            daily_log = "\n".join(logs_by_date[date_str])
            
            # ログが短い場合はスキップ記録
            if len(daily_log) < 50:
                print(f"  - {date_str}: ログが短いためスキップ記録します。")
                self._append_single_episode({
                    "date": date_str,
                    "summary": "（特筆すべき会話ログはありませんでした）",
                    "created_at": datetime.datetime.now().isoformat()
                })
                continue
                
            print(f"  - {date_str} の要約を作成中...")            

            prompt = f"""
あなたは、日々の出来事を記録する日記の執筆者です。
以下の会話ログは、ある一日の「{user_name}」と「{agent_name}（あなた）」のやり取りです。
この日の出来事、話題、そして感情の動きを、**後から読み返して文脈を思い出せるような「エピソード記憶」として要約**してください。

【会話ログ ({date_str})】
---
{daily_log}
---

【要約のルール】
1.  **三人称視点（だ・である調）**で記述してください。
2.  主語には「ユーザー」「AI」という抽象的な言葉ではなく、**ログ内で使われている固有名詞（名前）**をそのまま使用し、誰が何をしたか明確にしてください。
3.  単なる箇条書きではなく、**3〜5行程度の自然な文章**にまとめてください。
4.  特に「{user_name}の興味・関心」「決定事項」「約束」「感情的な交流」を重点的に記録してください。

【出力（要約のみ）】
"""

            summary_result = None
            max_retries = 3
            
            for attempt in range(max_retries):
                try:
                    # invokeの結果が空の場合も考慮
                    result = llm.invoke(prompt)
                    content = result.content.strip()
                    
                    if content:
                        summary_result = content
                        break
                    else:
                        # コンテンツが空（ブロック等）の場合
                        print(f"  - Warning: Empty response for {date_str} (Attempt {attempt+1})")
                        summary_result = "（コンテンツポリシーにより要約できませんでした）"
                        break # リトライしても恐らく同じなので抜ける

                except Exception as e:
                    error_str = str(e)
                    if "429" in error_str or "ResourceExhausted" in error_str:
                        wait_time = 10
                        match = re.search(r"retry_delay {\s*seconds: (\d+)", error_str)
                        if match: wait_time = int(match.group(1)) + 2
                        print(f"    -> API制限検知。{wait_time}秒待機してリトライします...")
                        time.sleep(wait_time)
                    else:
                        print(f"  - Error summarizing {date_str}: {e}")
                        summary_result = f"（エラーにより要約できませんでした: {e}）"
                        break
            
            # ▼▼▼【重要】結果がNoneのままループを抜けた場合のフォールバック ▼▼▼
            if not summary_result:
                summary_result = "（生成エラーまたはブロックにより要約できませんでした）"
            # ▲▲▲【追加】▲▲▲

            # どのような結果であれ、必ず保存する
            self._append_single_episode({
                "date": date_str,
                "summary": summary_result,
                "created_at": datetime.datetime.now().isoformat()
            })
            
            if "エラー" in summary_result or "できませんでした" in summary_result:
                error_count += 1
            else:
                success_count += 1

        return f"処理完了: 成功 {success_count}件 / エラー・スキップ {error_count}件"

    def _append_single_episode(self, new_episode: Dict):
        """
        単一のエピソードをファイルに追記保存するヘルパーメソッド。
        読み込み→追加→保存をアトミックに行う。
        """
        try:
            # 常に最新の状態を読み込む
            current_data = self._load_memory()
            
            # 重複チェック（念のため）
            if any(item['date'] == new_episode['date'] for item in current_data):
                return # 既に存在すれば何もしない

            current_data.append(new_episode)
            self._save_memory(current_data)
            
        except Exception as e:
            print(f"Error appending episode: {e}")

    def get_episodic_context(self, oldest_log_date_str: str, lookback_days: int) -> str:
        """
        APIに送信する「生ログ」より前の期間のエピソード記憶を取得し、テキスト化して返す。
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
        # 日付順にソートされている前提だが、念のためソート
        memory_data.sort(key=lambda x: x['date'])
        
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

    def get_latest_memory_date(self) -> str:
        """保存されているエピソード記憶の中で最も新しい日付を返す"""
        data = self._load_memory()
        if not data:
            return "なし"
        
        # 日付でソートして最後（最新）を取得
        try:
            sorted_data = sorted(data, key=lambda x: x['date'])
            return sorted_data[-1]['date']
        except Exception:
            return "不明"