# -*- coding: utf-8 -*-
import os
import json
import traceback
import faiss
import numpy as np
from typing import List, Optional

# モジュールインポート
import character_manager
import gemini_api # gemini_apiモジュールをインポートしてクライアントを使用
from utils import load_chat_log

# 定数定義
RAG_DIR = "rag_data"
RAG_INDEX_FILENAME = "rag_index.faiss"
RAG_CHUNKS_FILENAME = "rag_chunks.json"
EMBEDDING_MODEL = "text-embedding-004"

def _get_rag_data_path(character_name: str) -> Optional[str]:
    # (この関数は変更なし)
    if not character_name: return None
    try:
        char_base_path = os.path.join(character_manager.CHARACTERS_DIR, character_name)
        rag_path = os.path.join(char_base_path, RAG_DIR)
        os.makedirs(rag_path, exist_ok=True)
        return rag_path
    except Exception as e:
        print(f"RAGディレクトリ作成エラー ({character_name}): {e}")
        return None

def _chunk_text(text: str, chunk_size: int = 500, chunk_overlap: int = 50) -> List[str]:
    # (この関数は変更なし)
    if not text: return []
    return [text[i:i+chunk_size] for i in range(0, len(text), chunk_size - chunk_overlap)]

def create_or_update_index(character_name: str) -> bool:
    print(f"--- RAG索引作成開始: {character_name} ---")
    if not gemini_api._gemini_client:
        print("エラー: Geminiクライアントが初期化されていません。UIでAPIキーが選択・設定されているか確認してください。")
        return False

    log_f, sys_p, _, mem_p = character_manager.get_character_files_paths(character_name)
    rag_path = _get_rag_data_path(character_name)

    if not rag_path: # rag_path が取れなければ致命的
        print(f"エラー: {character_name} のRAGデータパスが取得できません。")
        return False
    if not os.path.exists(mem_p) and not os.path.exists(sys_p):
        print(f"エラー: {character_name} の記憶ファイル (memory.json) またはシステムプロンプト (system_prompt.txt) が見つかりません。RAGの知識源がありません。")
        return False # 知識源がない場合は索引を作れないのでエラーとする

    all_chunks = []
    try:
        if os.path.exists(mem_p):
            with open(mem_p, "r", encoding="utf-8") as f:
                mem_data = json.load(f)
                for key, value in mem_data.items():
                    if value:
                        text = f"記憶（{key}）: {json.dumps(value, ensure_ascii=False)}"
                        all_chunks.extend(_chunk_text(text))
        if os.path.exists(sys_p):
            with open(sys_p, "r", encoding="utf-8") as f:
                prompt_text = f.read().strip()
                if prompt_text: # 空でなければチャンク化
                    all_chunks.extend(_chunk_text(f"システム指示: {prompt_text}"))
    except Exception as e:
        print(f"知識源の読み込みとチャンク化でエラー: {e}"); traceback.print_exc()
        return False

    if not all_chunks:
        print(f"情報: {character_name} のRAG索引に含めるチャンクがありません。memory.json や system_prompt.txt の内容を確認してください。")
        return True # チャンクがなくても処理は試みたとしてTrue

    print(f"情報: {len(all_chunks)}個のチャンクをベクトル化します (モデル: models/{EMBEDDING_MODEL})...")
    try:
        # ★★★ これが唯一の正しいAPI呼び出し方法です ★★★
        result = gemini_api._gemini_client.models.embed_content(
            model=f"models/{EMBEDDING_MODEL}", # モデル名は "models/" プレフィックスが必要
            contents=all_chunks, # content を contents に修正
            task_type="RETRIEVAL_DOCUMENT"
        )
        embeddings = result['embedding']
    except Exception as e:
        print(f"Embedding API呼び出しでエラー (モデル: models/{EMBEDDING_MODEL}): {e}"); traceback.print_exc()
        return False

    try:
        dimension = len(embeddings[0])
        index = faiss.IndexFlatL2(dimension)
        index.add(np.array(embeddings, dtype='float32'))
        index_file = os.path.join(rag_path, RAG_INDEX_FILENAME)
        chunks_file = os.path.join(rag_path, RAG_CHUNKS_FILENAME)
        faiss.write_index(index, index_file)
        with open(chunks_file, "w", encoding="utf-8") as f:
            json.dump(all_chunks, f, ensure_ascii=False, indent=2)
        print(f"--- RAG索引作成完了: {character_name} ({index.ntotal}件) ---")
        return True
    except Exception as e:
        print(f"FAISSインデックスの構築または保存でエラー: {e}"); traceback.print_exc()
        return False


def search_relevant_chunks(character_name: str, query_text: str, top_k: int = 5) -> List[str]: # top_k はここでデフォルト値を設定
    if not gemini_api._gemini_client:
        print("エラー(検索時): Geminiクライアントが初期化されていません。UIでAPIキーが選択・設定されているか確認してください。")
        return []

    rag_path = _get_rag_data_path(character_name)
    if not rag_path: return []
    index_file = os.path.join(rag_path, RAG_INDEX_FILENAME)
    chunks_file = os.path.join(rag_path, RAG_CHUNKS_FILENAME)

    if not os.path.exists(index_file) or not os.path.exists(chunks_file):
        print(f"情報: {character_name} のRAG索引が未作成か、またはチャンクファイルが見つかりません。検索をスキップします。")
        return []

    try:
        index = faiss.read_index(index_file)
        with open(chunks_file, "r", encoding="utf-8") as f:
            all_chunks = json.load(f)

        # ★★★ これが唯一の正しいAPI呼び出し方法です ★★★
        result = gemini_api._gemini_client.models.embed_content(
            model=f"models/{EMBEDDING_MODEL}", # モデル名は "models/" プレフィックスが必要
            contents=[query_text], # content を contents に修正
            task_type="RETRIEVAL_QUERY"
        )
        query_embedding_list = result['embedding']
        if not query_embedding_list or not query_embedding_list[0]:
            print(f"エラー: クエリ '{query_text[:20]}...' のEmbedding結果が空、または無効です。")
            return []

        query_embedding = np.array(query_embedding_list, dtype='float32')

        distances, indices = index.search(query_embedding, top_k)
        relevant_chunks = [all_chunks[i] for i in indices[0] if i != -1 and 0 <= i < len(all_chunks)]
        # RAG検索結果のログ出力は呼び出し元の gemini_api.py で行う
        return relevant_chunks
    except Exception as e:
        print(f"RAG検索エラー: {e}"); traceback.print_exc()
        return []
