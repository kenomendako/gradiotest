# memory_archivist.py (v3: 感情記録・自動名寄せ・新ワークフロー対応 最終版)

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

import spacy
import networkx as nx
from langchain_community.vectorstores import FAISS
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_google_genai._common import GoogleGenerativeAIError
import google.genai as genai
from google.api_core import exceptions as google_exceptions

import config_manager
import constants
import utils

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Spacy Model Loading ---
try:
    nlp = spacy.load("ja_core_news_lg")
except OSError:
    logger.error("Japanese spaCy model 'ja_core_news_lg' not found.")
    sys.exit(1)

# --- LLM Helper Functions (Smart Retry) ---
def call_gemini_with_smart_retry(gemini_client: genai.Client, model_name: str, prompt: str, max_retries: int = 5) -> str | None:
    retry_count = 0
    while retry_count < max_retries:
        try:
            response = gemini_client.models.generate_content(
                model=f"models/{model_name}", contents=[prompt],
            )
            return response.text
        except google_exceptions.ResourceExhausted as e:
            retry_count += 1
            if retry_count >= max_retries:
                logger.error(f"API rate limit exceeded. Max retries ({max_retries}) reached. Aborting this call.")
                return None
            wait_time = 5 * (2 ** (retry_count - 1))
            logger.warning(f"Rate limit hit. Retrying in {wait_time} seconds... ({retry_count}/{max_retries})")
            time.sleep(wait_time)
        except Exception as e:
            logger.error(f"An unexpected API error occurred: {e}", exc_info=True)
            return None
    return None

# --- New Core Functions for v3 ---
def generate_episodic_summary(gemini_client: genai.Client, pair_content: str) -> str | None:
    prompt = f"""
あなたは、対話ログを要約する専門家です。以下の対話の要点を、客観的な事実に基づき、簡潔な箇条書きで3〜5点にまとめてください。
【対話ログ】
---
{pair_content}
---
【要約】
"""
    response_text = call_gemini_with_smart_retry(gemini_client, constants.INTERNAL_PROCESSING_MODEL, prompt)
    return response_text.strip() if response_text else None

def extract_rich_relations_from_chunk(gemini_client: genai.Client, chunk: str) -> list | None:
    prompt = f"""
あなたは、対話の中から人間関係や出来事の機微を読み解く、高度なナラティブ分析AIです。
【コンテキストとなる会話】
---
{chunk}
---
【あなたのタスク】
上記の会話に登場する主要なエンティティ（人物、場所、組織、概念など）を特定し、それらの間に存在する、最も重要で意味のある関係性を、以下のJSON形式のリストとして、可能な限り多く抽出してください。

[
  {{
    "subject": "（主語となるエンティティ）",
    "relation": "（関係性を表す簡潔な動詞句。例: 'develops with', 'is concerned about'）",
    "object": "（目的語となるエンティティ）",
    "polarity": "（その関係性が持つ感情の極性: "positive", "negative", "neutral" のいずれか）",
    "intensity": "（感情の強度を1から10の整数で評価）",
    "context": "（その関係性が生まれた、あるいは示された状況の、50字程度の簡潔な要約）"
  }}
]

【最重要ルール】
- あなた自身の思考や挨拶は絶対に含めず、JSON配列のみを出力してください。
- 抽出する関係性がない場合は、空の配列 `[]` を出力してください。
- 全てのフィールドを必ず埋めてください。
"""
    response_text = call_gemini_with_smart_retry(gemini_client, constants.INTERNAL_PROCESSING_MODEL, prompt)
    if response_text is None: return None
    try:
        json_text = response_text.strip().removeprefix("```json").removesuffix("```").strip()
        data = json.loads(json_text)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, KeyError) as e:
        logger.error(f"Failed to parse JSON response from Gemini: {e}\nResponse was: {response_text}")
        return None

def normalize_entities_with_ai(gemini_client: genai.Client, entities: list) -> dict:
    if not entities: return {}
    # 辞書順でソートすることで、同じ入力に対して常に同じ出力を期待できるようにする
    sorted_entities = sorted(list(set(entities)))

    prompt = f"""
以下のエンティティのリストを分析し、意味的に重複しているものを一つにまとめてください。
出力は、正規化された日本語名をキーとし、元の名前のリストを値とするJSONオブジェクトにしてください。
英語は、可能であれば最も一般的で自然な日本語に翻訳してください。

入力リスト:
{json.dumps(sorted_entities, ensure_ascii=False)}

出力JSON:
"""
    response_text = call_gemini_with_smart_retry(gemini_client, constants.INTERNAL_PROCESSING_MODEL, prompt)
    if not response_text: return {e: [e] for e in sorted_entities} # フォールバック
    try:
        json_text = response_text.strip().removeprefix("```json").removesuffix("```").strip()
        data = json.loads(json_text)
        return data if isinstance(data, dict) else {e: [e] for e in sorted_entities}
    except json.JSONDecodeError:
        logger.warning("Failed to parse normalization JSON, falling back to original entities.")
        return {e: [e] for e in sorted_entities}

# --- Helper Functions (File I/O, etc.) ---
def load_graph(path: Path) -> nx.DiGraph:
    return nx.read_graphml(str(path)) if path.exists() else nx.DiGraph()

def save_graph(G: nx.DiGraph, path: Path):
    nx.write_graphml(G, str(path))

def save_progress(progress_file: Path, progress_data: dict):
    temp_path = progress_file.with_suffix(f"{progress_file.suffix}.tmp")
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(progress_data, f, indent=4, ensure_ascii=False)
        shutil.move(str(temp_path), str(progress_file))
    except Exception as e:
        logger.error(f"CRITICAL: Failed to save progress to {progress_file}. Error: {e}", exc_info=True)

def extract_entities(text: str) -> list:
    doc = nlp(text)
    entities = set()
    particles = {"って", "は", "が", "の", "に", "を", "と", "へ", "で"}
    for ent in doc.ents:
        if ent.label_ in ["PERSON", "ORG", "GPE", "LOC"]:
            clean_text = ent.text.strip()
            if len(clean_text) > 1 and clean_text[-1] in particles:
                clean_text = clean_text[:-1]
            if clean_text: entities.add(clean_text)
    for token in doc:
        if token.pos_ in ["NOUN", "PROPN"] and len(token.text) > 1:
            entities.add(token.text.strip())
    return sorted(list(entities))

def extract_conversation_pairs(log_messages: list) -> list:
    if not log_messages: return []
    pairs = []
    i = 0
    while i < len(log_messages):
        if log_messages[i].get("role") == "USER":
            user_message = log_messages[i]
            if i + 1 < len(log_messages) and log_messages[i+1].get("role") == "AGENT":
                agent_message = log_messages[i+1]
                pairs.append({"user": user_message, "agent": agent_message})
                i += 2
            else:
                i += 1
        else:
            i += 1
    return pairs

# --- Main Execution Logic ---
def main():
    parser = argparse.ArgumentParser(description="Nexus Ark Memory Archivist v3")
    parser.add_argument("--source", type=str, required=True, choices=["import", "active_log"], help="Source of the logs.")
    parser.add_argument("--room_name", type=str, required=True, help="The name of the room.")
    args = parser.parse_args()

    logger.info(f"--- Memory Archivist Started for Room: {args.room_name}, Source: {args.source} ---")

    # --- APIキーとクライアントの初期化 (プロジェクト規約遵守) ---
    config_manager.load_config()
    try:
        selected_key_name = config_manager.initial_api_key_name_global
        api_key = config_manager.GEMINI_API_KEYS.get(selected_key_name)

        if not api_key or api_key.startswith("YOUR_API_KEY"):
            logger.error(f"FATAL: The selected API key '{selected_key_name}' is invalid or a placeholder.")
            sys.exit(1)

        # 規約1: genai.Clientをインスタンス化する
        gemini_client = genai.Client(api_key=api_key)
        # 規約2: LangChain用のEmbeddingクライアントも、キーを渡して個別に初期化する
        embeddings = GoogleGenerativeAIEmbeddings(model="gemini-embedding-001", google_api_key=api_key)

        logger.info(f"Gemini clients initialized successfully for key '{selected_key_name}'.")
    except Exception as e:
        logger.error(f"Failed to initialize Gemini client or embeddings: {e}", exc_info=True)
        sys.exit(1)

    # --- Path and Progress Setup ---
    room_path = Path(constants.ROOMS_DIR) / args.room_name
    rag_data_path = room_path / "rag_data"

    # --- Workflow Branching ---
    if args.source == "import":
        source_dir = room_path / "log_import_source"
        progress_file = rag_data_path / "import_progress.json"
    else: # active_log
        source_dir = room_path # log.txt is in the root
        progress_file = rag_data_path / "active_log_progress.json"

    processed_dir = source_dir / "processed" # For import source only

    rag_data_path.mkdir(parents=True, exist_ok=True)
    progress_data = {}
    if progress_file.exists():
        try:
            with open(progress_file, "r", encoding="utf-8") as f:
                progress_data = json.load(f)
        except (json.JSONDecodeError, IOError):
            logger.warning(f"Could not read progress file {progress_file}. Starting from scratch.")
            progress_data = {}

    try:
        # --- Determine files to process ---
        files_to_process = []
        if args.source == "import":
            source_dir.mkdir(parents=True, exist_ok=True)
            processed_dir.mkdir(parents=True, exist_ok=True)
            all_logs = sorted([f for f in source_dir.glob("*.txt") if f.is_file()])
            files_to_process = [f for f in all_logs if progress_data.get(f.name, {}).get("status") != "completed"]
        else: # active_log
            log_file = source_dir / "log.txt"
            if log_file.exists(): files_to_process.append(log_file)

        if not files_to_process:
            logger.info("No new log files to process.")
            return

        # --- Main Loop ---
        for log_file in files_to_process:
            try:
                logger.info(f"--- Processing log file: {log_file.name} ---")
                log_messages = utils.load_chat_log(str(log_file))
                conversation_pairs = extract_conversation_pairs(log_messages)
                if not conversation_pairs:
                    logger.info(f"No conversation pairs found in {log_file.name}. Skipping.")
                    progress_data[log_file.name] = {"status": "completed"}
                    if args.source == "import":
                        shutil.move(str(log_file), str(processed_dir / log_file.name))
                    continue

                # --- Determine start index based on source ---
                if args.source == "import":
                    file_progress = progress_data.get(log_file.name, {})
                    start_pair_index = file_progress.get("last_processed_pair_index", -1) + 1
                else: # active_log
                    last_id = progress_data.get("last_processed_id", None)
                    if last_id is None:
                        start_pair_index = 0
                    else:
                        # Find the index of the message after the last processed one
                        start_pair_index = next((i + 1 for i, msg in enumerate(log_messages) if msg.get("id") == last_id), len(log_messages))

                # --- Resource Initialization ---
                episodic_path = rag_data_path / "episodic_memory.json"
                vector_store_path = rag_data_path / "faiss_index"
                graph_path = rag_data_path / "knowledge_graph.graphml"

                episodic_memory = []
                if episodic_path.exists():
                    with open(episodic_path, "r", encoding="utf-8") as f:
                        episodic_memory = json.load(f)

                db = FAISS.load_local(str(vector_store_path), embeddings, allow_dangerous_deserialization=True) if vector_store_path.exists() else None
                G = load_graph(graph_path)

                # --- Pair Processing Loop ---
                for i, pair in enumerate(conversation_pairs[start_pair_index:], start=start_pair_index):
                    user_content = pair["user"]["content"]
                    agent_content = pair["agent"]["content"]
                    combined_content = f"User: {user_content}\nAgent: {agent_content}"
                    pair_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, combined_content))

                    file_progress = progress_data.get(log_file.name, {"last_processed_pair_index": -1, "last_completed_stage": 0})
                    start_stage = file_progress.get("last_completed_stage", 0)

                    # --- Stage 1: Episodic Memory ---
                    if start_stage < 1:
                        logger.info(f"  - Pair {i+1}/{len(conversation_pairs)}, Stage 1: Creating episodic memory...")
                        summary = generate_episodic_summary(gemini_client, combined_content)
                        if summary:
                            episodic_memory.append({
                                "id": pair_id,
                                "timestamp": pair["user"].get("timestamp", datetime.now().isoformat()),
                                "summary": summary,
                                "user_content": user_content,
                                "agent_content": agent_content
                            })
                            with open(episodic_path, "w", encoding="utf-8") as f:
                                json.dump(episodic_memory, f, indent=2, ensure_ascii=False)
                        file_progress.update({"last_completed_stage": 1})
                        save_progress(progress_file, progress_data)
                        logger.info(f"    - Stage 1 completed.")

                    # --- Stage 2: Semantic Memory (v3 SUPER-EVOLUTION) ---
                    if start_stage < 2:
                        logger.info(f"  - Pair {i+1}/{len(conversation_pairs)}, Stage 2: Deepening semantic memory...")

                        all_relations = extract_rich_relations_from_chunk(gemini_client, combined_content)
                        if all_relations is None: raise RuntimeError("Failed to extract relations after max retries.")

                        if all_relations:
                            # Extract all unique entities from the relations found by the AI
                            unique_entities = set()
                            for rel in all_relations:
                                if rel.get("subject"): unique_entities.add(rel.get("subject"))
                                if rel.get("object"): unique_entities.add(rel.get("object"))

                            # Normalize these entities using AI
                            normalization_map = normalize_entities_with_ai(gemini_client, list(unique_entities))
                            reverse_alias_map = {alias: canonical for canonical, aliases in normalization_map.items() for alias in aliases}

                            for rel in all_relations:
                                subj = rel.get("subject")
                                obj = rel.get("object")
                                pred = rel.get("relation")

                                if not all([subj, obj, pred]): continue

                                # Normalize subject and object
                                norm_subj = reverse_alias_map.get(subj, subj)
                                norm_obj = reverse_alias_map.get(obj, obj)

                                if not G.has_node(norm_subj): G.add_node(norm_subj)
                                if not G.has_node(norm_obj): G.add_node(norm_obj)

                                if not G.has_edge(norm_subj, norm_obj):
                                    G.add_edge(
                                        norm_subj, norm_obj,
                                        label=pred,
                                        polarity=rel.get("polarity", "neutral"),
                                        intensity=rel.get("intensity", 5),
                                        context=rel.get("context", "")
                                    )
                                    logger.info(f"      - Found relation: {norm_subj} -> {pred} -> {norm_obj}")

                            save_graph(G, graph_path)
                        else:
                            logger.info("    - No significant relations found in this pair.")

                        file_progress.update({"last_completed_stage": 2})
                        if args.source == "import":
                            file_progress["last_processed_pair_index"] = i
                            progress_data[log_file.name] = file_progress
                        save_progress(progress_file, progress_data)
                        logger.info(f"    - Stage 2 completed.")

                    # --- Stage 3: RAG Indexing ---
                    if start_stage < 3:
                        logger.info(f"  - Pair {i+1}/{len(conversation_pairs)}, Stage 3: Indexing for RAG...")
                        metadata = {
                            "source": log_file.name,
                            "pair_id": pair_id,
                            "timestamp": pair["user"].get("timestamp", datetime.now().isoformat())
                        }
                        if db is None:
                            db = FAISS.from_texts([combined_content], embeddings, metadatas=[metadata])
                        else:
                            db.add_texts([combined_content], metadatas=[metadata])

                        db.save_local(str(vector_store_path))

                        file_progress.update({"last_completed_stage": 3})
                        if args.source == "import":
                            file_progress["last_processed_pair_index"] = i
                            progress_data[log_file.name] = file_progress
                        save_progress(progress_file, progress_data)
                        logger.info(f"    - Stage 3 completed.")

                # --- Post-loop logic ---
                if args.source == "import":
                    logger.info(f"--- Successfully completed all pairs for {log_file.name} ---")
                    progress_data[log_file.name] = {"status": "completed"}
                    shutil.move(str(log_file), str(processed_dir / log_file.name))
                else: # active_log
                    if log_messages:
                        last_message_id = log_messages[-1].get("id")
                        progress_data["last_processed_id"] = last_message_id
                        logger.info(f"--- Active log processing complete. Last processed ID: {last_message_id} ---")

            except Exception as e:
                logger.error(f"Processing of file {log_file.name} was interrupted. Saving progress.", exc_info=True)
                break

    finally:
        logger.info("Saving final progress...")
        save_progress(progress_file, progress_data)

if __name__ == "__main__":
    main()
