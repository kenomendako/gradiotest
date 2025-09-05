import os
import sys
import json
import argparse
import time
import re
import signal
from typing import List, Dict, Tuple
import logging
from pathlib import Path
import traceback

import spacy
import networkx as nx
import google.genai as genai
from google.api_core.exceptions import ResourceExhausted

# Constantsをインポート
try:
    import constants
except ImportError:
    print("Error: constants.py not found. Please ensure it's in the same directory.")
    sys.exit(1)

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Graceful Shutdown ---
shutdown_flag = False
def signal_handler(signum, frame):
    global shutdown_flag
    logger.warning(f"Shutdown signal {signum} received. Finishing current task and saving progress...")
    shutdown_flag = True

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# --- spaCy Model Loading ---
try:
    nlp = spacy.load("ja_core_news_lg")
    logger.info("spaCy Japanese model 'ja_core_news_lg' loaded successfully.")
except OSError:
    logger.error("spaCy model 'ja_core_news_lg' not found.")
    logger.error("Please run 'python -m spacy download ja_core_news_lg' to download it.")
    sys.exit(1)


def chunk_log(log_content: str) -> List[str]:
    """
    Splits a log file into meaningful conversation chunks.
    """
    lines = log_content.strip().split('\n')
    chunks = []
    current_chunk = ""
    last_role = None

    user_pattern = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} - USER: ")
    assistant_pattern = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} - ASSISTANT: ")

    for line in lines:
        is_user = user_pattern.match(line)
        is_assistant = assistant_pattern.match(line)

        current_role = "user" if is_user else "assistant" if is_assistant else last_role

        if current_role != last_role and last_role == "assistant":
            chunks.append(current_chunk.strip())
            current_chunk = ""

        if is_user or is_assistant:
             current_chunk += line.split(" - ", 2)[-1] + "\n"
        else:
             current_chunk += line + "\n"

        last_role = current_role

    if current_chunk:
        chunks.append(current_chunk.strip())

    logger.info(f"Log content chunked into {len(chunks)} parts.")
    return chunks

# ---------------------------------
# ▼▼▼【ここからが修正箇所】▼▼▼
# ---------------------------------

# 引数から、間違った型ヒントと、不要な`gemini_model`を削除します。
# 代わりに、作法の基本となる`client`オブジェクトを受け取ります。
def get_relation_from_gemini(client: 'genai.client.Client', chunk: str, entity1: str, entity2: str) -> str:
    """
    Gemini APIを呼び出して、2つのエンティティ間の関係性を推論する。
    """
    # プロジェクト規約で定められた、中央管理のモデル名を`constants`から取得します。
    model_name = constants.INTERNAL_PROCESSING_MODEL

    prompt = f"""
    あなたは、二つのエンティティ間の関係性を定義する、高精度の言語分析AIです。

    【コンテキストとなる会話】
    ---
    {chunk}
    ---

    【あなたのタスク】
    上記の会話において、「{entity1}」と「{entity2}」の間に存在する最も的確な関係性を、以下の選択肢から一つだけ選び、その単語のみを返答してください。

    【関係性の選択肢】
    IS_IN (〜にいる), GOES_TO (〜へ行く), TALKS_ABOUT (〜について話す), LIKES (〜を好む), DISLIKES (〜を嫌う), HAS (〜を持つ)

    【最重要ルール】
    - あなたの思考や挨拶は不要です。選択肢の中から最も適切な単語、ただ一つだけを出力してください。
    - どの選択肢も当てはまらない場合は、`UNKNOWN`とだけ出力してください。
    """

    try:
        # 唯一の正しい作法: client.models.generate_content(...) を使用します。
        response = client.models.generate_content(
            model=f"models/{model_name}",
            contents=[prompt]
        )
        relation = response.text.strip()
        # 念のため、応答が選択肢のいずれかであるかを確認します
        valid_relations = ["IS_IN", "GOES_TO", "TALKS_ABOUT", "LIKES", "DISLIKES", "HAS", "UNKNOWN"]
        return relation if relation in valid_relations else "UNKNOWN"
    except Exception as e:
        # スマートリトライ機構は、この関数の呼び出し元で実装するため、
        # ここではエラーが発生したことを示す文字列を返します。
        logging.error(f"Gemini API call failed for entities ('{entity1}', '{entity2}'): {e}")
        # リトライを促すための特別なキーワードを返す
        return "API_ERROR_RETRY"

# ---------------------------------
# ▲▲▲【修正はここまで】▲▲▲
# ---------------------------------

def main(room_name: str, api_key: str):
    G = nx.Graph()
    progress = {}
    rag_data_path = Path("characters") / room_name / "rag_data"
    graph_path = rag_data_path / "knowledge_graph.graphml"
    progress_file = rag_data_path / "importer_progress.json"

    try:
        # --- Setup ---
        try:
            gemini_client = genai.Client(api_key=api_key)
            logger.info(f"Gemini API client created successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize Gemini client: {e}")
            sys.exit(1)

        log_source_path = Path("characters") / room_name / "log_import_source"
        log_source_path.mkdir(parents=True, exist_ok=True)
        rag_data_path.mkdir(parents=True, exist_ok=True)

        if progress_file.exists():
            with open(progress_file, 'r', encoding='utf-8') as f: progress = json.load(f)
            logger.info("Loaded progress.")
        if graph_path.exists():
            G = nx.read_graphml(graph_path)
            logger.info("Loaded existing knowledge graph.")

        # --- Entity & Initial Edge Extraction ---
        log_files = [f for f in log_source_path.glob("*.txt")]
        logger.info(f"Found {len(log_files)} log files.")
        for log_file_path in log_files:
            if shutdown_flag: break
            log_filename = log_file_path.name
            if progress.get(log_filename, {}).get('status') == 'chunking_completed':
                logger.info(f"Skipping entity extraction for already processed file: {log_filename}")
                continue

            logger.info(f"Processing file for entities: {log_filename}")
            with open(log_file_path, 'r', encoding='utf-8') as f: content = f.read()
            chunks = chunk_log(content)
            start_chunk = progress.get(log_filename, {}).get('last_processed_chunk', -1) + 1

            for i, chunk in enumerate(chunks[start_chunk:], start=start_chunk):
                if shutdown_flag: break
                logger.info(f"Processing chunk {i+1}/{len(chunks)} of {log_filename}")
                doc = nlp(chunk)
                entities = list(set([ent.text for ent in doc.ents if ent.label_ in ["PERSON", "ORG", "GPE", "FAC", "LOC"]]))
                if len(entities) >= 2:
                    for entity in entities:
                        if not G.has_node(entity): G.add_node(entity)
                    for j in range(len(entities)):
                        for k in range(j + 1, len(entities)):
                            if not G.has_edge(entities[j], entities[k]):
                                G.add_edge(entities[j], entities[k], relation="related_to")
                progress[log_filename] = {'last_processed_chunk': i}

            if not shutdown_flag:
                progress[log_filename]['status'] = 'chunking_completed'

        # --- Relationship Enrichment ---
        logger.info("Starting relationship enrichment with Gemini API...")
        edges_to_process = [(u, v) for u, v, d in G.edges(data=True) if d.get('relation') == 'related_to']
        processed_edges = set(map(tuple, progress.get("processed_edges", [])))

        for i, (u, v) in enumerate(edges_to_process):
            if shutdown_flag: break
            edge_tuple = tuple(sorted((u, v)))
            if edge_tuple in processed_edges: continue

            origin_chunk = ""
            for log_file_path in log_files:
                if shutdown_flag: break
                with open(log_file_path, 'r', encoding='utf-8') as f: content = f.read()
                chunks = chunk_log(content)
                for chunk in chunks:
                    if u in chunk and v in chunk:
                        origin_chunk = chunk; break
                if origin_chunk: break

            if not origin_chunk: continue

            logger.info(f"Analyzing relation for ({u}, {v}) - {i+1}/{len(edges_to_process)}")

            # Smart retry loop
            retry_count = 0
            max_retries = 5
            while retry_count < max_retries and not shutdown_flag:
                relation = get_relation_from_gemini(gemini_client, origin_chunk, u, v)
                if relation != "API_ERROR_RETRY":
                    break
                retry_count += 1
                wait_time = 5 * (2 ** (retry_count - 1)) # Exponential backoff
                logger.warning(f"API error detected. Retrying in {wait_time} seconds... (Attempt {retry_count}/{max_retries})")
                time.sleep(wait_time)

            if relation == "API_ERROR_RETRY":
                logger.error(f"Failed to get relation for ({u}, {v}) after {max_retries} retries. Skipping.")
                continue

            if relation != "UNKNOWN" and relation in ["IS_IN", "GOES_TO", "TALKS_ABOUT", "LIKES", "DISLIKES", "HAS"]:
                G[u][v]['relation'] = relation
                logger.info(f"Updated relation for ({u}, {v}) to '{relation}'")

            processed_edges.add(edge_tuple)

    finally:
        # --- Save Progress and Graph ---
        logger.info("Saving final progress and knowledge graph...")
        progress["processed_edges"] = [list(e) for e in processed_edges]
        with open(progress_file, 'w', encoding='utf-8') as f:
            json.dump(progress, f, indent=2, ensure_ascii=False)
        nx.write_graphml(G, graph_path)
        logger.info(f"Knowledge graph saved to {graph_path}")
        if shutdown_flag:
            logger.warning("Importer stopped due to shutdown signal.")
        else:
            logger.info("All tasks completed successfully.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build a knowledge graph from conversation logs.")
    parser.add_argument("room_name", type=str, help="The name of the room to process.")
    args = parser.parse_args()

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        try:
            with open('config.json', 'r') as f:
                config = json.load(f)
                api_key = next(iter(config['api_keys'].values()))
                logger.info("Loaded API key from config.json")
        except (FileNotFoundError, json.JSONDecodeError, KeyError, StopIteration):
            logger.error("Could not find a valid API key in config.json or GEMINI_API_KEY env var.")
            sys.exit(1)

    main(args.room_name, api_key)
