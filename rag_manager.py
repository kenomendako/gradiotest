# rag_manager.py (v3: Complete & Verbose)

import os
import shutil
import tempfile
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
        
        # 2つのインデックスパスを定義
        self.static_index_path = self.rag_data_dir / "faiss_index_static" # 過去ログ用（追記型）
        self.dynamic_index_path = self.rag_data_dir / "faiss_index_dynamic" # ナレッジ・現行ログ用（再構築型）
        
        # 処理済みファイルの記録用
        self.processed_files_record = self.rag_data_dir / "processed_static_files.json"
        
        # ディレクトリの保証
        self.rag_data_dir.mkdir(parents=True, exist_ok=True)

        # Embeddingモデルの初期化
        self.embeddings = GoogleGenerativeAIEmbeddings(
            model=constants.EMBEDDING_MODEL,
            google_api_key=self.api_key,
            task_type="retrieval_document"
        )

    def _load_processed_record(self) -> Set[str]:
        """処理済み静的ファイルのリストを読み込む"""
        if self.processed_files_record.exists():
            try:
                with open(self.processed_files_record, 'r', encoding='utf-8') as f:
                    return set(json.load(f))
            except Exception:
                return set()
        return set()

    def _save_processed_record(self, processed_files: Set[str]):
        """処理済み静的ファイルのリストを保存する"""
        with open(self.processed_files_record, 'w', encoding='utf-8') as f:
            json.dump(list(processed_files), f, indent=2, ensure_ascii=False)

    def _safe_save_index(self, db: FAISS, target_path: Path):
        """FAISSインデックスを安全に保存する（日本語パス対策）"""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            db.save_local(str(temp_path))
            
            if target_path.exists():
                shutil.rmtree(str(target_path))
            shutil.move(str(temp_path), str(target_path))

    def _safe_load_index(self, target_path: Path) -> Optional[FAISS]:
        """FAISSインデックスを安全に読み込む（日本語パス対策）"""
        if not target_path.exists():
            return None
            
        with tempfile.TemporaryDirectory() as temp_dir:
            # フォルダごと一時領域にコピー
            temp_index_path = Path(temp_dir) / "index_copy"
            shutil.copytree(str(target_path), str(temp_index_path))
            
            try:
                # 検索用設定でロード
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

    def create_or_update_index(self, status_callback=None) -> str:
        """
        インデックスの更新プロセスを実行する。
        1. 静的インデックス（過去ログ）: 差分のみ追加
        2. 動的インデックス（知識・現行ログ）: 完全再構築
        """
        # --- 内部ヘルパー: 進捗を表示・通知する ---
        def report(message):
            print(f"--- [RAG] {message}") # コンソールに出力
            if status_callback:
                status_callback(message) # UIに通知

        messages = []
        
        # --- Phase 1: 静的インデックス（過去ログ）の更新 ---
        report("Phase 1: 過去ログアーカイブを確認中...")
        
        processed_files = self._load_processed_record()
        new_static_docs = []
        new_processed_files = set()
        
        archives_dir = self.room_dir / "log_archives"
        if archives_dir.exists():
            all_archives = list(archives_dir.glob("*.txt"))
            total_archives = len(all_archives)
            print(f"  - アーカイブフォルダ内のファイル数: {total_archives}")
            
            for i, f in enumerate(all_archives):
                # ファイル名が記録になければ「新規」とみなす
                if f.name not in processed_files:
                    try:
                        content = f.read_text(encoding="utf-8")
                        if content.strip():
                            new_static_docs.append(Document(
                                page_content=content, 
                                metadata={"source": f.name, "type": "log_archive", "path": str(f)}
                            ))
                            new_processed_files.add(f.name)
                            # print(f"    - 新規検出: {f.name}")
                    except Exception as e:
                        print(f"Failed to read archive {f.name}: {e}")

        static_update_count = 0
        if new_static_docs:
            report(f"過去ログの新規追加分 ({len(new_static_docs)}ファイル) を処理中... ベクトル化を実行します。")
            
            text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
            static_splits = text_splitter.split_documents(new_static_docs)
            print(f"  - チャンク分割完了: {len(static_splits)} チャンク")
            
            # 既存のインデックスがあればロードして追加、なければ新規作成
            static_db = self._safe_load_index(self.static_index_path)
            
            if static_db:
                print("  - 既存の静的インデックスに追加します...")
                static_db.add_documents(static_splits)
            else:
                print("  - 新規に静的インデックスを作成します...")
                static_db = FAISS.from_documents(static_splits, self.embeddings)
            
            self._safe_save_index(static_db, self.static_index_path)
            
            # 処理済みリストを更新
            processed_files.update(new_processed_files)
            self._save_processed_record(processed_files)
            
            static_update_count = len(new_static_docs)
            messages.append(f"過去ログ: {static_update_count}ファイルを新規追加")
        else:
            print("  - 過去ログに新規追加ファイルはありませんでした。")
            messages.append("過去ログ: 差分なし")

        # --- Phase 2: 動的インデックス（知識・現行ログ）の再構築 ---
        report("Phase 2: 知識ベースと現行ログ、エピソード記憶を処理中...")
        
        dynamic_docs = []
        
        # 知識ベース
        knowledge_dir = self.room_dir / "knowledge"
        if knowledge_dir.exists():
            for f in list(knowledge_dir.glob("*.txt")) + list(knowledge_dir.glob("*.md")):
                try:
                    content = f.read_text(encoding="utf-8")
                    dynamic_docs.append(Document(page_content=content, metadata={"source": f.name, "type": "knowledge"}))
                except Exception:
                    pass

        # 現行ログ
        current_log_path = self.room_dir / "log.txt"
        if current_log_path.exists():
             try:
                content = current_log_path.read_text(encoding="utf-8")
                dynamic_docs.append(Document(page_content=content, metadata={"source": "log.txt", "type": "current_log"}))
             except Exception:
                pass

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
                            # 検索に引っかかりやすい形式に整形
                            content = f"日付: {date_str}\n内容: {summary}"
                            dynamic_docs.append(Document(
                                page_content=content,
                                metadata={
                                    "source": "episodic_memory.json",
                                    "type": "episodic_memory",
                                    "date": date_str
                                }
                            ))
                    print(f"  - エピソード記憶から {len(episodes)} 件をインデックス化しました。")
            except Exception as e:
                print(f"Warning: Failed to read episodic_memory.json: {e}")

        dynamic_count = 0
        if dynamic_docs:
            text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
            dynamic_splits = text_splitter.split_documents(dynamic_docs)
            
            # 常に新規作成（上書き）
            dynamic_db = FAISS.from_documents(dynamic_splits, self.embeddings)
            self._safe_save_index(dynamic_db, self.dynamic_index_path)
            dynamic_count = len(dynamic_docs)
            messages.append(f"知識・現行ログ: {dynamic_count}ファイルを更新")
        else:
            # ドキュメントがない場合は、古いインデックスがあれば削除しておく
            if self.dynamic_index_path.exists():
                shutil.rmtree(str(self.dynamic_index_path))
            messages.append("知識・現行ログ: 対象なし")

        final_msg = " / ".join(messages)
        print(f"--- [RAG] 処理完了: {final_msg} ---")
        return final_msg

    def search(self, query: str, k: int = 4) -> List[Document]:
        """静的・動的インデックスの両方を検索し、結果を統合する"""
        results = []
        
        # 1. 動的インデックス（優先度高：知識や最新ログ）
        dynamic_db = self._safe_load_index(self.dynamic_index_path)
        if dynamic_db:
            # 動的からは多めに取得
            results.extend(dynamic_db.similarity_search(query, k=k))

        # 2. 静的インデックス（過去ログ）
        static_db = self._safe_load_index(self.static_index_path)
        if static_db:
            results.extend(static_db.similarity_search(query, k=k))

        # 統合した結果を返す（本当はスコアで再ソートすべきだが、まずは単純結合）
        # 件数が多すぎるとコンテキストを圧迫するので、合計で最大 k+2 件程度に絞る
        return results[:k+2]