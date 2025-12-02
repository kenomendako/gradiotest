# rag_manager.py

import os
import shutil
import tempfile
from pathlib import Path
from typing import List, Dict, Optional
import traceback
import logging

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
        self.index_path = self.rag_data_dir / "faiss_index"
        
        # ディレクトリの保証
        self.rag_data_dir.mkdir(parents=True, exist_ok=True)

        # Embeddingモデルの初期化
        self.embeddings = GoogleGenerativeAIEmbeddings(
            model=constants.EMBEDDING_MODEL,
            google_api_key=self.api_key,
            # document作成時は "retrieval_document" だが、検索時は "retrieval_query"
            # LangChainの仕様上、初期化時に指定が必要だが、メソッド呼び出しで上書きされる挙動を期待
            task_type="retrieval_document" 
        )

    def _get_safe_index_path(self) -> str:
        """FAISSの日本語パス問題を回避するための一時パスを取得する"""
        # 一時ディレクトリを作成してそのパスを返す実装を予定
        # 現時点ではプレースホルダー
        return str(self.index_path)

    def create_or_update_index(self, status_callback=None) -> str:
        """
        知識ベース(knowledge/)と過去ログ(log_archives/)からインデックスを作成/更新する。
        """
        if status_callback: status_callback("ドキュメントを収集中...")
        
        documents = []
        
        # 1. 知識ベースドキュメントの読み込み
        knowledge_dir = self.room_dir / "knowledge"
        if knowledge_dir.exists():
            for f in list(knowledge_dir.glob("*.txt")) + list(knowledge_dir.glob("*.md")):
                try:
                    content = f.read_text(encoding="utf-8")
                    documents.append(Document(page_content=content, metadata={"source": f.name, "type": "knowledge"}))
                except Exception as e:
                    print(f"Warning: Failed to read {f.name}: {e}")

        # 2. 過去ログの読み込み（ログアーカイブ）
        archives_dir = self.room_dir / "log_archives"
        if archives_dir.exists():
            for f in archives_dir.glob("*.txt"):
                try:
                    # ここにログ専用のチャンク分割ロジックが入る予定
                    # とりあえず全文を1つとして読み込む（後で改良）
                    content = f.read_text(encoding="utf-8")
                    documents.append(Document(page_content=content, metadata={"source": f.name, "type": "log_archive"}))
                except Exception as e:
                    print(f"Warning: Failed to read log archive {f.name}: {e}")

        # 3. 現行ログの読み込み
        current_log_path = self.room_dir / "log.txt"
        if current_log_path.exists():
             try:
                content = current_log_path.read_text(encoding="utf-8")
                # 現行ログは変動が激しいので扱い注意だが、一旦対象に含める
                documents.append(Document(page_content=content, metadata={"source": "log.txt", "type": "current_log"}))
             except Exception as e:
                print(f"Warning: Failed to read log.txt: {e}")

        if not documents:
            return "インデックス化するドキュメントが見つかりませんでした。"

        # 4. チャンク分割
        if status_callback: status_callback(f"{len(documents)}ファイルの分割処理中...")
        
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
        splits = text_splitter.split_documents(documents)

        # 5. ベクトル化と保存
        if status_callback: status_callback(f"{len(splits)}チャンクのベクトル化を実行中...")
        
        try:
            # 日本語パス対策：一時ディレクトリで作成してから移動
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_index_path = Path(temp_dir)
                
                # FAISSインデックス作成 (バッチ処理は内部で行われるが、大量の場合は分割が必要かも)
                db = FAISS.from_documents(splits, self.embeddings)
                db.save_local(str(temp_index_path))
                
                # 本番パスへ移動
                if self.index_path.exists():
                    shutil.rmtree(str(self.index_path))
                shutil.move(str(temp_index_path), str(self.index_path))
                
            return f"インデックス作成完了: 合計 {len(splits)} チャンクを登録しました。"
            
        except Exception as e:
            traceback.print_exc()
            return f"インデックス作成中にエラーが発生しました: {e}"

    def search(self, query: str, k: int = 4) -> List[Document]:
        """クエリに基づいて類似ドキュメントを検索する"""
        if not self.index_path.exists():
            return []

        try:
            # 検索用Embeddings (queryモード)
            query_embeddings = GoogleGenerativeAIEmbeddings(
                model=constants.EMBEDDING_MODEL,
                google_api_key=self.api_key,
                task_type="retrieval_query"
            )

            # 日本語パス対策：一時ディレクトリにコピーしてロード
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_index_path = Path(temp_dir) / "faiss_index"
                shutil.copytree(str(self.index_path), str(temp_index_path))
                
                db = FAISS.load_local(
                    str(temp_index_path),
                    query_embeddings,
                    allow_dangerous_deserialization=True
                )
                return db.similarity_search(query, k=k)
                
        except Exception as e:
            print(f"RAG Search Error: {e}")
            return []