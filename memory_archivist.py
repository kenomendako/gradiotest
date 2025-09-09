import argparse
import os
import sys
import uuid
import json
import shutil
import tempfile
from datetime import datetime
import logging
import time
from pathlib import Path
from itertools import combinations

import spacy
import networkx as nx
import traceback
from langchain_community.vectorstores import FAISS
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
import google.genai as genai
from google.api_core import exceptions as google_exceptions

import config_manager
import constants
import utils
import room_manager

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Spacy Model Loading ---
try:
    nlp = spacy.load("ja_core_news_lg")
except OSError:
    logger.error("Japanese spaCy model 'ja_core_news_lg' not found.")
    logger.error("Please run 'python -m spacy download ja_core_news_lg' to install it.")
    sys.exit(1)

# --- LLM and Helper Functions ---
def _call_gemini_with_retry(gemini_client: genai.Client, model_name: str, prompt: str) -> str:
    """
    Calls the API, catching ResourceExhausted errors to return a special value.
    """
    try:
        response = gemini_client.models.generate_content(
            model=f"models/{model_name}",
            contents=[prompt],
        )
        return response.text
    except google_exceptions.ResourceExhausted as e:
        logger.warning(f"API rate limit exceeded during call. SDK's internal retry failed. Details: {e}")
        return "RATE_LIMIT_EXCEEDED"
    except Exception as e:
        logger.error(f"An unexpected API error occurred: {e}")
        return "API_ERROR"

def summarize_chunk(gemini_client: genai.Client, chunk: str) -> str:
    """Summarizes a text chunk using the provided Gemini client."""
    prompt = f"""
あなたは、対話ログを要約する専門家です。以下の対話の要点を、客観的な事実に基づき、簡潔な箇条書きで3〜5点にまとめてください。
【対話ログ】
---
{chunk}
---
【要約】
"""
    return _call_gemini_with_retry(gemini_client, constants.INTERNAL_PROCESSING_MODEL, prompt)

def get_rich_relation_from_gemini(gemini_client: genai.Client, chunk: str, entity1: str, entity2: str) -> dict | str | None:
    """
    Gets a rich relationship. Returns dict on success, str on rate limit/API error, None on other errors.
    """
    prompt = f"""
あなたは、対話の中から人間関係や出来事の機微を読み解く、高度なナラティブ分析AIです。
【コンテキストとなる会話】
---
{chunk}
---
【あなたのタスク】
上記の会話において、「{entity1}」と「{entity2}」の間に存在する最も重要な関係性を分析し、以下のJSON形式で厳密に出力してください。
{{
  "relation": "（関係性を表す簡潔な動詞句。例: 'shares tea with', 'worries about', 'is located in'）",
  "polarity": "（その関係性が持つ感情の極性: "positive", "negative", "neutral" のいずれか）",
  "intensity": "（感情の強度を1から10の整数で評価）",
  "context": "（その関係性が生まれた、あるいは示された状況の、50字程度の簡潔な要約）"
}}
【最重要ルール】
- あなた自身の思考や挨拶は絶対に含めず、JSONオブジェクトのみを出力してください。
- 全てのフィールドを必ず埋めてください。
"""
    response_text = _call_gemini_with_retry(gemini_client, constants.INTERNAL_PROCESSING_MODEL, prompt)

    if response_text in ["RATE_LIMIT_EXCEEDED", "API_ERROR"]:
        return response_text

    try:
        json_text = response_text.strip().removeprefix("```json").removesuffix("```").strip()
        data = json.loads(json_text)
        if all(k in data for k in ["relation", "polarity", "intensity", "context"]):
            return data
        else:
            logger.warning(f"Parsed JSON is missing required keys for ({entity1}, {entity2}).")
            return None
    except (json.JSONDecodeError, KeyError) as e:
        logger.error(f"Failed to parse JSON response from Gemini for ({entity1}, {entity2}): {e}\nResponse was: {response_text}")
        return None

def load_graph(path: Path) -> nx.DiGraph:
    if path.exists():
        return nx.read_graphml(str(path))
    return nx.DiGraph()

def save_graph(G: nx.DiGraph, path: Path):
    nx.write_graphml(G, str(path))

def extract_entities(text: str) -> list:
    doc = nlp(text)
    entities = [ent.text.strip() for ent in doc.ents if ent.label_ in ["PERSON", "ORG", "GPE", "LOC"]]
    return sorted(list(set(entities)))

def main():
    parser = argparse.ArgumentParser(description="Nexus Ark Memory Archivist")
    parser.add_argument("--source", type=str, required=True, choices=["import", "archive"], help="Source of the logs to process.")
    parser.add_argument("--room_name", type=str, required=True, help="The name of the room to process.")
    args = parser.parse_args()

    logger.info(f"--- Memory Archivist Started for Room: {args.room_name}, Source: {args.source} ---")

    config_manager.load_config()
    api_key = config_manager.GEMINI_API_KEYS.get(config_manager.initial_api_key_name_global)

    if not api_key or api_key.startswith("YOUR_API_KEY"):
        logger.error("FATAL: The selected API key is invalid.")
        sys.exit(1)

    try:
        gemini_client = genai.Client(api_key=api_key)
        logger.info("Gemini API client created successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize Gemini client: {e}")
        sys.exit(1)

    room_path = Path(constants.ROOMS_DIR) / args.room_name
    rag_data_path = room_path / "rag_data"

    if args.source == "import":
        source_dir = room_path / "log_import_source"
        processed_dir = source_dir / "processed"
    else:
        source_dir = room_path / "log_archives"
        processed_dir = source_dir / "processed"

    rag_data_path.mkdir(exist_ok=True)
    source_dir.mkdir(exist_ok=True)
    processed_dir.mkdir(exist_ok=True)

    progress_file = rag_data_path / "archivist_progress.json"
    processed_files = set()
    if progress_file.exists():
        with open(progress_file, "r", encoding="utf-8") as f:
            try:
                progress_data = json.load(f)
                processed_files = set(progress_data.get("processed_files", []))
            except json.JSONDecodeError:
                logger.warning("Progress file is corrupted. Starting from scratch.")

    all_logs = [f for f in source_dir.glob("*.txt") if f.is_file()]
    files_to_process = sorted([f for f in all_logs if f.name not in processed_files])

    if not files_to_process:
        logger.info("All log files have already been processed.")
        if progress_file.exists():
            progress_file.unlink()
        return

    logger.info(f"Found {len(files_to_process)} log file(s) to process.")

    try:
        for log_file in files_to_process:
            try:
                logger.info(f"--- Processing log file: {log_file.name} ---")

                with open(log_file, "r", encoding="utf-8") as f:
                    log_content = f.read()

                if not log_content.strip():
                    logger.warning("Log file is empty, skipping.")
                    processed_files.add(log_file.name)
                    shutil.move(str(log_file), str(processed_dir / log_file.name))
                    continue

                text_splitter = RecursiveCharacterTextSplitter(chunk_size=8000, chunk_overlap=200, length_function=len)
                chunks = text_splitter.split_text(log_content)

                all_episode_summaries = []
                # Block 1: Episodic Memory
                logger.info("Block 1: Generating episodic memory...")
                short_term_path = rag_data_path / "memory_short_term_summary.txt"
                mid_term_path = rag_data_path / "memory_mid_term_summary.json"
                for i, chunk in enumerate(chunks):
                    summary = summarize_chunk(gemini_client, chunk)
                    if summary == "RATE_LIMIT_EXCEEDED":
                        raise RuntimeError("API rate limit exceeded during summarization.")
                    if not summary:
                        logger.warning(f"Skipping empty summary for chunk {i+1}.")
                        continue
                    episode_id = str(uuid.uuid4())
                    episode_data = {"episode_id": episode_id, "timestamp": datetime.now().isoformat(), "summary": summary, "source_log": log_file.name}
                    all_episode_summaries.append(episode_data)
                    with open(short_term_path, "a", encoding="utf-8") as f:
                        f.write(f"## Episode: {episode_id} (Generated: {episode_data['timestamp']})\n{summary}\n\n")
                    with open(mid_term_path, "a", encoding="utf-8") as f:
                        f.write(json.dumps(episode_data, ensure_ascii=False) + "\n")
                logger.info(f"  - Generated {len(all_episode_summaries)} episodic memories.")

                # Block 2: Semantic Memory
                logger.info("Block 2: Deepening semantic memory (Knowledge Graph)...")
                graph_path = rag_data_path / "knowledge_graph.graphml"
                G = load_graph(graph_path)
                for i, chunk in enumerate(chunks):
                    entities = extract_entities(chunk)
                    if len(entities) < 2: continue
                    for entity1, entity2 in combinations(entities, 2):
                        if G.has_edge(entity1, entity2): continue

                        max_retries = 3
                        retry_count = 0
                        relation_data = None
                        while retry_count < max_retries:
                            relation_data = get_rich_relation_from_gemini(gemini_client, chunk, entity1, entity2)
                            if isinstance(relation_data, str) and relation_data == "RATE_LIMIT_EXCEEDED":
                                retry_count += 1
                                wait_time = 5 * retry_count
                                logger.warning(f"Rate limit hit for relation extraction. Retrying in {wait_time}s... (Attempt {retry_count}/{max_retries})")
                                time.sleep(wait_time)
                            else:
                                break

                        if relation_data == "RATE_LIMIT_EXCEEDED":
                            raise RuntimeError("API rate limit exceeded after max retries during relation extraction.")

                        if isinstance(relation_data, dict):
                            logger.info(f"    - Found relation: {entity1} -> {relation_data['relation']} -> {entity2}")
                            G.add_edge(entity1, entity2, label=relation_data['relation'], **relation_data)

                save_graph(G, graph_path)
                logger.info(f"  - Knowledge graph updated with {G.number_of_edges()} relations.")

                # Block 3: RAG Indexing
                logger.info("Block 3: Indexing for RAG...")
                if all_episode_summaries:
                    faiss_index_path = rag_data_path / "episode_summary_index.faiss"
                    embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001", task_type="RETRIEVAL_DOCUMENT", google_api_key=api_key)
                    docs_to_index = [f"Episode ID: {item['episode_id']}\nTimestamp: {item['timestamp']}\nSummary:\n{item['summary']}" for item in all_episode_summaries]

                    if faiss_index_path.exists():
                        vector_store = FAISS.load_local(str(rag_data_path), embeddings, "episode_summary_index", allow_dangerous_deserialization=True)
                        vector_store.add_texts(docs_to_index)
                    else:
                        vector_store = FAISS.from_texts(docs_to_index, embeddings)

                    with tempfile.TemporaryDirectory() as temp_dir:
                        temp_path_str = str(Path(temp_dir) / "temp_index")
                        vector_store.save_local(temp_path_str)
                        shutil.move(f"{temp_path_str}/index.faiss", str(rag_data_path / "episode_summary_index.faiss"))
                        shutil.move(f"{temp_path_str}/index.pkl", str(rag_data_path / "episode_summary_index.pkl"))
                    logger.info(f"  - FAISS index saved successfully.")
                else:
                    logger.info("  - No new summaries to index.")

                processed_files.add(log_file.name)
                shutil.move(str(log_file), str(processed_dir / log_file.name))
                logger.info(f"Successfully processed and moved {log_file.name}")

            except Exception as e:
                logger.error(f"!!! FAILED to process {log_file.name}: {e}", exc_info=True)
                sys.exit(1)

        logger.info("--- All tasks completed successfully ---")
        if progress_file.exists():
            progress_file.unlink()

    finally:
        logger.info("Saving final progress...")
        with open(progress_file, "w", encoding="utf-8") as f:
            json.dump({"processed_files": list(processed_files)}, f, indent=2)

if __name__ == "__main__":
    main()
