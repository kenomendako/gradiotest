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

from langchain_core.embeddings import Embeddings
from langchain_community.vectorstores import FAISS
from langchain_community.docstore.document import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from google.api_core import exceptions as google_exceptions

import constants
import config_manager
import utils

# ロギング設定
logger = logging.getLogger(__name__)


class LangChainEmbeddingWrapper(Embeddings):
    """ローカルエンベディングをLangChainのインターフェースでラップ"""
    
    def __init__(self, local_provider):
        self.local_provider = local_provider
    
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        # local_provider.embed_documents は np.ndarray を返す想定
        embeddings = self.local_provider.embed_documents(texts)
        return embeddings.tolist()
    
    def embed_query(self, text: str) -> List[float]:
        # local_provider.embed_query は np.ndarray を返す想定
        embedding = self.local_provider.embed_query(text)
        return embedding.tolist()


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

        # エンベディングモードを設定から取得
        effective_settings = config_manager.get_effective_settings(room_name)
        self.embedding_mode = effective_settings.get("embedding_mode", "api")
        
        if self.embedding_mode == "local":
            # ローカルエンベディングを使用
            try:
                from topic_cluster_manager import LocalEmbeddingProvider
                local_provider = LocalEmbeddingProvider()
                self.embeddings = LangChainEmbeddingWrapper(local_provider)
                print(f"[RAGManager] ローカルエンベディングモードで初期化")
            except Exception as e:
                print(f"[RAGManager] ローカルエンベディング初期化失敗、APIにフォールバック: {e}")
                from langchain_google_genai import GoogleGenerativeAIEmbeddings
                self.embeddings = GoogleGenerativeAIEmbeddings(
                    model=constants.EMBEDDING_MODEL,
                    google_api_key=self.api_key,
                    task_type="retrieval_document"
                )
        else:
            # Gemini API エンベディングを使用
            from langchain_google_genai import GoogleGenerativeAIEmbeddings
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
            temp_index_path = Path(temp_dir)
            try:
                # インデックスを一時フォルダにコピー
                shutil.copytree(str(target_path), str(temp_index_path), dirs_exist_ok=True)
                
                # モードに応じたエンベディング（query用）を使用
                query_embeddings = self.embeddings # 既に初期化済みのものを使用
                
                # Gemini API の場合はタスクタイプを query に変更した新しいインスタンスが必要な場合があるが、
                # langchain_google_genai は内部で処理する場合が多い。
                # ローカルモードの場合は self.embeddings がそのまま使える。
                
                return FAISS.load_local(
                    str(temp_index_path),
                    query_embeddings,
                    allow_dangerous_deserialization=True
                )
            except Exception as e:
                print(f"Index load error: {e}")
                return None

    def _create_index_in_batches(self, splits: List[Document], existing_db: Optional[FAISS] = None, progress_callback=None) -> FAISS:
        """
        大量のドキュメントをバッチ分割し、レート制限を回避しながらインデックスを作成/追記する。
        progress_callback: 進捗を報告するコールバック関数 (batch_num, total_batches) -> None
        """
        BATCH_SIZE = 20
        db = existing_db
        total_splits = len(splits)
        total_batches = (total_splits + BATCH_SIZE - 1) // BATCH_SIZE
        
        print(f"    [BATCH] 開始: {total_splits} チャンク, {total_batches} バッチ")
        if progress_callback:
            progress_callback(0, total_batches)

        for i in range(0, total_splits, BATCH_SIZE):
            batch = splits[i : i + BATCH_SIZE]
            batch_num = (i // BATCH_SIZE) + 1
            
            # リトライループ
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    if db is None:
                        db = FAISS.from_documents(batch, self.embeddings)
                    else:
                        db.add_documents(batch)
                    
                    # 進捗を報告
                    if progress_callback:
                        progress_callback(batch_num, total_batches)
                    
                    if self.embedding_mode == "api":
                        time.sleep(2) 
                    break 
                
                except Exception as e:
                    error_str = str(e)
                    print(f"      ! ベクトル化エラー (試行 {attempt+1}/{max_retries}): {e}")
                    if "429" in error_str or "ResourceExhausted" in error_str:
                        wait_time = 10 * (attempt + 1)
                        print(f"      ! API制限検知。{wait_time}秒待機してリトライ...")
                        time.sleep(wait_time)
                    else:
                        if attempt == max_retries - 1:
                            print(f"      ! このバッチをスキップします。最終エラー: {e}")
                            traceback.print_exc()
                        if self.embedding_mode == "api":
                            time.sleep(2)
        
        print(f"    [BATCH] 全バッチ処理完了")
        return db

    def update_memory_index(self, status_callback=None) -> str:
        """
        記憶用インデックスを更新する（過去ログ、エピソード記憶、夢日記）
        """
        def report(message):
            print(f"--- [RAG Memory] {message}")
            if status_callback: status_callback(message)

        report("記憶索引を更新中: 過去ログ、エピソード記憶、夢日記の差分を確認...")
        
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

        # 4. 現行ログ (log.txt) - 動的インデックスで処理するため、ここでは除外
        # 現行ログは頻繁に変更されるため、毎回再構築する動的インデックス側で処理する方が効率的

        # --- 実行: 小分けにして保存しながら進む ---
        if pending_items:
            total_pending = len(pending_items)
            report(f"新規追加アイテム: {total_pending}件。処理中...")
            
            static_db = self._safe_load_index(self.static_index_path)
            SAVE_INTERVAL = 5 
            text_splitter = RecursiveCharacterTextSplitter(chunk_size=300, chunk_overlap=50)
            processed_count = 0
            
            for i in range(0, total_pending, SAVE_INTERVAL):
                batch_items = pending_items[i : i + SAVE_INTERVAL]
                batch_docs = [item[1] for item in batch_items]
                batch_ids = [item[0] for item in batch_items]
                
                print(f"  - グループ処理中 ({i+1}〜{min(i+SAVE_INTERVAL, total_pending)} / {total_pending})...")
                splits = text_splitter.split_documents(batch_docs)
                static_db = self._create_index_in_batches(splits, existing_db=static_db)
                
                if static_db:
                    self._safe_save_index(static_db, self.static_index_path)
                    processed_records.update(batch_ids)
                    self._save_processed_record(processed_records)
                    processed_count += len(batch_items)
                else:
                    print(f"    ! グループ処理失敗。")

            result_msg = f"記憶索引: {processed_count}件を追加保存"
        else:
            result_msg = "記憶索引: 差分なし"
        
        print(f"--- [RAG Memory] 完了: {result_msg} ---")
        return result_msg

    def update_knowledge_index(self, status_callback=None) -> str:
        """
        知識用インデックスを更新する（knowledgeフォルダ内のドキュメントのみ）
        """
        def report(message):
            print(f"--- [RAG Knowledge] {message}")
            if status_callback: status_callback(message)

        report("知識索引を再構築中...")
        dynamic_docs = []
        
        knowledge_dir = self.room_dir / "knowledge"
        if knowledge_dir.exists():
            for f in list(knowledge_dir.glob("*.txt")) + list(knowledge_dir.glob("*.md")):
                try:
                    content = f.read_text(encoding="utf-8")
                    dynamic_docs.append(Document(page_content=content, metadata={"source": f.name, "type": "knowledge"}))
                except Exception: pass

        # 知識ドキュメントのみ処理（現行ログは別ボタンで処理）
        if dynamic_docs:
            text_splitter = RecursiveCharacterTextSplitter(chunk_size=300, chunk_overlap=50)
            dynamic_splits = text_splitter.split_documents(dynamic_docs)
            dynamic_db = self._create_index_in_batches(dynamic_splits, existing_db=None)
            
            if dynamic_db:
                self._safe_save_index(dynamic_db, self.dynamic_index_path)
                result_msg = f"知識索引: {len(dynamic_docs)}ファイルを更新"
            else:
                result_msg = "知識索引: 作成失敗"
        else:
            if self.dynamic_index_path.exists():
                shutil.rmtree(str(self.dynamic_index_path))
            result_msg = "知識索引: 対象なし"

        print(f"--- [RAG Knowledge] 完了: {result_msg} ---")
        return result_msg

    def update_current_log_index_with_progress(self):
        """
        現行ログ（log.txt）のみをインデックス化する（進捗をyieldするジェネレーター版）
        yields: (batch_num, total_batches, status_message)
        """
        current_log_path = self.room_dir / "log.txt"
        if not current_log_path.exists():
            yield (0, 0, "現行ログ: ファイルが存在しません")
            return
        
        try:
            content = current_log_path.read_text(encoding="utf-8")
            
            if not content.strip():
                yield (0, 0, "現行ログ: 空のファイルです")
                return
            
            doc = Document(page_content=content, metadata={"source": "log.txt", "type": "current_log"})
            
            text_splitter = RecursiveCharacterTextSplitter(chunk_size=300, chunk_overlap=50)
            splits = text_splitter.split_documents([doc])
            
            BATCH_SIZE = 20
            total_batches = (len(splits) + BATCH_SIZE - 1) // BATCH_SIZE
            
            yield (0, total_batches, f"開始: {len(splits)}チャンク, {total_batches}バッチ")
            
            db = None
            for i in range(0, len(splits), BATCH_SIZE):
                batch = splits[i : i + BATCH_SIZE]
                batch_num = (i // BATCH_SIZE) + 1
                
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        if db is None:
                            db = FAISS.from_documents(batch, self.embeddings)
                        else:
                            db.add_documents(batch)
                        
                        yield (batch_num, total_batches, f"処理中: {batch_num}/{total_batches} バッチ完了")
                        if self.embedding_mode == "api":
                            time.sleep(2)
                        break
                    except Exception as e:
                        error_str = str(e)
                        print(f"      ! [CurrentLog] ベクトル化エラー (試行 {attempt+1}/{max_retries}): {e}")
                        if "429" in error_str or "ResourceExhausted" in error_str:
                            wait_time = 10 * (attempt + 1)
                            yield (batch_num, total_batches, f"API制限 - {wait_time}秒待機中...")
                            time.sleep(wait_time)
                        else:
                            if attempt == max_retries - 1:
                                yield (batch_num, total_batches, f"エラー: バッチ{batch_num}をスキップ")
                                print(f"      ! このバッチをスキップします。最終エラー: {e}")
                                traceback.print_exc()
                            if self.embedding_mode == "api":
                                time.sleep(2)
            
            if db:
                current_log_index_path = self.room_dir / "rag_data" / "current_log_index"
                self._safe_save_index(db, current_log_index_path)
                yield (total_batches, total_batches, f"✅ 現行ログ: {len(splits)}チャンクを索引化完了")
            else:
                yield (0, total_batches, "現行ログ: 索引化失敗")
                
        except Exception as e:
            import traceback
            traceback.print_exc()
            yield (0, 0, f"エラー: {e}")

    def create_or_update_index(self, status_callback=None) -> str:
        """
        後方互換用ラッパー: 記憶索引と知識索引の両方を更新する
        """
        memory_result = self.update_memory_index(status_callback)
        knowledge_result = self.update_knowledge_index(status_callback)
        
        final_msg = f"{memory_result} / {knowledge_result}"
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