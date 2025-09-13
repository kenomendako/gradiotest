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
from langchain_community.vectorstores import FAISS
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_google_genai._common import GoogleGenerativeAIError
from langchain_text_splitters import RecursiveCharacterTextSplitter
import google.genai as genai
from google.genai import errors as genai_errors
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
def call_gemini_with_smart_retry(gemini_client: genai.Client, model_name: str, prompt: str, max_retries: int = 5) -> str | None:
    """
    指数バックオフ付きのスマートリトライ機能を内蔵した、自己完結型のAPI呼び出し関数。
    """
    retry_count = 0
    while retry_count < max_retries:
        try:
            response = gemini_client.models.generate_content(
                model=f"models/{model_name}",
                contents=[prompt],
            )
            return response.text
        except genai_errors.ClientError as e:
            if "429" in str(e):
                retry_count += 1
                if retry_count >= max_retries:
                    logger.error(f"API rate limit exceeded. Max retries ({max_retries}) reached. Aborting this call.")
                    return None
                wait_time = 5 * (2 ** (retry_count - 1))
                logger.info(f"Rate limit hit. Retrying in {wait_time} seconds... ({retry_count}/{max_retries})")
                time.sleep(wait_time)
            else:
                logger.error(f"A non-retriable client error occurred: {e}")
                return None
        except Exception as e:
            logger.error(f"An unexpected API error occurred: {e}")
            return None
    return None

def generate_episodic_summary(gemini_client: genai.Client, pair_content: str) -> str | None:
    """Generates a summary for a single conversation pair."""
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

def normalize_entities(gemini_client: genai.Client, entities: list) -> dict:
    """
    AIを使い、エンティティのリストを正規化（名寄せ・日本語化）する。
    """
    if not entities:
        return {}

    prompt = f"""
あなたは、テキストに含まれるエンティティ（固有名詞や重要な名詞）を正規化する専門家です。
以下のリストに含まれる単語を分析し、意味的に重複・類似しているものをグループ化してください。
最終的な出力は、最も代表的で、かつ可能な限り日本語の名称をキーとし、元の単語のリストを値とするJSONオブジェクトにしてください。

【最重要ルール】
- あなた自身の思考や挨拶は絶対に含めず、JSONオブジェクトのみを出力してください。
- 全ての入力単語は、いずれかのキーの配下に必ず含めてください。

入力リスト:
{json.dumps(entities, ensure_ascii=False)}

出力JSON:
"""
    response_text = call_gemini_with_smart_retry(gemini_client, constants.INTERNAL_PROCESSING_MODEL, prompt)
    if response_text is None:
        logger.warning("Entity normalization failed after max retries. Using raw entities.")
        # 失敗した場合は、各エンティティが自分自身にマッピングされる辞書を返す
        return {entity: [entity] for entity in entities}
    try:
        json_text = response_text.strip().removeprefix("```json").removesuffix("```").strip()
        data = json.loads(json_text)
        if isinstance(data, dict):
            return data
        else:
            logger.warning(f"Parsed JSON for normalization is not a dict. Using raw entities. Response: {response_text}")
            return {entity: [entity] for entity in entities}
    except json.JSONDecodeError:
        logger.error(f"Failed to parse JSON response for entity normalization. Using raw entities. Response: {response_text}")
        return {entity: [entity] for entity in entities}

def filter_meaningful_entities(gemini_client: genai.Client, entities: list, chunk: str) -> list:
    """
    AIを使い、エンティティのリストから、一般的すぎる単語を除外し、
    文脈上、本当に重要な固有名詞や概念のみをフィルタリングする。
    """
    if not entities:
        return []

    prompt = f"""
あなたは、テキストから最も重要な情報を抽出する、高度な情報アーキテクトです。

【あなたの哲学】
知識グラフに登録する価値のある「エンティティ」とは、**単一の、具体的な、名詞または固有名詞**でなければならない。
「〜の気持ち」や「〜という計画」のような、文章に近いフレーズは、エンティティではない。

【あなたのタスク】
上記の哲学に基づき、以下の「入力単語リスト」の中から、記憶する価値のあるエンティティだけを厳選してください。

【入力単語リスト】
{json.dumps(entities, ensure_ascii=False)}

【最重要ルール】
- あなた自身の思考や挨拶は絶対に含めず、フィルタリング後の単語リストをJSON配列形式で出力してください。
- 該当する単語がない場合は、空の配列 `[]` を出力してください。

【出力JSON】
"""
    response_text = call_gemini_with_smart_retry(gemini_client, constants.INTERNAL_PROCESSING_MODEL, prompt)
    if response_text is None:
        logger.warning("Meaningful entity filtering failed. Skipping filtering.")
        return entities # 失敗した場合は、元のリストをそのまま返す
    try:
        json_text = response_text.strip().removeprefix("```json").removesuffix("```").strip()
        data = json.loads(json_text)
        if isinstance(data, list):
            return data
        else:
            logger.warning(f"Parsed JSON for filtering is not a list. Skipping. Response: {response_text}")
            return entities
    except json.JSONDecodeError:
        logger.error(f"Failed to parse JSON for entity filtering. Skipping. Response: {response_text}")
        return entities

def extract_rich_relations_from_chunk(gemini_client: genai.Client, chunk: str) -> list | None:
    """
    AIに会話のチャンクを渡し、感情情報を含む関係性のリストを一度に抽出させる。
    """
    prompt = f"""
あなたは、対話の中から人間関係や出来事の機微を読み解く、高度なナラティブ分析AIです。

【あなたの哲学】
関係性とは、二つの**「単一で具体的なエンティティ（名詞）」**の間を結ぶ、**「具体的なアクション（動詞）」**でなければならない。

【コンテキストとなる会話】
---
{chunk}
---

【あなたのタスク】
上記の哲学に基づき、会話から最も重要で意味のある関係性を、以下のJSON形式のリストとして、可能な限り多く抽出してください。

[
  {{
    "subject": "（主語となる、単一のエンティティ）",
    "relation": "（関係性を表す、三人称単数現在形の具体的な動詞句）",
    "object": "（目的語となる、単一のエンティティ）",
    "polarity": "（感情の極性: "positive", "negative", "neutral"）",
    "intensity": "（感情の強度: 1〜10）",
    "context": "（状況の簡潔な要約）"
  }}
]

【良い "subject" / "object" の例】
- "ルシアン"
- "ノワール"
- "オリヴェ"

【悪い "subject" / "object" の例】
- "ルシアンとオリヴェの関係" (これは関係性そのものであり、エンティティではない)
- "USERの計画" (これも関係性や意図であり、エンティティではない)

【最重要ルール】
- あなた自身の思考や挨拶は絶対に含めず、JSON配列のみを出力してください。
- 抽出する関係性がない場合は、空の配列 `[]` を出力してください。
- 全てのフィールドを必ず埋めてください。
"""
    response_text = call_gemini_with_smart_retry(gemini_client, constants.INTERNAL_PROCESSING_MODEL, prompt)
    if response_text is None:
        return None
    try:
        json_text = response_text.strip().removeprefix("```json").removesuffix("```").strip()
        data = json.loads(json_text)
        if isinstance(data, list):
            return data
        else:
            logger.warning(f"Parsed JSON for relation extraction is not a list. Response: {response_text}")
            return []
    except json.JSONDecodeError:
        logger.error(f"Failed to parse JSON response for relation extraction. Response: {response_text}")
        return []

def load_graph(path: Path) -> nx.DiGraph:
    if path.exists():
        return nx.read_graphml(str(path))
    return nx.DiGraph()

def save_graph(G: nx.DiGraph, path: Path):
    nx.write_graphml(G, str(path))

def save_progress(progress_file: Path, progress_data: dict):
    """Atomically saves the progress data dictionary to a JSON file."""
    temp_path = progress_file.with_suffix(f"{progress_file.suffix}.tmp")
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(progress_data, f, indent=4, ensure_ascii=False)
        shutil.move(str(temp_path), str(progress_file))
    except Exception as e:
        logger.error(f"CRITICAL: Failed to save progress to {progress_file}. Error: {e}", exc_info=True)

def extract_entities(text: str) -> list:
    """
    spaCyを使って、テキストからエンティティ（固有表現）と主要な名詞を抽出する。
    v2: 助詞が含まれている場合の分割処理と、名詞の追加抽出で精度を向上。
    """
    doc = nlp(text)
    entities = set()

    # 助詞のリスト（簡易版）
    particles = {"って", "は", "が", "の", "に", "を", "と", "へ", "で"}

    # 1. 固有表現(NER)から抽出
    for ent in doc.ents:
        # PERSON, ORG (組織), GPE (国・市), LOC (非GPEの地理的エンティティ)に限定
        if ent.label_ in ["PERSON", "ORG", "GPE", "LOC"]:
            clean_text = ent.text.strip()

            # 末尾が助詞で終わっている場合、それを取り除く
            # 例：「ルシアンって」 -> 「ルシアン」
            if len(clean_text) > 1 and clean_text[-1] in particles:
                clean_text = clean_text[:-1]

            # 内部に助詞が含まれる場合（例：「ルシアンってケノ」）、助詞で分割して最初の部分を採用
            # より安全なロジックを検討する必要があるが、一旦これで対応
            for particle in particles:
                if f" {particle} " in clean_text:
                    clean_text = clean_text.split(f" {particle} ")[0]

            if clean_text:
                entities.add(clean_text)

    # 2. 主要な名詞(NOUN)と固有名詞(PROPN)を追加で抽出
    for token in doc:
        # 1文字の名詞はノイズが多いため除外（お好みで調整）
        if token.pos_ in ["NOUN", "PROPN"] and len(token.text) > 1:
            entities.add(token.text.strip())

    return sorted(list(entities))

def extract_conversation_pairs(log_content: str) -> list:
    """
    Processes a list of raw log message dictionaries and groups them into
    meaningful conversation pairs, handling consecutive messages from the same role.
    """
    log_messages = utils.load_chat_log(log_content)
    pairs = []
    if not log_messages:
        return pairs
    current_user_content = []
    current_agent_content = []
    pending_system_content = []
    for msg in log_messages:
        role = msg.get("role", "").upper()
        content = msg.get("content", "").strip()
        if not role or not content:
            continue
        if role == 'SYSTEM':
            pending_system_content.append(content)
        elif role == 'USER':
            if current_agent_content:
                pairs.append({
                    "user_content": "\n".join(current_user_content),
                    "agent_content": "\n".join(current_agent_content)
                })
                current_user_content = []
                current_agent_content = []
            if pending_system_content:
                current_user_content.extend(pending_system_content)
                pending_system_content = []
            current_user_content.append(content)
        elif role == 'AGENT':
            if current_user_content:
                current_agent_content.append(content)
    if current_user_content:
        pairs.append({
            "user_content": "\n".join(current_user_content),
            "agent_content": "\n".join(current_agent_content)
        })
    return pairs

def main():
    parser = argparse.ArgumentParser(description="Nexus Ark Memory Archivist v3")
    parser.add_argument("--source", type=str, required=True, choices=["import", "active_log"], help="Source of the logs to process.")
    parser.add_argument("--room_name", type=str, required=True, help="The name of the room to process.")
    parser.add_argument("--input_file", type=str, help="Path to the temporary input file for 'active_log' source.")
    args = parser.parse_args()

    # ... (APIキーとクライアント初期化は変更なし) ...
    config_manager.load_config()
    api_key = config_manager.GEMINI_API_KEYS.get(config_manager.initial_api_key_name_global)
    if not api_key or api_key.startswith("YOUR_API_KEY"):
        logger.error("FATAL: The selected API key is invalid.")
        sys.exit(1)
    try:
        gemini_client = genai.Client(api_key=api_key)
        logger.info("Gemini API client created successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize Gemini client: {e}", exc_info=True)
        sys.exit(1)

    # --- パスと進捗データの準備 ---
    room_path = Path(constants.ROOMS_DIR) / args.room_name
    rag_data_path = room_path / "rag_data"

    # ソースに応じて進捗ファイルと処理対象を切り替え
    if args.source == "import":
        progress_file = rag_data_path / "import_progress.json"
        source_dir = room_path / "log_import_source"
        processed_dir = source_dir / "processed"
        source_dir.mkdir(parents=True, exist_ok=True)
        processed_dir.mkdir(parents=True, exist_ok=True)
    else: # active_log
        # アクティブログは専用の進捗ファイルを使い、過去ログの進捗に影響を与えない
        progress_file = rag_data_path / "active_log_internal_progress.json"
        # 処理対象は単一の入力ファイル
        source_dir, processed_dir = None, None

    # ... (rag_dataフォルダの存在確認は変更なし) ...
    rag_data_path.mkdir(parents=True, exist_ok=True)

    progress_data = {}
    if progress_file.exists():
        # ... (進捗ファイルの読み込みは変更なし) ...
        with open(progress_file, "r", encoding="utf-8") as f:
            try:
                progress_data = json.load(f)
                logger.info(f"Successfully loaded progress file: {progress_file}")
            except json.JSONDecodeError:
                logger.warning(f"Progress file {progress_file} is corrupted. Starting from scratch.")


    # --- メイン処理 ---
    try:
        files_to_process = []
        if args.source == "import":
            all_logs = sorted([f for f in source_dir.glob("*.txt") if f.is_file()])
            files_to_process = [f for f in all_logs if progress_data.get(f.name, {}).get("status") != "completed"]
        elif args.input_file and Path(args.input_file).exists():
            files_to_process = [Path(args.input_file)]

        # ... (files_to_process が空の場合の処理は変更なし) ...
        if not files_to_process:
            logger.info("All log files have already been processed for this source.")
            return

        logger.info(f"Found {len(files_to_process)} log file(s) to process.")

        for log_file in files_to_process:
            try:
                # ... (ログファイル読み込みとペア抽出は変更なし) ...
                logger.info(f"--- Processing log file: {log_file.name} ---")
                conversation_pairs = extract_conversation_pairs(str(log_file))

                if not conversation_pairs:
                    logger.warning(f"No conversation pairs found in {log_file.name}. Marking as completed.")
                    if args.source == "import":
                        progress_data[log_file.name] = {"status": "completed"}
                        shutil.move(str(log_file), str(processed_dir / log_file.name))
                    continue

                # ... (リソース初期化は変更なし) ...
                file_progress = progress_data.get(log_file.name, {})
                start_pair_index = file_progress.get("last_processed_pair_index", -1) + 1

                graph_path = rag_data_path / "knowledge_graph.graphml"
                G = load_graph(graph_path)
                embeddings = GoogleGenerativeAIEmbeddings(model="gemini-embedding-001", google_api_key=api_key)
                vector_store = FAISS.load_local(str(rag_data_path), embeddings, "episode_summary_index", allow_dangerous_deserialization=True) if (rag_data_path / "episode_summary_index.faiss").exists() else None

                if start_pair_index > 0:
                    logger.info(f"Resuming {log_file.name} from conversation pair {start_pair_index}.")

                # --- 会話ペアごとのループ ---
                for i, pair in enumerate(conversation_pairs[start_pair_index:], start=start_pair_index):
                    # ... (ステージ1: Episodic Memory は変更なし) ...
                    start_stage = file_progress.get("last_completed_stage", 0) if i == start_pair_index else 0
                    combined_content = f"USER: {pair.get('user_content', '')}\nAGENT: {pair.get('agent_content', '')}".strip()
                    episode_summary_doc = None

                    if start_stage < 1:
                        logger.info(f"  - Pair {i+1}/{len(conversation_pairs)}, Stage 1: Generating episodic memory...")
                        summary_text = generate_episodic_summary(gemini_client, combined_content)
                        if summary_text is None:
                            raise RuntimeError("Failed to generate episodic summary after max retries.")
                        episode_id = str(uuid.uuid4())
                        episode_data = {"episode_id": episode_id, "timestamp": datetime.now().isoformat(), "summary": summary_text, "source_log": log_file.name, "pair_index": i}
                        short_term_path = rag_data_path / "memory_short_term_summary.txt"
                        mid_term_path = rag_data_path / "memory_mid_term_summary.json"
                        with open(short_term_path, "a", encoding="utf-8") as f, open(mid_term_path, "a", encoding="utf-8") as jf:
                            f.write(f"## Episode: {episode_id} (Source: {log_file.name}, Pair: {i})\n{summary_text}\n\n")
                            jf.write(json.dumps(episode_data, ensure_ascii=False) + "\n")
                        episode_summary_doc = f"Episode ID: {episode_id}\nTimestamp: {episode_data['timestamp']}\nSummary:\n{summary_text}"
                        file_progress.update({"status": "in_progress", "last_processed_pair_index": i, "last_completed_stage": 1})
                        progress_data[log_file.name] = file_progress
                        save_progress(progress_file, progress_data)
                        logger.info(f"    - Stage 1 completed.")

                    # --- ステージ2: Deepening Semantic Memory (全面的に書き換え) ---
                    if start_stage < 2:
                        logger.info(f"  - Pair {i+1}/{len(conversation_pairs)}, Stage 2: Deepening semantic memory...")

                        # 1. エンティティ抽出
                        raw_entities = extract_entities(combined_content)

                        # 1.5 意味のあるエンティティのみをフィルタリング
                        meaningful_entities = filter_meaningful_entities(gemini_client, raw_entities, combined_content)

                        # 2. エンティティ正規化
                        normalized_entity_map = normalize_entities(gemini_client, meaningful_entities)
                        # 逆引き辞書を作成 (例: {"ユーザー": "USER", "User": "USER"})
                        reverse_alias_map = {alias: canonical for canonical, aliases in normalized_entity_map.items() for alias in aliases}

                        # 3. 関係性の一括抽出
                        relations = extract_rich_relations_from_chunk(gemini_client, combined_content)
                        if relations is None:
                            raise RuntimeError("Failed to extract relations after max retries.")

                        if relations:
                            for rel in relations:
                                subj_raw = rel.get("subject")
                                obj_raw = rel.get("object")

                                # 4. 関係性の主語・目的語を正規化
                                subj_norm = reverse_alias_map.get(subj_raw, subj_raw)
                                obj_norm = reverse_alias_map.get(obj_raw, obj_raw)

                                if all([subj_norm, obj_norm, rel.get("relation")]):
                                    if not G.has_node(subj_norm): G.add_node(subj_norm)
                                    if not G.has_node(obj_norm): G.add_node(obj_norm)

                                    if not G.has_edge(subj_norm, obj_norm):
                                        G.add_edge(
                                            subj_norm, obj_norm,
                                            label=rel.get("relation"),
                                            polarity=rel.get("polarity"),
                                            intensity=rel.get("intensity"),
                                            context=rel.get("context")
                                        )
                                        logger.info(f"      - Found relation: {subj_norm} -> {rel.get('relation')} -> {obj_norm}")
                            save_graph(G, graph_path)
                        else:
                            logger.info("    - No significant relations found in this pair.")

                        file_progress.update({"last_completed_stage": 2})
                        progress_data[log_file.name] = file_progress
                        save_progress(progress_file, progress_data)
                        logger.info(f"    - Stage 2 completed.")

                    # --- ステージ3: RAG Indexing (変更なし) ---
                    if start_stage < 3:
                        # ... (変更なし) ...
                        logger.info(f"  - Pair {i+1}/{len(conversation_pairs)}, Stage 3: Indexing for RAG...")
                        max_retries = 5
                        retry_count = 0
                        success = False
                        while retry_count < max_retries:
                            try:
                                if episode_summary_doc is None:
                                    mid_term_path = rag_data_path / "memory_mid_term_summary.json"
                                    if mid_term_path.exists():
                                        with open(mid_term_path, "r", encoding="utf-8") as jf:
                                            for line in jf:
                                                try:
                                                    item = json.loads(line)
                                                    if item.get("source_log") == log_file.name and item.get("pair_index") == i:
                                                        episode_summary_doc = f"Episode ID: {item['episode_id']}\nTimestamp: {item['timestamp']}\nSummary:\n{item['summary']}"
                                                        logger.info("      - Found previous summary for this pair to index.")
                                                        break
                                                except json.JSONDecodeError: continue
                                if episode_summary_doc:
                                    if vector_store is None:
                                        vector_store = FAISS.from_texts([episode_summary_doc], embeddings)
                                    else:
                                        vector_store.add_texts([episode_summary_doc])
                                    with tempfile.TemporaryDirectory() as temp_dir:
                                        temp_path_str = str(Path(temp_dir) / "temp_index")
                                        vector_store.save_local(temp_path_str)
                                        # Windowsではatomic moveができないことがあるので、shutil.moveを使う
                                        faiss_target = rag_data_path / "episode_summary_index.faiss"
                                        pkl_target = rag_data_path / "episode_summary_index.pkl"
                                        if faiss_target.exists(): faiss_target.unlink()
                                        if pkl_target.exists(): pkl_target.unlink()
                                        shutil.move(f"{temp_path_str}/index.faiss", str(faiss_target))
                                        shutil.move(f"{temp_path_str}/index.pkl", str(pkl_target))
                                else:
                                    logger.warning("    - Could not find summary to index for this pair. Skipping RAG indexing.")
                                success = True
                                break
                            except (GoogleGenerativeAIError, google_exceptions.ResourceExhausted) as e:
                                if "429" in str(e) or isinstance(e, google_exceptions.ResourceExhausted):
                                    retry_count += 1
                                    if retry_count >= max_retries:
                                        logger.error(f"Embedding API rate limit exceeded. Max retries ({max_retries}) reached for pair {i}.")
                                        raise e
                                    wait_time = 5 * (2 ** (retry_count - 1))
                                    logger.info(f"Embedding rate limit hit. Retrying in {wait_time} seconds... ({retry_count}/{max_retries})")
                                    time.sleep(wait_time)
                                else:
                                    logger.error(f"A non-retriable Google/LangChain error occurred during RAG indexing for pair {i}: {e}", exc_info=True)
                                    raise e
                        if not success:
                            raise RuntimeError(f"Failed to index for RAG after {max_retries} retries without a clear exception.")
                        file_progress.update({"last_completed_stage": 3})
                        progress_data[log_file.name] = file_progress
                        save_progress(progress_file, progress_data)
                        logger.info(f"    - Stage 3 completed.")

                    # --- ペア完了処理 (変更なし) ---
                    file_progress.update({"last_processed_pair_index": i, "last_completed_stage": 0})
                    progress_data[log_file.name] = file_progress
                    save_progress(progress_file, progress_data)
                    logger.info(f"  - Successfully processed pair {i+1}/{len(conversation_pairs)}.")

                # --- ファイル完了処理 (ソースに応じた分岐を追加) ---
                if args.source == "import":
                    logger.info(f"--- Successfully completed all pairs for {log_file.name} ---")
                    progress_data[log_file.name] = {"status": "completed"}
                    shutil.move(str(log_file), str(processed_dir / log_file.name))

            except Exception as e:
                # ... (例外処理は変更なし) ...
                logger.error(f"Processing of file {log_file.name} was interrupted by an error. Saving progress and stopping.", exc_info=True)
                break

    finally:
        # ... (最終的な進捗保存は変更なし) ...
        logger.info("Saving final progress...")
        save_progress(progress_file, progress_data)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.critical(f"An unhandled exception occurred in the archivist process: {e}", exc_info=True)
        sys.exit(1)
