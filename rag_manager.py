# rag_manager.py (v4: Batch Processing & Rate Limit Handling)

import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import List, Dict, Optional, Set
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
        # バッチサイズ: 安全を見て20件ずつ
        BATCH_SIZE = 20
        db = existing_db
        total_splits = len(splits)
        
        print(f"  - 合計 {total_splits} チャンクをバッチ処理でベクトル化します...")

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
                    
                    # 成功したら少し待機して次へ (レート制限対策)
                    time.sleep(2) 
                    break 
                
                except Exception as e:
                    error_str = str(e)
                    if "429" in error_str or "ResourceExhausted" in error_str:
                        wait_time = 10 * (attempt + 1)
                        print(f"    - API制限検知 (Batch {i//BATCH_SIZE + 1})。{wait_time}秒待機してリトライします...")
                        time.sleep(wait_time)
                    else:
                        print(f"    - ベクトル化中に予期せぬエラー: {e}")
                        if attempt == max_retries - 1:
                            print("    - このバッチの処理をスキップします。")
                        time.sleep(2)
        
        return db

    def create_or_update_index(self, status_callback=None) -> str:
        def report(message):
            print(f"--- [RAG] {message}")
            if status_callback: status_callback(message)

        messages = []
        
        # --- Phase 1: 静的インデックス（過去ログ） ---
        report("Phase 1: 過去ログアーカイブを確認中...")
        processed_files = self._load_processed_record()
        new_static_docs = []
        new_processed_files = set()
        
        archives_dir = self.room_dir / "log_archives"
        if archives_dir.exists():
            all_archives = list(archives_dir.glob("*.txt"))
            for f in all_archives:
                if f.name not in processed_files:
                    try:
                        content = f.read_text(encoding="utf-8")
                        if content.strip():
                            new_static_docs.append(Document(
                                page_content=content, 
                                metadata={"source": f.name, "type": "log_archive", "path": str(f)}
                            ))
                            new_processed_files.add(f.name)
                    except Exception as e:
                        print(f"Failed to read archive {f.name}: {e}")

        if new_static_docs:
            report(f"過去ログの新規追加分 ({len(new_static_docs)}ファイル) を処理中...")
            # チャンクサイズを小さく
            text_splitter = RecursiveCharacterTextSplitter(chunk_size=300, chunk_overlap=50)
            static_splits = text_splitter.split_documents(new_static_docs)
            
            static_db = self._safe_load_index(self.static_index_path)
            
            # バッチ処理メソッドを使用
            static_db = self._create_index_in_batches(static_splits, existing_db=static_db)
            
            if static_db:
                self._safe_save_index(static_db, self.static_index_path)
                processed_files.update(new_processed_files)
                self._save_processed_record(processed_files)
                messages.append(f"過去ログ: {len(new_static_docs)}ファイルを新規追加")
            else:
                messages.append("過去ログ: ベクトル化失敗")
        else:
            messages.append("過去ログ: 差分なし")

        # --- Phase 2: 動的インデックス（知識・現行ログ） ---
        report("Phase 2: 知識ベースと現行ログ、エピソード記憶を処理中...")
        dynamic_docs = []
        
        # Knowledge
        knowledge_dir = self.room_dir / "knowledge"
        if knowledge_dir.exists():
            for f in list(knowledge_dir.glob("*.txt")) + list(knowledge_dir.glob("*.md")):
                try:
                    content = f.read_text(encoding="utf-8")
                    dynamic_docs.append(Document(page_content=content, metadata={"source": f.name, "type": "knowledge"}))
                except Exception: pass

        # Current Log
        current_log_path = self.room_dir / "log.txt"
        if current_log_path.exists():
             try:
                content = current_log_path.read_text(encoding="utf-8")
                dynamic_docs.append(Document(page_content=content, metadata={"source": "log.txt", "type": "current_log"}))
             except Exception: pass

        # Episodic Memory
        episodic_memory_path = self.room_dir / "memory" / "episodic_memory.json"
        if episodic_memory_path.exists():
            try:
                with open(episodic_memory_path, 'r', encoding='utf-8') as f:
                    episodes = json.load(f)
                if isinstance(episodes, list):
                    for ep in episodes:
                        date_str = ep.get('date', '不明な日付')
                        summary = ep.get('summary', '')
                        if summary:
                            content = f"日付: {date_str}\n内容: {summary}"
                            dynamic_docs.append(Document(
                                page_content=content,
                                metadata={"source": "episodic_memory.json", "type": "episodic_memory", "date": date_str}
                            ))
                    print(f"  - エピソード記憶から {len(episodes)} 件をインデックス化しました。")
            except Exception as e: print(f"Warning: Failed to read episodic_memory.json: {e}")

        # Dream Insights
        insights_path = self.room_dir / "memory" / "insights.json"
        if insights_path.exists():
            try:
                with open(insights_path, 'r', encoding='utf-8') as f:
                    insights = json.load(f)
                if isinstance(insights, list):
                    for item in insights:
                        date_str = item.get('created_at', '').split(' ')[0]
                        trigger = item.get('trigger_topic', '')
                        insight_content = item.get('insight', '')
                        strategy = item.get('strategy', '')
                        if insight_content:
                            content = (
                                f"【過去の夢・深層心理の記録 ({date_str})】\n"
                                f"トリガー: {trigger}\n"
                                f"気づき: {insight_content}\n"
                                f"指針: {strategy}"
                            )
                            dynamic_docs.append(Document(
                                page_content=content,
                                metadata={"source": "insights.json", "type": "dream_insight", "date": date_str}
                            ))
                    print(f"  - 夢日記から {len(insights)} 件の洞察をインデックス化しました。")
            except Exception as e: print(f"Warning: Failed to read insights.json: {e}")

        if dynamic_docs:
            # チャンクサイズを小さく
            text_splitter = RecursiveCharacterTextSplitter(chunk_size=300, chunk_overlap=50)
            dynamic_splits = text_splitter.split_documents(dynamic_docs)
            
            # バッチ処理メソッドを使用
            # 常に新規作成（上書き）
            dynamic_db = self._create_index_in_batches(dynamic_splits, existing_db=None)
            
            if dynamic_db:
                self._safe_save_index(dynamic_db, self.dynamic_index_path)
                messages.append(f"知識・現行ログ: {len(dynamic_docs)}ファイルを更新")
            else:
                messages.append("知識・現行ログ: 作成失敗")
        else:
            if self.dynamic_index_path.exists():
                shutil.rmtree(str(self.dynamic_index_path))
            messages.append("知識・現行ログ: 対象なし")

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