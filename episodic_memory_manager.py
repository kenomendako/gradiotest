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
        def get_sort_key_for_save(item):
            d = item.get('date', '').strip()
            # 範囲なら開始日でソートして自然な並びにする
            if '~' in d: return d.split('~')[0].strip()
            if '～' in d: return d.split('～')[0].strip()
            return d
            
        data.sort(key=get_sort_key_for_save)
        with open(self.memory_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        # print(f"  - 記憶ファイルを保存しました ({len(data)}件, {os.path.getsize(self.memory_file)} bytes)")

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
        print(f"  - 既存の記憶エントリ総数: {len(existing_memory)}")
        
        # 既にある日付をセット（単独日の高速検索用）
        # 全角チルダにも対応し、前後の空白も除去
        # 「エラーにより要約できませんでした」という文字が含まれるエントリは、再処理対象にするため「既知」から除外する
        existing_dates_single = {
            item['date'].strip() for item in existing_memory 
            if isinstance(item, dict) and 'date' in item 
            and '~' not in item['date'] and '～' not in item['date']
            and "エラーにより要約できませんでした" not in item.get('summary', '')
        }
        print(f"  - 解析された単独エントリ数: {len(existing_dates_single)}")
        
        if len(existing_dates_single) > 0:
            may_dates = sorted([d for d in existing_dates_single if "2025-05" in d])
            if may_dates:
                print(f"  - 5月の単独エントリ例: {may_dates[:10]}")

        # 既にある日付範囲（週圧縮済み用）
        existing_date_ranges = []
        for item in existing_memory:
            if not isinstance(item, dict) or 'date' not in item: continue
            
            d_str = item['date'].strip()
            if '~' in d_str or '～' in d_str:
                sep = '~' if '~' in d_str else '～'
                parts = d_str.split(sep)
                if len(parts) == 2:
                    existing_date_ranges.append((parts[0].strip(), parts[1].strip()))
        
        print(f"  - 解析された既知の範囲数: {len(existing_date_ranges)}")
        if existing_date_ranges:
            print(f"  - 解析された既知の範囲: {existing_date_ranges}")

        today_str = datetime.datetime.now().strftime('%Y-%m-%d')
        
        target_dates = []
        for date_str in sorted(logs_by_date.keys()):
            date_str_clean = date_str.strip() # ここでもトリミング
            if date_str_clean == today_str: continue
            
            # 単独日として存在するかチェック
            if date_str_clean in existing_dates_single: continue
            
            # いずれかの範囲に含まれているかチェック
            is_processed = False
            for start, end in existing_date_ranges:
                if start <= date_str_clean <= end:
                    is_processed = True
                    break
            
            if is_processed: continue
            
            target_dates.append(date_str_clean)

        if not target_dates:
            print("  - 新規に要約すべき日付はありません。")
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
            is_temporary_error = False
            max_retries = 3
            
            for attempt in range(max_retries):
                try:
                    # invokeの結果が空の場合も考慮
                    result = llm.invoke(prompt)
                    content = result.content.strip()
                    
                    if content:
                        summary_result = content
                        is_temporary_error = False
                        break
                    else:
                        # コンテンツが空（ブロック等）の場合
                        print(f"  - Warning: Empty response for {date_str} (Attempt {attempt+1})")
                        summary_result = "（コンテンツポリシーにより要約できませんでした）"
                        is_temporary_error = False
                        break # リトライしても恐らく同じなので抜ける

                except Exception as e:
                    error_str = str(e)
                    # 一時的なエラー（リトライすべきもの）
                    if any(code in error_str for code in ["429", "ResourceExhausted", "500", "503", "504", "deadline exceeded"]):
                        is_temporary_error = True
                        if "429" in error_str or "ResourceExhausted" in error_str:
                            wait_time = 10
                            match = re.search(r"retry_delay {\s*seconds: (\d+)", error_str)
                            if match: wait_time = int(match.group(1)) + 2
                            print(f"    -> API制限検知({attempt+1}/{max_retries})。{wait_time}秒待機...")
                            time.sleep(wait_time)
                        else:
                            print(f"    -> 一時的エラー検知({attempt+1}/{max_retries}): {e}")
                        
                        # ループの最後なら次へ行く（自然に attempt が増える）
                        continue
                    else:
                        # 恒久的なエラー（このまま保存して終わるもの）
                        print(f"  - 恒久的なエラーまたは未知のエラー: {e}")
                        summary_result = f"（エラーにより要約できませんでした: {e}）"
                        is_temporary_error = False
                        break
            
            # --- 保存判定 ---
            if summary_result:
                # 成功したか、恒久的に失敗した場合は保存して「完了」とする
                # [Phase 2] Arousal平均値を取得
                arousal_score = 0.5  # デフォルト
                try:
                    import session_arousal_manager
                    arousal_score = session_arousal_manager.get_daily_average(self.room_name, date_str)
                except Exception as e:
                    print(f"  - [Arousal] 取得失敗: {e}")
                
                self._append_single_episode({
                    "date": date_str,
                    "summary": summary_result,
                    "arousal": arousal_score,  # Arousal追加
                    "created_at": datetime.datetime.now().isoformat()
                })
                
                if "エラー" in summary_result or "できませんでした" in summary_result:
                    error_count += 1
                else:
                    success_count += 1
            elif is_temporary_error:
                # すべてのリトライが一時的エラーで終わった場合。
                # 保存しないことで、次回の update_memory 実行時に再度対象に含まれるようにする。
                print(f"  - {date_str}: 一時的エラーが解消されなかったため、保存せずに今回はスキップします（次回再試行）。")
                error_count += 1
            else:
                # 予期せぬケース
                print(f"  - {date_str}: 要約結果が得られなかったため、保存をスキップしました。")
                error_count += 1

        return f"処理完了: 成功 {success_count}件 / エラー・スキップ {error_count}件"

    def _append_single_episode(self, new_episode: Dict):
        """
        単一のエピソードをファイルに追記保存するヘルパーメソッド。
        読み込み→追加→保存をアトミックに行う。
        """
        try:
            # 常に最新の状態を読み込む
            current_data = self._load_memory()
            
            # 重複判定（単一一致 or 範囲内）
            is_duplicate = False
            for item in current_data:
                d_str = item.get('date', '').strip()
                new_date = new_episode.get('date', '').strip()
                
                if '~' in d_str or '～' in d_str:
                    sep = '~' if '~' in d_str else '～'
                    parts = d_str.split(sep)
                    if len(parts) == 2:
                        start, end = parts[0].strip(), parts[1].strip()
                        if start <= new_date <= end:
                            is_duplicate = True
                            break
                elif d_str == new_date:
                    is_duplicate = True
                    break
            
            if is_duplicate:
                # 既に存在する場合の特別処理: 
                # 既存が「エラー記録」で、今回が「正常な要約」なら上書き（差し替え）を許可する
                existing_item = None
                for i in current_data:
                    if i.get('date', '').strip() == new_date:
                        existing_item = i
                        break
                
                if existing_item and "エラーにより要約できませんでした" in existing_item.get('summary', ''):
                    if "エラーにより要約できませんでした" not in new_episode.get('summary', ''):
                        # エラーを正常な記憶で上書き
                        current_data.remove(existing_item)
                    else:
                        # 両方エラーなら追記せず終了
                        return
                else:
                    # 既存が正常なら何もしない
                    return

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
                # 範囲日付 (YYYY-MM-DD~YYYY-MM-DD) または 単独日付 (YYYY-MM-DD)
                d_str = item['date']
                sep = '~' if '~' in d_str else ('～' if '～' in d_str else None)
                
                if sep:
                    parts = d_str.split(sep)
                    item_start_date = datetime.datetime.strptime(parts[0].strip(), '%Y-%m-%d').date()
                    item_end_date = datetime.datetime.strptime(parts[1].strip(), '%Y-%m-%d').date()
                else:
                    item_start_date = datetime.datetime.strptime(d_str.strip(), '%Y-%m-%d').date()
                    item_end_date = item_start_date
                
                # 範囲チェック: (既存エピソードの終端がルックバック開始日以降) かつ (既存エピソードの開始が生ログ開始日より前)
                if (item_end_date >= start_date) and (item_start_date < cutoff_date):
                    relevant_episodes.append(f"[{d_str}] {item['summary']}")
            except Exception:
                continue

        if not relevant_episodes:
            return ""

        return "\n".join(relevant_episodes)

    def get_latest_memory_date(self) -> str:
        """保存されているエピソード記憶の中で最も新しい日付を返す"""
        try:
            data = self._load_memory()
            if not data:
                return "なし"
            
            # 範囲日付の終端、または単一の日付でソートして最後（最新）を取得
            # dateキーが存在しない可能性を考慮
            valid_items = [x for x in data if isinstance(x, dict) and 'date' in x]
            if not valid_items:
                return "なし"
            
            def get_sort_key(item):
                d = item['date']
                if '~' in d: return d.split('~')[-1].strip()
                if '～' in d: return d.split('～')[-1].strip()
                return d.strip()
                
            sorted_data = sorted(valid_items, key=get_sort_key)
            return sorted_data[-1]['date']
        except Exception as e:
            print(f"Error in get_latest_memory_date: {e}")
            import traceback
            traceback.print_exc()
            return "取得エラー"

    def compress_old_episodes(self, api_key: str, threshold_days: int = 60) -> str:
        """
        一定期間以上前のエピソード記憶を週単位に統合する。
        元データはアーカイブに保存。
        
        Args:
            api_key: 要約生成に使用するAPIキー
            threshold_days: 圧縮対象とする日数（デフォルト60日 = 約2ヶ月）
            
        Returns:
            処理結果のメッセージ
        """
        from gemini_api import get_configured_llm
        from collections import defaultdict
        
        print(f"--- [Episodic Memory] 圧縮処理開始: {self.room_name} ---")
        
        episodes = self._load_memory()
        if not episodes:
            return "圧縮対象のエピソード記憶がありません。"
        
        # 閾値日付を計算
        threshold_date = datetime.datetime.now() - datetime.timedelta(days=threshold_days)
        threshold_date_str = threshold_date.strftime('%Y-%m-%d')
        
        # 古いエピソードと新しいエピソードを分離
        old_episodes = []
        recent_episodes = []
        
        for episode in episodes:
            episode_date = episode.get('date', '')
            if episode_date < threshold_date_str:
                old_episodes.append(episode)
            else:
                recent_episodes.append(episode)
        
        if not old_episodes:
            return f"圧縮対象のエピソード（{threshold_days}日以上前）はありませんでした。"
        
        print(f"  - 圧縮対象: {len(old_episodes)}件 / 最近: {len(recent_episodes)}件")
        
        # --- アーカイブ保存 ---
        archive_dir = self.memory_dir / "archives"
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive_file = archive_dir / f"episodic_archive_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        with open(archive_file, 'w', encoding='utf-8') as f:
            json.dump(old_episodes, f, indent=2, ensure_ascii=False)
        print(f"  - アーカイブ保存: {archive_file}")
        
        # --- 週ごとにグループ化 ---
        weekly_groups = defaultdict(list)
        preserved_compressed_episodes = [] # 既にある圧縮済みエピソード
        unparseable_episodes = [] # 形式不一致のため統合できないが破棄してはいけないエピソード
        
        for episode in old_episodes:
            ep_date_str = episode.get('date', '').strip()
            if '~' in ep_date_str or '～' in ep_date_str:
                # すでに圧縮済みのものはそのまま保持する
                preserved_compressed_episodes.append(episode)
                continue
                
            try:
                # 単一の日付の場合のみ週グループ化の対象にする
                episode_date = datetime.datetime.strptime(ep_date_str, '%Y-%m-%d')
                # 週の開始日（月曜日）を取得
                week_start_obj = episode_date - datetime.timedelta(days=episode_date.weekday())
                week_key = week_start_obj.strftime('%Y-%m-%d')
                weekly_groups[week_key].append(episode)
            except ValueError:
                print(f"  ⚠️ 無効な日付形式（現状保存）: {ep_date_str}")
                unparseable_episodes.append(episode)
                continue
        
        if not weekly_groups and not preserved_compressed_episodes and not unparseable_episodes:
            return "圧縮対象のエピソードがありませんでした。"
        
        print(f"  - グループ数: {len(weekly_groups)} / 維持: {len(preserved_compressed_episodes)} / 非パース: {len(unparseable_episodes)}")
        
        # --- 各週の要約を生成 ---
        effective_settings = config_manager.get_effective_settings(self.room_name)
        llm = get_configured_llm(constants.SUMMARIZATION_MODEL, api_key, effective_settings)
        
        compressed_episodes = []
        
        for week_start, week_episodes in sorted(weekly_groups.items()):
            # 週の終了日を計算
            week_start_date = datetime.datetime.strptime(week_start, '%Y-%m-%d')
            week_end_date = week_start_date + datetime.timedelta(days=6)
            week_end = week_end_date.strftime('%Y-%m-%d')
            
            # --- [Phase 2-B] Arousalによるソート ---
            # 高Arousalエピソードを優先して詳細に記載
            week_episodes_sorted = sorted(
                week_episodes,
                key=lambda e: e.get("arousal", 0.5),
                reverse=True
            )
            
            # 週内のArousal統計
            arousal_values = [e.get("arousal", 0.5) for e in week_episodes]
            avg_arousal = sum(arousal_values) / len(arousal_values) if arousal_values else 0.5
            max_arousal = max(arousal_values) if arousal_values else 0.5
            
            # 週内のエピソード要約を結合（高Arousal順）
            week_summaries = []
            for i, ep in enumerate(week_episodes_sorted):
                summary = ep.get('summary', '')
                if summary and '（' not in summary[:5]:  # エラーメッセージでないことを確認
                    ep_arousal = ep.get("arousal", 0.5)
                    # 高Arousal（上位2件）はマークを付加
                    if i < 2 and ep_arousal >= 0.5:
                        week_summaries.append(f"★[{ep['date']}] {summary}")
                    else:
                        week_summaries.append(f"[{ep['date']}] {summary}")
            
            if not week_summaries:
                continue
            
            combined_text = "\n\n".join(week_summaries)
            
            # 週ごとの統合要約を生成
            prompt = f"""
あなたは、日記の編集者です。
以下は、ある1週間の出来事の記録です。これらを1つにまとめて、週全体の出来事として要約してください。

【元の記録 ({week_start} 〜 {week_end})】
---
{combined_text}
---

【要約のルール】
1. 三人称視点（だ・である調）で記述してください。
2. 固有名詞はそのまま使用してください。
3. 5〜8行程度の自然な文章にまとめてください。
4. 重要な出来事、決定事項、感情的な交流を優先して記録してください。
5. 個々の日付に言及する必要はありません。週全体の印象をまとめてください。

【出力（週間要約のみ）】
"""
            
            try:
                result = llm.invoke(prompt)
                summary = result.content.strip()
                
                if summary:
                    compressed_episodes.append({
                        "date": f"{week_start}~{week_end}",
                        "summary": summary,
                        "arousal": round(avg_arousal, 3),  # 週平均Arousal
                        "arousal_max": round(max_arousal, 3),  # 週最大Arousal
                        "compressed": True,
                        "original_count": len(week_episodes),
                        "created_at": datetime.datetime.now().isoformat()
                    })
                    print(f"    - {week_start}〜{week_end}: {len(week_episodes)}件 → 1件 (Arousal avg:{avg_arousal:.2f})")
                else:
                    # 要約が空だった場合は元のエピソードをそのまま保持（データ消失防止）
                    print(f"    - {week_start}〜{week_end}: 要約が空のため統合をスキップし、元データを維持します。")
                    compressed_episodes.extend(week_episodes)
            except Exception as e:
                print(f"    - {week_start}〜{week_end}: 要約エラー ({e})")
                # エラー時は元のエピソードをそのまま保持
                compressed_episodes.extend(week_episodes)
        
        # --- 圧縮後のデータを保存 ---
        # 既存の圧縮済み + 今回圧縮したもの + 形式不一致 + 最近のもの
        final_episodes = preserved_compressed_episodes + compressed_episodes + unparseable_episodes + recent_episodes
        
        self._save_memory(final_episodes)
        
        msg = f"圧縮完了: {len(old_episodes) - len(preserved_compressed_episodes) - len(unparseable_episodes)}件を{len(compressed_episodes)}件に集約しました。"
        if preserved_compressed_episodes:
            msg += f"（既存圧縮{len(preserved_compressed_episodes)}件、非パース{len(unparseable_episodes)}件を維持）"
        print(f"  - {msg}")
        return msg

    def get_compression_stats(self, threshold_days: int = 60) -> dict:
        """
        現在の記憶ファイルの圧縮状況（圧縮済み最終日、圧縮対象件数）をスキャンして返す。
        """
        episodes = self._load_memory()
        if not episodes:
            return {"last_compressed_date": None, "pending_count": 0, "total_count": 0}
            
        # 閾値日付
        threshold_date = datetime.datetime.now() - datetime.timedelta(days=threshold_days)
        threshold_date_str = threshold_date.strftime('%Y-%m-%d')
        
        last_compressed_date = None
        pending_count = 0
        
        for ep in episodes:
            date_str = ep.get('date', '')
            # 圧縮済み（週範囲形式 "YYYY-MM-DD~YYYY-MM-DD"）をチェック
            if '~' in date_str:
                parts = date_str.split('~')
                end_date = parts[-1]
                if last_compressed_date is None or end_date > last_compressed_date:
                    last_compressed_date = end_date
            elif ep.get('compressed') is True: # フラグがある場合
                if last_compressed_date is None or date_str > last_compressed_date:
                    last_compressed_date = date_str
            else:
                # 圧縮されていないエピソードで、かつ閾値より古いものをカウント
                if date_str < threshold_date_str:
                    pending_count += 1
                    
        return {
            "last_compressed_date": last_compressed_date,
            "pending_count": pending_count,
            "total_count": len(episodes)
        }