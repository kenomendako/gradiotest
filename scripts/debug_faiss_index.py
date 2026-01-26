#!/usr/bin/env python3
# debug_faiss_index.py - FAISSインデックスの中身を調査

import sys
sys.path.insert(0, '/home/baken/nexus_ark')

import os
os.chdir('/home/baken/nexus_ark')

from pathlib import Path
from langchain_community.vectorstores import FAISS
from langchain_google_genai import GoogleGenerativeAIEmbeddings
import config_manager
import constants

def investigate_index():
    room_name = "ルシアン"
    
    # APIキーを取得 - まずload_config()を呼び出す
    config_manager.load_config()  # これでGEMINI_API_KEYSがセットされる
    
    config = config_manager.load_config_file()
    api_key_name = config.get("last_api_key_used", "")
    api_key = config_manager.GEMINI_API_KEYS.get(api_key_name, "")
    
    if not api_key:
        # 最初のキーを使用
        if config_manager.GEMINI_API_KEYS:
            api_key = next(iter(config_manager.GEMINI_API_KEYS.values()), "")
    
    if not api_key:
        print("エラー: APIキーが見つかりません")
        print(f"GEMINI_API_KEYS: {list(config_manager.GEMINI_API_KEYS.keys())}")
        return
    
    print(f"使用するAPIキー名: {api_key_name or '最初のキー'}")
    
    # インデックスのパス
    room_dir = Path(constants.ROOMS_DIR) / room_name
    static_index_path = room_dir / "rag_data" / "faiss_index_static"
    
    print(f"\n静的インデックスパス: {static_index_path}")
    print(f"存在: {static_index_path.exists()}")
    
    if not static_index_path.exists():
        print("インデックスが存在しません")
        return
    
    # エンベディングを初期化
    embeddings = GoogleGenerativeAIEmbeddings(
        model=constants.EMBEDDING_MODEL,
        google_api_key=api_key,
        task_type="retrieval_document"
    )
    
    # インデックスをロード
    print("\nインデックスをロード中...")
    try:
        db = FAISS.load_local(
            str(static_index_path),
            embeddings,
            allow_dangerous_deserialization=True
        )
    except Exception as e:
        print(f"ロードエラー: {e}")
        return
    
    # docstoreの内容を調査
    print(f"\n=== インデックス内のドキュメント ===")
    docstore = db.docstore._dict
    print(f"総ドキュメント数: {len(docstore)}")
    
    # サンプルを表示 + 全体統計
    empty_count = 0
    star_only_count = 0
    type_counts = {}
    
    for i, (doc_id, doc) in enumerate(docstore.items()):
        content = doc.page_content
        metadata = doc.metadata
        doc_type = metadata.get('type', 'unknown')
        
        # タイプ別カウント
        type_counts[doc_type] = type_counts.get(doc_type, 0) + 1
        
        # カウント
        if not content.strip():
            empty_count += 1
        elif content.strip() == "*":
            star_only_count += 1
        
        # 最初の20個を表示
        if i < 20:
            clean_content = content.replace('\n', ' ')[:80]
            print(f"  [{i+1}] Type: {doc_type}, Source: {metadata.get('source', 'unknown')}")
            print(f"      Content ({len(content)} chars): {clean_content}...")
    
    print(f"\n=== 統計 ===")
    print(f"空のドキュメント: {empty_count}")
    print(f"「*」のみのドキュメント: {star_only_count}")
    print(f"\nタイプ別:")
    for t, c in sorted(type_counts.items()):
        print(f"  - {t}: {c}")
    
    # 「*」のみのドキュメントを詳細調査
    if star_only_count > 0:
        print(f"\n=== 「*」のみのドキュメントの詳細 ===")
        count = 0
        for doc_id, doc in docstore.items():
            if doc.page_content.strip() == "*":
                if count < 10:
                    print(f"  - Source: {doc.metadata.get('source')}, Type: {doc.metadata.get('type')}, Full: '{doc.page_content}'")
                count += 1
        print(f"  合計: {count}件")

if __name__ == "__main__":
    investigate_index()
