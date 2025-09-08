import argparse
import os
import sys
import uuid
import json
import shutil
import tempfile
from datetime import datetime

import spacy
import networkx as nx
import traceback
from langchain_faiss import FAISS
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
import google.genai as genai

import config_manager
import constants
import utils
import room_manager

# --- Spacy Model Loading ---
# Load a smaller, efficient model. This might need to be downloaded on first run.
# python -m spacy download en_core_web_sm
nlp = spacy.load("en_core_web_sm")

# --- LLM and Helper Functions ---

def get_llm(api_key: str):
    """Initializes and returns the Gemini client."""
    # Safety settings to block as little as possible.
    safety_settings = {
        "HARM_CATEGORY_HARASSMENT": "BLOCK_NONE",
        "HARM_CATEGORY_HATE_SPEECH": "BLOCK_NONE",
        "HARM_CATEGORY_SEXUALLY_EXPLICIT": "BLOCK_NONE",
        "HARM_CATEGORY_DANGEROUS_CONTENT": "BLOCK_NONE",
    }
    return genai.GenerativeModel(
        constants.INTERNAL_PROCESSING_MODEL,
        safety_settings=safety_settings
    )

def summarize_chunk(llm, chunk: str) -> str:
    """Summarizes a text chunk using the provided LLM."""
    prompt = f"""
あなたは、対話ログを要約する専門家です。以下の対話の要点を、客観的な事実に基づき、簡潔な箇条書きで3〜5点にまとめてください。

【対話ログ】
---
{chunk}
---

【要約】
"""
    try:
        response = llm.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        print(f"Error during summarization: {e}", file=sys.stderr)
        return "" # Return empty string on error

def load_graph(path: str) -> nx.DiGraph:
    """Loads a graph from a GraphML file, or returns a new graph if not found."""
    if os.path.exists(path):
        return nx.read_graphml(path)
    return nx.DiGraph()

def save_graph(G: nx.DiGraph, path: str):
    """Saves a graph to a GraphML file."""
    nx.write_graphml(G, path)

def extract_entities(text: str) -> list:
    """Extracts named entities (people, places, organizations) from text."""
    doc = nlp(text)
    # We are interested in specific entity types that are likely to be important.
    # PERSON, ORG, GPE (Geopolitical Entity), LOC (Location)
    entities = [
        ent.text.strip() for ent in doc.ents
        if ent.label_ in ["PERSON", "ORG", "GPE", "LOC"]
    ]
    # Remove duplicates and return
    return sorted(list(set(entities)))

def get_rich_relation_from_gemini(llm, chunk: str, entity1: str, entity2: str) -> dict:
    """
    Uses Gemini to extract a rich, structured relationship between two entities from a text chunk.
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
    try:
        response = llm.generate_content(prompt)
        # Clean up the response to extract only the JSON part
        json_text = response.text.strip()
        if json_text.startswith("```json"):
            json_text = json_text[7:]
        if json_text.endswith("```"):
            json_text = json_text[:-3]

        data = json.loads(json_text)
        # Basic validation
        if all(k in data for k in ["relation", "polarity", "intensity", "context"]):
            return data
    except (json.JSONDecodeError, AttributeError, Exception) as e:
        print(f"Error parsing relation from Gemini for ({entity1}, {entity2}): {e}", file=sys.stderr)
    return None

def main():
    parser = argparse.ArgumentParser(description="Nexus Ark Memory Archivist")
    parser.add_argument("--source", type=str, required=True, choices=["import", "archive"], help="Source of the logs to process.")
    parser.add_argument("--room_name", type=str, required=True, help="The name of the room to process.")
    args = parser.parse_args()

    print(f"--- Memory Archivist Started for Room: {args.room_name}, Source: {args.source} ---")

    # --- Setup ---
    config_manager.load_config()
    # For now, we'll use the globally configured API key. This could be enhanced later.
    api_key = config_manager.GEMINI_API_KEYS.get(config_manager.initial_api_key_name_global)
    if not api_key:
        print("ERROR: Could not find a valid Gemini API key in config.json.", file=sys.stderr)
        sys.exit(1)

    genai.configure(api_key=api_key)
    llm = get_llm(api_key)

    room_dir = os.path.join(constants.ROOMS_DIR, args.room_name)
    memory_dir = os.path.join(room_dir, "memory")
    os.makedirs(memory_dir, exist_ok=True)

    if args.source == "import":
        source_dir = os.path.join(room_dir, "log_import_source")
        processed_dir = os.path.join(room_dir, "log_import_source", "processed")
    else: # archive
        source_dir = os.path.join(room_dir, "log_archives")
        processed_dir = os.path.join(room_dir, "log_archives", "processed")

    os.makedirs(source_dir, exist_ok=True)
    os.makedirs(processed_dir, exist_ok=True)

    # --- File Processing Loop ---
    for filename in os.listdir(source_dir):
        if not filename.endswith(".txt"):
            continue

        log_file_path = os.path.join(source_dir, filename)
        if not os.path.isfile(log_file_path):
            continue

        print(f"\n--- Processing log file: {filename} ---")
        all_episode_summaries = []

        try:
            with open(log_file_path, "r", encoding="utf-8") as f:
                log_content = f.read()

            if not log_content.strip():
                print("Log file is empty, skipping.")
                shutil.move(log_file_path, os.path.join(processed_dir, filename))
                continue

            text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=8000,
                chunk_overlap=200,
                length_function=len,
            )
            chunks = text_splitter.split_text(log_content)

            # --- Block 1: Episodic Memory ---
            print("Block 1: Generating episodic memory...")

            short_term_summary_path = os.path.join(memory_dir, "memory_short_term_summary.txt")
            mid_term_summary_path = os.path.join(memory_dir, "memory_mid_term_summary.json")

            for i, chunk in enumerate(chunks):
                print(f"  - Summarizing chunk {i+1}/{len(chunks)}...")
                summary = summarize_chunk(llm, chunk)
                if not summary:
                    print("  - Skipping empty summary.")
                    continue

                episode_id = str(uuid.uuid4())
                timestamp = datetime.now().isoformat()

                # Append to short-term text file
                with open(short_term_summary_path, "a", encoding="utf-8") as f:
                    f.write(f"## Episode: {episode_id} (Generated: {timestamp})\n")
                    f.write(summary)
                    f.write("\n\n")

                # Append to mid-term JSON file
                episode_data = {
                    "episode_id": episode_id,
                    "timestamp": timestamp,
                    "summary": summary,
                    "source_log": filename
                }
                all_episode_summaries.append(episode_data)

                with open(mid_term_summary_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(episode_data, ensure_ascii=False) + "\n")

            print(f"  - Generated {len(all_episode_summaries)} episodic memories.")

            # --- Block 2: Semantic Memory ---
            print("Block 2: Deepening semantic memory (Knowledge Graph)...")
            graph_path = os.path.join(memory_dir, "knowledge_graph.graphml")
            G = load_graph(graph_path)

            for i, chunk in enumerate(chunks):
                print(f"  - Analyzing entities and relations in chunk {i+1}/{len(chunks)}...")
                entities = extract_entities(chunk)
                if len(entities) < 2:
                    continue

                # Create all combinations of entity pairs
                from itertools import combinations
                entity_pairs = list(combinations(entities, 2))

                for entity1, entity2 in entity_pairs:
                    # Avoid adding self-loops or duplicate relations in the same run
                    if G.has_edge(entity1, entity2):
                        continue

                    relation_data = get_rich_relation_from_gemini(llm, chunk, entity1, entity2)
                    if relation_data:
                        print(f"    - Found relation: {entity1} -> {relation_data['relation']} -> {entity2}")
                        G.add_edge(entity1, entity2, label=relation_data['relation'], **relation_data)

            save_graph(G, graph_path)
            print(f"  - Knowledge graph updated with {G.number_of_edges()} relations.")


            # --- Block 3: RAG Indexing ---
            print("Block 3: Indexing for RAG...")
            if all_episode_summaries:
                faiss_index_path = os.path.join(memory_dir, "episode_summary_index.faiss")
                embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001", task_type="RETRIEVAL_DOCUMENT")

                # Format summaries for embedding
                documents_to_index = [
                    f"Episode ID: {item['episode_id']}\nTimestamp: {item['timestamp']}\nSummary:\n{item['summary']}"
                    for item in all_episode_summaries
                ]

                if os.path.exists(faiss_index_path):
                    print("  - Loading existing FAISS index...")
                    vector_store = FAISS.load_local(faiss_index_path, embeddings, allow_dangerous_deserialization=True)
                    print("  - Adding new documents to index...")
                    vector_store.add_texts(documents_to_index)
                else:
                    print("  - Creating new FAISS index...")
                    vector_store = FAISS.from_texts(documents_to_index, embeddings)

                # Atomic save using tempfile and shutil.move
                try:
                    with tempfile.NamedTemporaryFile(delete=False, mode='w', dir=memory_dir) as temp_file:
                        temp_path = temp_file.name

                    vector_store.save_local(temp_path)
                    shutil.move(os.path.join(temp_path, "index.faiss"), faiss_index_path)
                    shutil.move(os.path.join(temp_path, "index.pkl"), os.path.join(memory_dir, "episode_summary_index.pkl"))
                    os.rmdir(temp_path) # Clean up the temporary directory created by save_local
                    print(f"  - FAISS index saved successfully to {faiss_index_path}")

                except Exception as e:
                    print(f"!!! Error during atomic save of FAISS index: {e}", file=sys.stderr)
                    # If saving fails, we should not mark the log as processed.
                    # Re-raise the exception to be caught by the main try...except block.
                    raise e
            else:
                print("  - No new summaries to index.")


            # Move the processed file to the processed directory
            shutil.move(log_file_path, os.path.join(processed_dir, filename))
            print(f"--- Successfully processed and moved {filename} ---")

        except Exception as e:
            print(f"!!! FAILED to process {filename}: {e}", file=sys.stderr)
            traceback.print_exc()
            # If any block fails, we do not move the file, so it can be re-processed.

    print("\n--- Memory Archivist Finished ---")


if __name__ == "__main__":
    main()
