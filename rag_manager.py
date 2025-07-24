# -*- coding: utf-8 -*-
import os
import json
import traceback
import faiss
import numpy as np
from typing import List, Optional
import tempfile
import shutil

import google.genai as genai # Clientを直接使うために、インポートをgenaiに統一

# モジュールインポート
import character_manager
# import gemini_api # gemini_apiへの依存を削除
from utils import load_chat_log
# import config_manager # config_managerへの直接依存を削除
# import mem0_manager # 二重らせん記憶システムのために追加
from langchain_core.tools import tool


# 定数定義
RAG_DIR = "rag_data"
RAG_INDEX_FILENAME = "rag_index.faiss"
RAG_CHUNKS_FILENAME = "rag_chunks.json"
EMBEDDING_MODEL = "text-embedding-004"

def _get_rag_data_path(character_name: str) -> Optional[str]:
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
    if not text: return []
    return [text[i:i+chunk_size] for i in range(0, len(text), chunk_size - chunk_overlap)]

def create_or_update_index(character_name: str, api_key: str) -> bool:
    print(f"--- RAG索引作成開始: {character_name} ---")

    # APIキーでクライアントを生成
    try:
        client = genai.Client(api_key=api_key)
    except Exception as e:
        print(f"エラー: APIキーを使用してGeminiクライアントの生成に失敗しました: {e}")
        traceback.print_exc()
        return False

    # log_f, sys_p, _, mem_p = character_manager.get_character_files_paths(character_name) # 元の行
    log_f, _, _, mem_p, _ = character_manager.get_character_files_paths(character_name) # sys_p と notepad_path を受け取らないように変更
    rag_path = _get_rag_data_path(character_name)

    # ★★★ RAGの知識源は memory.json のみになったので、その存在だけをチェック ★★★
    if not rag_path:
        print(f"エラー: {character_name} のRAGデータパスが取得できません。")
        return False
    if not os.path.exists(mem_p):
        print(f"エラー: {character_name} の記憶ファイル (memory.json) が見つかりません。RAGの知識源がありません。")
        return False

    all_chunks = []
    try:
        # ★★★ memory.json の読み込みは残す ★★★
        if os.path.exists(mem_p):
            with open(mem_p, "r", encoding="utf-8") as f:
                mem_data = json.load(f)
                for key, value in mem_data.items():
                    if value:
                        text = f"記憶（{key}）: {json.dumps(value, ensure_ascii=False)}"
                        all_chunks.extend(_chunk_text(text))

    except Exception as e:
        print(f"知識源の読み込みとチャンク化でエラー: {e}"); traceback.print_exc()
        return False

    if not all_chunks:
        print(f"情報: {character_name} のRAG索引に含めるチャンクがありません。")
        return True

    print(f"情報: {len(all_chunks)}個のチャンクをベクトル化します (モデル: models/{EMBEDDING_MODEL})...")

    all_embeddings_objects = []
    batch_size = 100
    try:
        for i in range(0, len(all_chunks), batch_size):
            batch_chunks = all_chunks[i:i + batch_size]
            print(f"  - バッチ {i//batch_size + 1} を処理中 (チャンク数: {len(batch_chunks)})...")
            result = client.models.embed_content(model=f"models/{EMBEDDING_MODEL}", contents=batch_chunks)
            all_embeddings_objects.extend(result.embeddings)
    except Exception as e:
        print(f"Embedding API呼び出しでエラー (モデル: models/{EMBEDDING_MODEL}): {e}"); traceback.print_exc()
        return False

    if not all_embeddings_objects:
        print("エラー: Embedding APIから有効なベクトルデータオブジェクトが得られませんでした。")
        return False

    print("情報: FAISSインデックスを構築しています...")
    tmp_index_path = None
    try:
        embedding_values = [emb.values for emb in all_embeddings_objects if hasattr(emb, 'values')]
        if not embedding_values:
            print("エラー: Embeddingオブジェクトからベクトル値を抽出できませんでした。")
            return False

        dimension = len(embedding_values[0])
        index = faiss.IndexFlatL2(dimension)

        vectors_to_add = np.array(embedding_values, dtype='float32')
        index.add(vectors_to_add)

        index_file_target = os.path.join(rag_path, RAG_INDEX_FILENAME)
        chunks_file = os.path.join(rag_path, RAG_CHUNKS_FILENAME)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".faiss", mode="wb") as tmp_file:
            tmp_index_path = tmp_file.name

        faiss.write_index(index, tmp_index_path)

        shutil.move(tmp_index_path, index_file_target)
        tmp_index_path = None

        with open(chunks_file, "w", encoding="utf-8") as f:
            json.dump(all_chunks, f, ensure_ascii=False, indent=2)
        print(f"--- RAG索引作成完了: {character_name} ({index.ntotal}件) ---")
        return True
    except Exception as e:
        print(f"FAISSインデックスの構築または保存でエラー: {e}"); traceback.print_exc()
        return False
    finally:
        if tmp_index_path and os.path.exists(tmp_index_path):
            os.remove(tmp_index_path)

# search_relevant_chunks は diary_search_tool で使用するため維持
def search_relevant_chunks(character_name: str, query_text: str, api_key: str, top_k: int = 5) -> List[str]:
    if not api_key:
        print("エラー: RAG検索にはAPIキーが必要です。")
        return []
    # APIキーでクライアントを生成
    try:
        client = genai.Client(api_key=api_key)
    except Exception as e:
        print(f"エラー: APIキーを使用してGeminiクライアントの生成に失敗しました: {e}")
        traceback.print_exc()
        return []

    rag_path = _get_rag_data_path(character_name)
    if not rag_path: return []
    index_file_source = os.path.join(rag_path, RAG_INDEX_FILENAME)
    chunks_file = os.path.join(rag_path, RAG_CHUNKS_FILENAME)

    if not os.path.exists(index_file_source) or not os.path.exists(chunks_file):
        print(f"情報: {character_name} のRAG索引(手帳)が未作成です。検索をスキップします。")
        return []

    tmp_read_path = None
    try:
        # FAISSインデックスとチャンクを読み込む
        with tempfile.NamedTemporaryFile(delete=False, suffix=".faiss", mode="wb") as tmp_file: # mode="wb" はコピーのため
            tmp_read_path = tmp_file.name
        shutil.copyfile(index_file_source, tmp_read_path) # 安全な読み込みのために一時ファイルにコピー
        index = faiss.read_index(tmp_read_path)

        with open(chunks_file, "r", encoding="utf-8") as f:
            all_chunks = json.load(f)

        # クエリをベクトル化
        result = client.models.embed_content(model=f"models/{EMBEDDING_MODEL}", contents=[query_text])
        query_embeddings_objects = result.embeddings
        if not query_embeddings_objects or not hasattr(query_embeddings_objects[0], 'values'):
            print(f"エラー: クエリ '{query_text[:20]}...' のEmbeddingオブジェクトまたはそのvalues属性が無効です。")
            return []
        query_embedding_vector = query_embeddings_objects[0].values
        query_embedding = np.array([query_embedding_vector], dtype='float32')

        # FAISSで検索
        distances, indices = index.search(query_embedding, top_k)
        relevant_chunks = [all_chunks[i] for i in indices[0] if i != -1 and 0 <= i < len(all_chunks)] # 範囲チェックを追加
        print(f"--- 手帳検索実行 (Character: {character_name}, Query: '{query_text}', Found: {len(relevant_chunks)} chunks) ---")
        return relevant_chunks
    except Exception as e:
        print(f"手帳(FAISS)検索エラー: {e}"); traceback.print_exc()
        return []
    finally:
        if tmp_read_path and os.path.exists(tmp_read_path):
            os.remove(tmp_read_path)

@tool
def diary_search_tool(query: str, character_name: str, api_key: str) -> str:
    """AI自身の意志で書き留めた「手帳(memory.json)」の内容を検索します。AI自身の内面的な誓い、秘密の独白、ユーザーから与えられた特別な許可、主観的な感情の記録など、魂の歴史を確認したい時に使用します。"""
    print(f"--- 手帳検索ツール呼び出し (Query: '{query}', Character: '{character_name}') ---")
    relevant_chunks = search_relevant_chunks(character_name, query, api_key, top_k=5) # top_kを5に戻す

    if not relevant_chunks:
        print(f"--- 手帳検索実行 (Character: {character_name}, Query: '{query}', Found: 0 chunks) ---")
        return "[]" # 結果がない場合は空のJSON配列を返す

    print(f"--- 手帳検索実行 (Character: {character_name}, Query: '{query}', Found: {len(relevant_chunks)} chunks) ---")

    # 検索結果のチャンクをJSON文字列として返す
    return json.dumps(relevant_chunks, ensure_ascii=False, indent=2)

@tool
def conversation_memory_search_tool(query: str, character_name: str, api_key: str) -> str:
    """【現在使用不可】ユーザーとの過去の具体的な会話のやり取り（ログ）を検索します。"""
    return "この機能は現在、無効化されています (Mem0 is disabled)。"

@tool
def search_conversation_memory_for_summary(character_name: str, query: str, api_key: str, limit: int = 5) -> str:
    """【現在使用不可】memory_weaver_nodeのために、Mem0の記憶を検索します。"""
    return "この機能は現在、無効化されています (Mem0 is disabled)。"
