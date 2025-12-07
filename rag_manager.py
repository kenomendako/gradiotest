# rag_manager.py (v6: Incremental Save / Checkpoint System)

import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import List, Dict, Optional, Set, Tuple
import traceback
import logging
import json
import hashlib

from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_community.docstore.document import Document
from langchain.text_splitter import RecursiveCharacterTextSplitter
from google.api_core import exceptions as google_exceptions

import constants
import config_manager
import utils

# ロギング設定
logger = logging.getLogger(__name__)

class RAGManager:
    def __init__(self, room_name: str, api_key: str):
        self.room_name = room_name
        self.api_key = api_key
        self.room_dir = Path(constants.ROOMS_DIR) / room_name
        self.rag_data_dir = self.room_dir / "rag_data"
        
        self.static_index_path = self.rag_data_dir / "faiss_index_static"
        self.dynamic_index_path = self.rag_data_dir / "faiss_index_dynamic"
        self.processed_files_record = self.rag_data_dir / "processed_static_files.json"
        
        self.rag_data_dir.mkdir(parents=True, exist_ok=True)

        self.embeddings = GoogleGenerativeAIEmbeddings(
            model=constants.EMBEDDING_MODEL,
            google_api_key=self.api_key,
            task_type="retrieval_document"
        )

    def _load_processed_record(self) -> Set[str]:
        if self.processed_files_record.exists():
            try:
                with open(self.processed_files_record, 'r', encoding='utf-8') as f:
                    return set(json.load(f))
            except Exception:
                return set()
        return set()

    def _save_processed_record(self, processed_files: Set[str]):
        with open(self.processed_files_record, 'w', encoding='utf-8') as f:
            json.dump(list(processed_files), f, indent=2, ensure_ascii=False)

    def _safe_save_index(self, db: FAISS, target_path: Path):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            db.save_local(str(temp_path))
            if target_path.exists():
                shutil.rmtree(str(target_path))
            shutil.move(str(temp_path), str(target_path))

    def _safe_load_index(self, target_path: Path) -> Optional[FAISS]:
        if not target_path.exists():
            return None
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_index_path = Path(temp_dir) / "index_copy"
            shutil.copytree(str(target_path), str(temp_index_path))
            try:
                query_embeddings = GoogleGenerativeAIEmbeddings(
                    model=constants.EMBEDDING_MODEL,
                    google_api_key=self.api_key,
                    task_type="retrieval_query"
                )
                return FAISS.load_local(
                    str(temp_index_path),
                    query_embeddings,
                    allow_dangerous_deserialization=True
                )
            except Exception as e:
                print(f"Index load error: {e}")
                return None

    def _create_index_in_batches(self, splits: List[Document], existing_db: Optional[FAISS] = None) -> FAISS:
        """
        大量のドキュメントをバッチ分割し、レート制限を回避しながらインデックスを作成/追記する。
        """
        BATCH_SIZE = 20
        db = existing_db
        total_splits = len(splits)
        
        # print(f"    - {total_splits} チャンクをAPIへ送信中...")

        for i in range(0, total_splits, BATCH_SIZE):
            batch = splits[i : i + BATCH_SIZE]
            
            # リトライループ
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    if db is None:
                        db = FAISS.from_documents(batch, self.embeddings)
                    else:
                        db.add_documents(batch)
                    
                    time.sleep(2) 
                    break 
                
                except Exception as e:
                    error_str = str(e)
                    if "429" in error_str or "ResourceExhausted" in error_str:
                        wait_time = 10 * (attempt + 1)
                        print(f"      ! API制限検知。{wait_time}秒待機してリトライ... ({attempt+1}/{max_retries})")
                        time.sleep(wait_time)
                    else:
                        print(f"      ! ベクトル化エラー: {e}")
                        if attempt == max_retries - 1:
                            print("      ! このバッチをスキップします。")
                        time.sleep(2)
        
        return db

    def create_or_update_index(self, status_callback=None) -> str:
        def report(message):
            print(f"--- [RAG] {message}")
            if status_callback: status_callback(message)

        messages = []
        
        # --- Phase 1: 静的インデックス（逐次保存・チェックポイント方式） ---
        report("Phase 1: 過去ログ、エピソード記憶、夢日記の差分を確認中...")
        
        processed_records = self._load_processed_record()
        
        # 処理対象のキュー: (record_id, document) のタプルリスト
        pending_items: List[Tuple[str, Document]] = []
        
        # 1. 過去ログ収集
        archives_dir = self.room_dir / "log_archives"
        if archives_dir.exists():
            for f in list(archives_dir.glob("*.txt")):
                record_id = f"archive:{f.name}"
                if record_id not in processed_records:
                    try:
                        content = f.read_text(encoding="utf-8")
                        if content.strip():
                            doc = Document(page_content=content, metadata={"source": f.name, "type": "log_archive", "path": str(f)})
                            pending_items.append((record_id, doc))
                    except Exception: pass

        # 2. エピソード記憶収集
        episodic_memory_path = self.room_dir / "memory" / "episodic_memory.json"
        if episodic_memory_path.exists():
            try:
                with open(episodic_memory_path, 'r', encoding='utf-8') as f:
                    episodes = json.load(f)
                if isinstance(episodes, list):
                    for ep in episodes:
                        date_str = ep.get('date', 'unknown')
                        record_id = f"episodic:{date_str}"
                        if record_id not in processed_records:
                            summary = ep.get('summary', '')
                            if summary:
                                content = f"日付: {date_str}\n内容: {summary}"
                                doc = Document(page_content=content, metadata={"source": "episodic_memory.json", "type": "episodic_memory", "date": date_str})
                                pending_items.append((record_id, doc))
            except Exception: pass

        # 3. 夢日記収集
        insights_path = self.room_dir / "memory" / "insights.json"
        if insights_path.exists():
            try:
                with open(insights_path, 'r', encoding='utf-8') as f:
                    insights = json.load(f)
                if isinstance(insights, list):
                    for item in insights:
                        date_str = item.get('created_at', '').split(' ')[0]
                        record_id = f"dream:{date_str}"
                        if record_id not in processed_records:
                            insight_content = item.get('insight', '')
                            strategy = item.get('strategy', '')
                            if insight_content:
                                content = f"【過去の夢・深層心理の記録 ({date_str})】\nトリガー: {item.get('trigger_topic','')}\n気づき: {insight_content}\n指針: {strategy}"
                                doc = Document(page_content=content, metadata={"source": "insights.json", "type": "dream_insight", "date": date_str})
                                pending_items.append((record_id, doc))
            except Exception: pass

        # --- Phase 1 実行: 小分けにして保存しながら進む ---
        if pending_items:
            total_pending = len(pending_items)
            report(f"新規追加アイテム: {total_pending}件。これらを小分けにして保存しながら処理します。")
            
            # インデックスのロード
            static_db = self._safe_load_index(self.static_index_path)
            
            # 保存の粒度（何ファイルごとにセーブするか）
            SAVE_INTERVAL = 5 
            
            text_splitter = RecursiveCharacterTextSplitter(chunk_size=300, chunk_overlap=50)
            
            processed_count = 0
            
            # リストをチャンク分割してループ
            for i in range(0, total_pending, SAVE_INTERVAL):
                batch_items = pending_items[i : i + SAVE_INTERVAL]
                batch_docs = [item[1] for item in batch_items]
                batch_ids = [item[0] for item in batch_items]
                
                print(f"  - グループ処理中 ({i+1}〜{min(i+SAVE_INTERVAL, total_pending)} / {total_pending})...")
                
                # ドキュメントをチャンク分割
                splits = text_splitter.split_documents(batch_docs)
                
                # ベクトル化してDBに追加
                # (初回でstatic_dbがNoneの場合はここで生成される)
                static_db = self._create_index_in_batches(splits, existing_db=static_db)
                
                if static_db:
                    # ★★★ チェックポイント保存 ★★★
                    self._safe_save_index(static_db, self.static_index_path)
                    
                    # 記録を更新して保存
                    processed_records.update(batch_ids)
                    self._save_processed_record(processed_records)
                    
                    processed_count += len(batch_items)
                    # print(f"    -> セーブ完了。")
                else:
                    print(f"    ! グループ処理失敗。")

            messages.append(f"固定記憶: {processed_count}件を追加保存")
        else:
            messages.append("固定記憶: 差分なし")

        # --- Phase 2: 動的インデックス（知識・現行ログのみ） ---
        # ※ここは再構築なのでセーブポイント方式は適用せず、一括で行う（件数が少ない前提）
        report("Phase 2: 知識ベースと現行ログを再構築中...")
        dynamic_docs = []
        
        knowledge_dir = self.room_dir / "knowledge"
        if knowledge_dir.exists():
            for f in list(knowledge_dir.glob("*.txt")) + list(knowledge_dir.glob("*.md")):
                try:
                    content = f.read_text(encoding="utf-8")
                    dynamic_docs.append(Document(page_content=content, metadata={"source": f.name, "type": "knowledge"}))
                except Exception: pass

        current_log_path = self.room_dir / "log.txt"
        if current_log_path.exists():
             try:
                content = current_log_path.read_text(encoding="utf-8")
                dynamic_docs.append(Document(page_content=content, metadata={"source": "log.txt", "type": "current_log"}))
             except Exception: pass

        if dynamic_docs:
            text_splitter = RecursiveCharacterTextSplitter(chunk_size=300, chunk_overlap=50)
            dynamic_splits = text_splitter.split_documents(dynamic_docs)
            dynamic_db = self._create_index_in_batches(dynamic_splits, existing_db=None)
            
            if dynamic_db:
                self._safe_save_index(dynamic_db, self.dynamic_index_path)
                messages.append(f"変動記憶: {len(dynamic_docs)}ファイルを更新")
            else:
                messages.append("変動記憶: 作成失敗")
        else:
            if self.dynamic_index_path.exists():
                shutil.rmtree(str(self.dynamic_index_path))
            messages.append("変動記憶: 対象なし")

        final_msg = " / ".join(messages)
        print(f"--- [RAG] 処理完了: {final_msg} ---")
        return final_msg

    def search(self, query: str, k: int = 10, score_threshold: float = 0.75) -> List[Document]:
        """静的・動的インデックスの両方を検索し、スコアで足切りして結果を統合する"""
        results_with_scores = []
        print(f"--- [RAG Search Debug] Query: '{query}' (Threshold: {score_threshold}) ---")

        dynamic_db = self._safe_load_index(self.dynamic_index_path)
        if dynamic_db:
            try:
                dynamic_results = dynamic_db.similarity_search_with_score(query, k=k)
                results_with_scores.extend(dynamic_results)
            except Exception as e: print(f"  - [RAG Warning] Dynamic index search failed: {e}")

        static_db = self._safe_load_index(self.static_index_path)
        if static_db:
            try:
                static_results = static_db.similarity_search_with_score(query, k=k)
                results_with_scores.extend(static_results)
            except Exception as e: print(f"  - [RAG Warning] Static index search failed: {e}")

        filtered_docs = []
        results_with_scores.sort(key=lambda x: x[1])

        for doc, score in results_with_scores:
            is_relevant = score <= score_threshold
            clean_content = doc.page_content.replace('\n', ' ')[:50]
            status_icon = "✅" if is_relevant else "❌"
            print(f"  - {status_icon} Score: {score:.4f} | {clean_content}...")
            
            if is_relevant:
                filtered_docs.append(doc)

        return filtered_docs[:k]