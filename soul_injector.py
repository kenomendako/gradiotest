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

import networkx as nx
import google.genai as genai

# Constants and utilsをインポート
try:
    import constants
    import utils
except ImportError:
    print("Error: constants.py or utils.py not found. Please ensure they are in the same directory.")
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


def get_relation_from_gemini(client: 'genai.client.Client', chunk: str, entity1: str, entity2: str) -> str:
    """
    Gemini APIを呼び出して、2つのエンティティ間の関係性を推論する。
    """
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
        response = client.models.generate_content(
            model=f"models/{model_name}",
            contents=[prompt]
        )
        relation = response.text.strip()
        valid_relations = ["IS_IN", "GOES_TO", "TALKS_ABOUT", "LIKES", "DISLIKES", "HAS", "UNKNOWN"]
        return relation if relation in valid_relations else "UNKNOWN"
    except Exception as e:
        logging.error(f"Gemini API call failed for entities ('{entity1}', '{entity2}'): {e}")
        return "API_ERROR_RETRY"


def main(room_name: str, api_key: str):
    G = None
    tasks = []
    rag_data_path = Path("characters") / room_name / "rag_data"
    graph_path = rag_data_path / "knowledge_graph.graphml"
    analysis_file_path = rag_data_path / "pending_analysis.json"
    progress_file_path = rag_data_path / "injector_progress.json"

    try:
        # --- Setup and Load ---
        logger.info("--- Soul Injector Process Started ---")
        if not graph_path.exists() or not analysis_file_path.exists():
            logger.error("Skeleton graph or analysis file not found. Please run batch_importer.py first.")
            sys.exit(1)

        try:
            gemini_client = genai.Client(api_key=api_key)
            logger.info("Gemini API client created successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize Gemini client: {e}")
            sys.exit(1)

        G = nx.read_graphml(graph_path)
        with open(analysis_file_path, 'r', encoding='utf-8') as f:
            tasks = json.load(f)

        # Load progress
        progress = {}
        if progress_file_path.exists():
            with open(progress_file_path, 'r', encoding='utf-8') as f:
                progress = json.load(f)

        start_index = progress.get('last_processed_task_index', -1) + 1
        logger.info(f"Found {len(tasks)} tasks. Resuming from index {start_index}.")

        # --- Relationship Enrichment ---
        for i, task in enumerate(tasks[start_index:], start=start_index):
            if shutdown_flag: break

            u, v, chunk = task["entity1"], task["entity2"], task["chunk"]
            logger.info(f"Analyzing relation for ({u}, {v}) - Task {i+1}/{len(tasks)}")

            retry_count = 0
            max_retries = 5
            relation = "API_ERROR_RETRY"
            while retry_count < max_retries and not shutdown_flag:
                relation = get_relation_from_gemini(gemini_client, chunk, u, v)
                if relation != "API_ERROR_RETRY":
                    break
                retry_count += 1
                wait_time = 5 * (2 ** (retry_count - 1))
                logger.warning(f"API error. Retrying in {wait_time}s... (Attempt {retry_count}/{max_retries})")
                time.sleep(wait_time)

            if relation == "API_ERROR_RETRY":
                logger.error(f"Failed to get relation for ({u}, {v}) after {max_retries} retries. Skipping.")
                continue

            if relation != "UNKNOWN" and G.has_edge(u, v):
                G[u][v]['relation'] = relation
                logger.info(f"Updated relation for ({u}, {v}) to '{relation}'")

            progress['last_processed_task_index'] = i

        if not shutdown_flag:
            logger.info("All tasks completed. Cleaning up.")
            os.remove(analysis_file_path)
            os.remove(progress_file_path) # Also remove progress file on successful completion
            logger.info("Removed pending_analysis.json and injector_progress.json.")

    finally:
        # --- Save Progress and Graph ---
        if G is not None:
            logger.info("Saving final knowledge graph...")
            nx.write_graphml(G, graph_path)
            logger.info(f"Enriched knowledge graph saved to {graph_path}")

        if progress:
            with open(progress_file_path, 'w', encoding='utf-8') as f:
                json.dump(progress, f, indent=2, ensure_ascii=False)
            logger.info(f"Saved injector progress to {progress_file_path}")

        if shutdown_flag:
            logger.warning("Soul Injector stopped due to shutdown signal. Progress has been saved.")
        else:
            logger.info("--- Soul Injector Process Finished ---")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Nexus Ark Knowledge Graph Soul Injector")
    parser.add_argument("room_name", help="The name of the room to process.")
    args = parser.parse_args()

    # APIキーはconfig.jsonから読み込む
    api_key = None
    try:
        # config_managerはUIコンテキストで初期化されるため、直接config.jsonを読む
        with open('config.json', 'r') as f:
            config = json.load(f)
        # 最初のAPIキーを取得する
        api_key = next(iter(config['api_keys'].values()))
    except (FileNotFoundError, StopIteration, KeyError, json.JSONDecodeError) as e:
        logger.error(f"Could not load API key from config.json: {e}")
        sys.exit(1)

    main(args.room_name, api_key)
