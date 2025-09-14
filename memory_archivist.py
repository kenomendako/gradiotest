import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

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
以下の【生の会話ログ】を分析し、思考のステップに従って、登場するすべての主要なエンティティの対応辞書を生成してください。

【思考のステップ】
1.  まず、会話に登場するすべての主要なエンティティ（人物、AI、場所、重要概念）をリストアップします。
2.  次に、英語やその他の言語で記述されたエンティティを、最も自然な**日本語の表現に翻訳**します。
3.  最後に、同一のエンティティを指す異なる表現（例：「USER」「ケノ」「あなた」）を一つにまとめ、代表となる**「正式名称（日本語）」**をキー、それ以外の**「別名」**をリストの値とするPythonの辞書（dict）を生成します。

【生の会話ログ】
---
{chunk}
---

【最重要ルール】
- あなた自身の思考や挨拶は絶対に含めず、Pythonの辞書オブジェクトのみをJSON形式で出力してください。
- 該当するエンティティがない場合は、空の辞書 `{{}}` を出力してください。
"""
    response_text = call_gemini_with_smart_retry(gemini_client, constants.INTERNAL_PROCESSING_MODEL, prompt)

    if response_text is None:
        # AIからの応答がNoneの場合（APIエラーなど）の戻り値を、関数の期待する型に合わせる
        # この変更により、呼び出し元でのエラーハンドリングが容易になる
        return {} if "normalize_entities" in sys._getframe().f_code.co_name else []

    try:
        # ステップ1: AIの応答から ```json ... ``` ブロックを最優先で抽出する
        match = re.search(r'```json\s*([\s\S]*?)\s*```', response_text)
        if match:
            json_text = match.group(1)
        else:
            # ブロックがない場合は、応答全体を対象とする
            json_text = response_text

        # ステップ2: 目に見えない制御文字やエスケープシーケンスを除去する「聖別」処理
        # JSONとして有効な文字(ASCII文字、日本語文字、括弧、引用符など)以外を排除
        sanitized_text = re.sub(r'[^\x20-\x7E\u3000-\u303F\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF\uFF00-\uFFEF\n\r\t]', '', json_text)

        data = json.loads(sanitized_text)

        # 関数の種類に応じて、正しいデータ型を返す
        if "normalize_entities" in sys._getframe().f_code.co_name:
             return data if isinstance(data, dict) else {}
        else: # extract_relationships
             return data if isinstance(data, list) else []

    except json.JSONDecodeError:
        logger.warning(f"JSON parsing failed after sanitization. Attempting to repair with AI. Sanitized text: {sanitized_text}")
        repaired_json_text = repair_json_string_with_ai(gemini_client, sanitized_text)
        if repaired_json_text:
            try:
                data = json.loads(repaired_json_text)
                logger.info("Successfully repaired JSON string.")
                if "normalize_entities" in sys._getframe().f_code.co_name:
                    return data if isinstance(data, dict) else {}
                else: # extract_relationships
                    return data if isinstance(data, list) else []
            except json.JSONDecodeError:
                logger.error(f"Failed to parse even the repaired JSON. Repaired text: {repaired_json_text}")
                return {} if "normalize_entities" in sys._getframe().f_code.co_name else []
        else:
            logger.error("AI failed to repair the JSON string.")
            return {} if "normalize_entities" in sys._getframe().f_code.co_name else []


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
    完全に正規化された会話チャンクから、「述語の抽象化」と「属性の分離」を行い、知識を抽出する。
    """
    prompt = f"""
あなたは、対話ログから構造化された知識を抽出する、世界最高峰の認知科学者です。

【あなたのタスク】
以下の【完全に正規化された会話ログ】を分析し、思考プロセスに従って、エンティティ間の関係性や、エンティティ自身の属性を抽出してください。

【思考プロセス】
1.  まず、「誰が、誰に、何をした」という**【関係性】**を見つけます。
2.  次に、「誰が、どのような状態・性質である」という**【属性】**を見つけます。これは、関係性の主語と目的語が同一になるような、自己言及のケースです。
3.  「何をした（述語）」や「どのような状態（属性）」という部分を、最も本質的で簡潔な動詞句や形容詞句に『抽象化』します。
4.  その他の付帯情報（例：「親のように」「監視用に」「大切に」）は`context`として分離します。

【完全に正規化された会話ログ】
---
{normalized_chunk}
---

【出力フォーマット】
以下の厳格なJSON配列フォーマットで、抽出した知識のみを出力してください。

[
  {{
    "type": "relationship", // or "attribute"
    "subject": "（エンティティ名）",
    // "relationship" の場合
    "predicate": "（抽象化した動詞句）",
    "object": "（エンティティ名、または概念を表す短い名詞句）",
    // "attribute" の場合
    "attribute_key": "（属性の種類、例：感情、状態、性質）",
    "attribute_value": "（属性の値、例：独占欲が強い、AIである）",
    // 共通
    "polarity": "（感情の極性: "positive", "negative", "neutral"）",
    "intensity": "（感情の強度: 1〜10の整数）",
    "context": "（関係性や属性を修飾する、分離された付帯情報）"
  }}
]

【最重要ルール】
- 自己言及や状態の記述は、必ず`"type": "attribute"`として抽出してください。
- あなた自身の思考や挨拶は絶対に含めず、JSON配列のみを出力してください。
- 抽出する知識がない場合は、空の配列 `[]` を出力してください。
"""
    # (この関数の残りの部分は、v9の指示書にあった「聖別」ロジックをそのまま使用します)
    response_text = call_gemini_with_smart_retry(gemini_client, constants.INTERNAL_PROCESSING_MODEL, prompt)

    if response_text is None:
        return []

    try:
        match = re.search(r'```json\s*([\s\S]*?)\s*```', response_text)
        json_text = match.group(1) if match else response_text
        sanitized_text = re.sub(r'[^\x20-\x7E\u3000-\u303F\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF\uFF00-\uFFEF\n\r\t]', '', json_text)
        data = json.loads(sanitized_text)
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        logger.warning(f"JSON parsing failed after sanitization. Attempting to repair. Text: {sanitized_text}")
        repaired_json_text = repair_json_string_with_ai(gemini_client, sanitized_text)
        if repaired_json_text:
            try:
                data = json.loads(repaired_json_text)
                logger.info("Successfully repaired JSON string.")
                return data if isinstance(data, list) else []
            except json.JSONDecodeError:
                logger.error(f"Failed to parse even the repaired JSON. Repaired: {repaired_json_text}")
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

                        # ▼▼▼【ここからがv12アーキテクチャの核心】▼▼▼
                        # --- グラフへの反映 ---
                        # 1. エンティティの存在を保証（Noneチェックを追加）
                        for name, aliases in entity_map.items():
                            if not name or not isinstance(name, str):
                                continue
                            if not G.has_node(name):
                                G.add_node(
                                    name,
                                    aliases=json.dumps(aliases or [], ensure_ascii=False),
                                    category="Unknown",
                                    frequency=1
                                )
                            else:
                                G.nodes[name]['frequency'] = G.nodes[name].get('frequency', 0) + 1

                        # 2. 抽出された知識（関係性 or 属性）をグラフに追加
                        for fact in relationships:
                            fact_type = fact.get("type")
                            subj = fact.get("subject")

                            # --- 品質検査：subjectの妥当性チェック ---
                            if not isinstance(subj, str) or not subj or subj not in entity_map:
                                logger.warning(f"Skipping fact due to invalid or unmapped subject: '{subj}'")
                                continue

                            if fact_type == "relationship":
                                pred = fact.get("predicate")
                                obj = fact.get("object")

                                # --- 『空虚の聖絶』：ここが最後の砦 ---
                                if not all(isinstance(val, str) and val for val in [pred, obj]):
                                    logger.warning(f"Skipping incomplete relationship: {{'s': '{subj}', 'p': '{pred}', 'o': '{obj}'}}")
                                    continue

                                if not G.has_node(obj): G.add_node(obj, category="Concept", frequency=1)

                                if G.has_edge(subj, obj):
                                    G[subj][obj]['frequency'] = G[subj][obj].get('frequency', 1) + 1
                                else:
                                    G.add_edge(
                                        subj, obj,
                                        label=pred,
                                        polarity=fact.get("polarity", "neutral"),
                                        intensity=fact.get("intensity", 0),
                                        context=fact.get("context", ""),
                                        frequency=1
                                    )
                                    logger.info(f"      - Found Relationship: {subj} -> {pred} -> {obj}")

                            elif fact_type == "attribute":
                                key = fact.get("attribute_key")
                                value = fact.get("attribute_value")

                                if not all(isinstance(val, str) and val for val in [key, value]):
                                    logger.warning(f"Skipping incomplete attribute for '{subj}': {{'key': '{key}', 'value': '{value}'}}")
                                    continue

                                G.nodes[subj][key] = value
                                G.nodes[subj]['frequency'] = G.nodes[subj].get('frequency', 0) + 1
                                logger.info(f"      - Found Attribute for '{subj}': {key} = {value}")

                            else:
                                logger.warning(f"Skipping unknown fact type: '{fact_type}'")
                        # ▲▲▲【v12アーキテクチャここまで】▲▲▲

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
