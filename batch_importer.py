import os
import sys
import json
import argparse
import time
import re
from typing import List, Dict, Tuple
import logging
from pathlib import Path
import traceback

import spacy
import networkx as nx
import google.generativeai as genai
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

# --- spaCy Model Loading ---
try:
    nlp = spacy.load("ja_core_news_lg")
    logger.info("spaCy Japanese model 'ja_core_news_lg' loaded successfully.")
except OSError:
    logger.error("spaCy model 'ja_core_news_lg' not found.")
    logger.error("Please run 'python -m spacy download ja_core_news_lg' to download it.")
    sys.exit(1)

# --- Gemini API Configuration ---
try:
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    gemini_model = genai.GenerativeModel(constants.INTERNAL_PROCESSING_MODEL)
    logger.info(f"Gemini API configured with model: {constants.INTERNAL_PROCESSING_MODEL}")
except Exception as e:
    logger.error(f"Failed to configure Gemini API: {e}")
    sys.exit(1)

def chunk_log(log_content: str) -> List[str]:
    """
    Splits a log file into meaningful conversation chunks.
    A chunk is a sequence of user messages followed by a sequence of assistant messages.
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

        current_chunk += line.split(" - ", 2)[-1] + "\n"
        last_role = current_role

    if current_chunk:
        chunks.append(current_chunk.strip())

    logger.info(f"Log content chunked into {len(chunks)} parts.")
    return chunks

def get_relation_from_gemini(chunk: str, entity1: str, entity2: str) -> str:
    """
    Uses Gemini API to determine the relationship between two entities in a conversation chunk.
    """
    prompt_template = """
    あなたは、二つのエンティティ間の関係性を定義する、高精度の言語分析AIです。

    【コンテキストとなる会話】
    ---
    {conversation_chunk}
    ---

    【あなたのタスク】
    上記の会話において、「{entity1}」と「{entity2}」の間に存在する最も的確な関係性を、以下の選択肢から一つだけ選び、その単語のみを返答してください。

    【関係性の選択肢】
    IS_IN (〜にいる), GOES_TO (〜へ行く), TALKS_ABOUT (〜について話す), LIKES (〜を好む), DISLIKES (〜を嫌う), HAS (〜を持つ)

    【最重要ルール】
    - あなたの思考や挨拶は不要です。選択肢の中から最も適切な単語、ただ一つだけを出力してください。
    - どの選択肢も当てはまらない場合は、`UNKNOWN`とだけ出力してください。
    """
    prompt = prompt_template.format(conversation_chunk=chunk, entity1=entity1, entity2=entity2)

    while True:
        try:
            response = gemini_model.generate_content(prompt)
            relation = response.text.strip()
            logger.debug(f"Gemini response for ({entity1}, {entity2}): {relation}")
            return relation
        except ResourceExhausted as e:
            retry_delay = e.retry_delay if hasattr(e, 'retry_delay') else 30
            logger.warning(f"ResourceExhausted error. Retrying after {retry_delay} seconds...")
            time.sleep(retry_delay)
        except Exception as e:
            logger.error(f"An unexpected error occurred with Gemini API: {e}")
            return "UNKNOWN"

def main(room_name: str):
    base_path = Path("characters") / room_name
    log_source_path = base_path / "log_import_source"
    rag_data_path = base_path / "rag_data"
    progress_file = rag_data_path / "importer_progress.json"

    # Create directories if they don't exist
    log_source_path.mkdir(parents=True, exist_ok=True)
    rag_data_path.mkdir(parents=True, exist_ok=True)
    logger.info(f"Checked/created necessary directories for room: {room_name}")

    # Load progress
    progress = {}
    if progress_file.exists():
        with open(progress_file, 'r', encoding='utf-8') as f:
            progress = json.load(f)
        logger.info(f"Loaded progress from {progress_file}")

    # Initialize or load graph
    graph_path = rag_data_path / "knowledge_graph.graphml"
    if graph_path.exists():
        G = nx.read_graphml(graph_path)
        logger.info("Loaded existing knowledge graph.")
    else:
        G = nx.Graph()
        logger.info("Created a new knowledge graph.")

    log_files = [f for f in log_source_path.glob("*.txt")]
    logger.info(f"Found {len(log_files)} log files to process.")

    for log_file_path in log_files:
        log_filename = log_file_path.name
        if log_filename in progress and progress[log_filename].get('status') == 'completed':
            logger.info(f"Skipping already processed file: {log_filename}")
            continue

        logger.info(f"Processing file: {log_filename}")
        with open(log_file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        chunks = chunk_log(content)
        start_chunk = progress.get(log_filename, {}).get('last_processed_chunk', -1) + 1

        for i, chunk in enumerate(chunks[start_chunk:], start=start_chunk):
            try:
                logger.info(f"Processing chunk {i+1}/{len(chunks)} of {log_filename}")
                doc = nlp(chunk)
                entities = list(set([ent.text for ent in doc.ents]))

                if len(entities) < 2:
                    continue

                # Add nodes
                for entity in entities:
                    if not G.has_node(entity):
                        G.add_node(entity)
                        logger.debug(f"Added node: {entity}")

                # Add initial edges
                for j in range(len(entities)):
                    for k in range(j + 1, len(entities)):
                        u, v = entities[j], entities[k]
                        if not G.has_edge(u, v):
                            G.add_edge(u, v, relation="related_to")
                            logger.debug(f"Added edge: ({u}, {v})")

                # Update progress before API calls
                progress[log_filename] = {'last_processed_chunk': i, 'status': 'in_progress'}
                with open(progress_file, 'w', encoding='utf-8') as f:
                    json.dump(progress, f, indent=2)

            except Exception as e:
                logger.error(f"Error processing chunk {i} in {log_filename}: {e}\n{traceback.format_exc()}")

        progress[log_filename]['status'] = 'chunking_completed'
        logger.info(f"Finished entity extraction for {log_filename}.")

        # Save progress after chunking
        with open(progress_file, 'w', encoding='utf-8') as f:
            json.dump(progress, f, indent=2)

    # --- Step 3: Enrich relationships with Gemini ---
    logger.info("Starting relationship enrichment with Gemini API...")
    edges_to_process = [(u, v, d) for u, v, d in G.edges(data=True) if d.get('relation') == 'related_to']

    # This part is complex to make resumable. For now, we'll just process them.
    # A more robust implementation would track processed edges in the progress file.
    for i, (u, v, data) in enumerate(edges_to_process):
        # This is a simplification. We need to find the original chunk.
        # This requires a more complex data structure linking edges to chunks.
        # For this implementation, we will find *any* chunk with both entities.
        # This is a limitation but fulfills the core requirement.
        origin_chunk = ""
        for log_file_path in log_files:
            with open(log_file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            chunks = chunk_log(content)
            for chunk in chunks:
                if u in chunk and v in chunk:
                    origin_chunk = chunk
                    break
            if origin_chunk:
                break

        if not origin_chunk:
            logger.warning(f"Could not find origin chunk for edge ({u}, {v}). Skipping.")
            continue

        logger.info(f"Analyzing relation for ({u}, {v}) - {i+1}/{len(edges_to_process)}")
        relation = get_relation_from_gemini(origin_chunk, u, v)

        if relation != "UNKNOWN" and relation in ["IS_IN", "GOES_TO", "TALKS_ABOUT", "LIKES", "DISLIKES", "HAS"]:
            G[u][v]['relation'] = relation
            logger.info(f"Updated relation for ({u}, {v}) to '{relation}'")
        else:
            # We can either remove the edge or leave it as "related_to"
            # For now, let's leave it, but log the unknown relation.
            logger.warning(f"Could not determine a specific relation for ({u}, {v}). Kept as 'related_to'. Gemini response: {relation}")

        # Save graph periodically
        if i % 10 == 0:
            nx.write_graphml(G, graph_path)
            logger.info(f"Periodically saved graph to {graph_path}")


    # --- Step 5: Save the final knowledge graph ---
    nx.write_graphml(G, graph_path)
    logger.info(f"Successfully built and saved knowledge graph to {graph_path}")

    # Mark all as completed
    for log_file_path in log_files:
        progress[log_file_path.name] = {'status': 'completed'}
    with open(progress_file, 'w', encoding='utf-8') as f:
        json.dump(progress, f, indent=2)

    logger.info("All tasks completed.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build a knowledge graph from conversation logs.")
    parser.add_argument("room_name", type=str, help="The name of the room to process.")
    args = parser.parse_args()

    # A simple way to get API key if not in env.
    # In a real app, this would be more secure.
    if not os.getenv("GEMINI_API_KEY"):
        try:
            with open('config.json', 'r') as f:
                config = json.load(f)
                # Assuming the key is the first one in the dict
                api_key = next(iter(config['api_keys'].values()))
                os.environ['GEMINI_API_KEY'] = api_key
                logger.info("Loaded API key from config.json")
        except (FileNotFoundError, json.JSONDecodeError, KeyError, StopIteration):
            logger.error("Could not find a valid API key in config.json or GEMINI_API_KEY env var.")
            sys.exit(1)

    main(args.room_name)
