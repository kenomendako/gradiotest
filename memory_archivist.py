import argparse
import argparse
import os
import sys
import uuid
import json
import re
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

def normalize_entities_from_chunk(gemini_client: genai.Client, chunk: str) -> dict | None:
    """
    【第一段階：正規化の聖域】
    生の会話チャンクから、正規化されたエンティティの対応辞書を生成する。
    例: {"USER": ["ケノ", "あなた"], "AGENT": ["ミーモ"]}
    """
    prompt = f"""
あなたは、対話ログから登場人物や重要概念を特定し、名前の揺れを吸収する「名寄せ」の専門家です。

【あなたのタスク】
以下の【生の会話ログ】に登場するすべての主要なエンティティ（人物、AI、場所、重要概念）を特定してください。
次に、同一のエンティティを指す異なる表現（例：「USER」「ケノ」「あなた」）を一つにまとめ、代表となる**「正式名称」**をキー、それ以外の**「別名」**をリストの値とするPythonの辞書（dict）を生成してください。

【生の会話ログ】
---
{chunk}
---

【最重要ルール】
- あなた自身の思考や挨拶は絶対に含めず、Pythonの辞書オブジェクトのみをJSON形式で出力してください。
- 該当するエンティティがない場合は、空の辞書 `{{}}` を出力してください。
- キー（正式名称）には、最も頻繁に使われるか、最も正式だと思われる名前を選んでください。
"""
    response_text = call_gemini_with_smart_retry(gemini_client, constants.INTERNAL_PROCESSING_MODEL, prompt)
    if response_text is None:
        return None
    try:
        json_text = response_text.strip().removeprefix("```json").removesuffix("```").strip()
        data = json.loads(json_text)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        logger.error(f"Failed to parse JSON for entity normalization. Response: {response_text}")
        return {}


def deterministic_normalize_chunk(chunk: str, entity_map: dict) -> str:
    """
    【第二段階：機械的置換】
    正規化辞書に基づき、会話チャンク内のすべての別名を正式名称に機械的に置換する。
    """
    normalized_chunk = chunk
    # 置換が他の単語に影響を与えないよう、別名リストを「長い順」にソートする
    # 例：「AI」より先に「他のAI」を置換することで、「他のUSER」のような誤変換を防ぐ
    aliases_to_replace = []
    for name, aliases in entity_map.items():
        for alias in aliases:
            aliases_to_replace.append((alias, name))

    # 長いエイリアスから先に置換する
    aliases_to_replace.sort(key=lambda x: len(x[0]), reverse=True)

    for alias, name in aliases_to_replace:
        # 単語の境界を意識して置換するため、より安全な置換を行う
        # （この実装はシンプルだが多くの場合で機能する）
        normalized_chunk = normalized_chunk.replace(alias, name)

    return normalized_chunk


def repair_json_string_with_ai(gemini_client: genai.Client, broken_json_string: str) -> str | None:
    """
    【機械仕掛けの校正官】
    文字化けなどで破損した可能性のあるJSON文字列を、AIに修復させる。
    """
    prompt = f"""
あなたは、破損したJSON文字列を修復する専門家です。
以下の【破損した可能性のあるテキスト】を分析し、それが有効なJSONオブジェクトまたはJSON配列になるように修復してください。

【破損した可能性のあるテキスト】
---
{broken_json_string}
---

【最重要ルール】
- あなた自身の思考や挨拶、言い訳は絶対に含めず、修復されたJSON文字列のみを出力してください。
- どうしても修復不可能な場合は、空のJSONオブジェクト `{{}}` または `[]` を出力してください。
- 出力は必ず ````json` と ```` で囲んでください。
"""
    # 修復には、より能力の高いモデルを使用することを検討する
    response_text = call_gemini_with_smart_retry(gemini_client, "gemini-2.5-flash", prompt)
    if response_text is None:
        return None

    # AIの応答からJSON部分だけを確実に抽出
    match = re.search(r'```json\s*([\s\S]*?)\s*```', response_text)
    if match:
        return match.group(1).strip()
    else:
        # フォールバックとして、AIの応答全体を試す
        return response_text.strip()


def extract_relationships_from_normalized_chunk(gemini_client: genai.Client, normalized_chunk: str) -> list | None:
    """
    【第三段階：関係性の建築家 v3 - 最終版】
    完全に正規化された会話チャンクから、「述語の抽象化」を行い、関係性を抽出する。
    """
    prompt = f"""
あなたは、対話ログから構造化された知識を抽出する、世界最高峰の認知科学者です。

【あなたのタスク】
以下の【完全に正規化された会話ログ】を分析し、エンティティ間の重要な関係性を抽出してください。

【思考プロセス】
1.  まず、文の中から「誰が」「誰に」「何をした」という関係性の核となる部分を見つけます。
2.  次に、「何をした」という部分を、**最も本質的で、簡潔な動詞句（例：「尊敬する」「生成した」「感じる」）**に**『抽象化』**し、これを`predicate`とします。
3.  そして、関係性を修飾する付帯情報（例：「親のように」「監視用に」「大切に」）は、すべて`context`として分離・記録します。
4.  最後に、主語・目的語が具体的なエンティティでない場合（例：「USERの願い」「ルシアンの人物像」）、それらを短い名詞句として`object`に設定します。

【完全に正規化された会話ログ】
---
{normalized_chunk}
---

【出力フォーマット】
以下の厳格なJSON配列フォーマットで、抽出した関係性リストのみを出力してください。

[
  {{
    "subject": "（ログに登場するエンティティ名）",
    "predicate": "（あなたが抽象化した、本質的な動詞句）",
    "object": "（ログに登場するエンティティ名、または概念を表す短い名詞句）",
    "polarity": "（感情の極性: "positive", "negative", "neutral"）",
    "intensity": "（感情の強度: 1〜10の整数）",
    "context": "（関係性を修飾する、分離された付帯情報）"
  }}
]

【最重要ルール】
- `predicate`は、必ず関係性の本質を表す**動詞句**にしてください。
- `object`が具体的なエンティティでない場合は、必ず15文字以内の短い名詞句にしてください。
- あなた自身の思考や挨拶は絶対に含めず、JSON配列のみを出力してください。
- 抽出する関係性がない場合は、空の配列 `[]` を出力してください。
"""
    response_text = call_gemini_with_smart_retry(gemini_client, constants.INTERNAL_PROCESSING_MODEL, prompt)

    if response_text is None:
        return None

    try:
        json_text = response_text.strip().removeprefix("```json").removesuffix("```").strip()
        data = json.loads(json_text)
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        logger.warning(f"JSON parsing failed. Attempting to repair with AI. Original text: {response_text}")
        repaired_json_text = repair_json_string_with_ai(gemini_client, response_text)
        if repaired_json_text:
            try:
                data = json.loads(repaired_json_text)
                logger.info("Successfully repaired JSON string.")
                return data if isinstance(data, list) else []
            except json.JSONDecodeError:
                logger.error(f"Failed to parse even the repaired JSON. Repaired text: {repaired_json_text}")
                return []
        else:
            logger.error("AI failed to repair the JSON string.")
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


def extract_conversation_pairs(log_content: str) -> list:
    """
    Processes a log file's content string and groups them into
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

                    if start_stage < 2:
                        logger.info(f"  - Pair {i+1}/{len(conversation_pairs)}, Stage 2: Deepening semantic memory...")

                        # ▼▼▼【ここからがv6アーキテクチャの核心】▼▼▼
                        # --- ステージ 2a: 正規化辞書の生成 ---
                        logger.info("    - Stage 2a: Normalizing entities...")
                        entity_map = normalize_entities_from_chunk(gemini_client, combined_content)
                        if entity_map is None:
                            raise RuntimeError("Failed to normalize entities after max retries.")

                        # --- ステージ 2b: 機械的置換 ---
                        logger.info("    - Stage 2b: Performing deterministic replacement...")
                        normalized_chunk = deterministic_normalize_chunk(combined_content, entity_map)

                        # --- ステージ 2c: 関係性の抽出 ---
                        logger.info("    - Stage 2c: Extracting relationships from normalized chunk...")
                        relationships = extract_relationships_from_normalized_chunk(gemini_client, normalized_chunk)
                        if relationships is None:
                            raise RuntimeError("Failed to extract relationships after max retries.")

                        # --- グラフへの反映ロジック（v5から流用・微修正） ---
                        # 1. エンティティをグラフに追加
                        for name, aliases in entity_map.items():
                            if not G.has_node(name):
                                G.add_node(
                                    name,
                                    aliases=json.dumps(aliases, ensure_ascii=False),
                                    category="Unknown", # カテゴリは今後の課題
                                    frequency=1
                                )
                            else:
                                G.nodes[name]['frequency'] = G.nodes[name].get('frequency', 0) + 1

                        # 2. 関係性をグラフに追加
                        for rel in relationships:
                            subj = rel.get("subject")
                            obj = rel.get("object")
                            pred = rel.get("predicate")

                            # subjectがentity_mapのキーに存在することを確認
                            if subj in entity_map and all(isinstance(val, str) and val for val in [pred, obj]):
                                # objectがentity_mapに存在しない場合、それは「概念」ノードとして扱う
                                if not G.has_node(obj): G.add_node(obj, category="Concept", frequency=1)

                                if G.has_edge(subj, obj):
                                    # 既存エッジの重みを更新
                                    G[subj][obj]['frequency'] = G[subj][obj].get('frequency', 1) + 1
                                    # より情報量の多いコンテキストで上書きするなどのロジックも将来的に検討可能
                                else:
                                    G.add_edge(
                                        subj, obj,
                                        label=pred,
                                        polarity=rel.get("polarity"),
                                        intensity=rel.get("intensity"),
                                        context=rel.get("context"),
                                        frequency=1
                                    )
                                    logger.info(f"      - Found relationship: {subj} -> {pred} -> {obj}")
                            else:
                                logger.warning(f"Skipping relationship with invalid or unmapped subject: '{subj}'")
                        # ▲▲▲【v6アーキテクチャここまで】▲▲▲

                        save_graph(G, graph_path)
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
