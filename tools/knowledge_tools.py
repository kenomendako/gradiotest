# tools/knowledge_tools.py
import os
from pathlib import Path
from langchain_core.tools import tool
import networkx as nx
import spacy

# --- spaCy Model Loading ---
# このツールが独立して動作できるよう、自身のプロセスでモデルをロードする
try:
    nlp = spacy.load("ja_core_news_lg")
except OSError:
    # モデルがない場合でも、ツール自体は定義されるようにする
    # 呼び出し時にエラーを返すことで、アプリケーション全体の起動は妨げない
    nlp = None

@tool
def search_knowledge_graph(query: str, room_name: str) -> str:
    """
    AI自身の長期記憶（知識グラフ）に保存されている、過去の会話から抽出された客観的な事実や、登場人物・場所・物事の関係性について、自然言語で検索する。
    query: 検索したい内容を記述した、自然言語の質問文（例：「キャラクターAとアイテムBの関係は？」）。
    """
    # 1. 前提条件のチェック
    if nlp is None:
        return "【エラー】言語解析モデルがロードされていません。管理者に連絡してください。"
    if not room_name:
        return "【エラー】検索対象のルームが指定されていません。"

    # 2. 知識グラフの読み込み
    graph_path = Path("characters") / room_name / "rag_data" / "knowledge_graph.graphml"
    if not graph_path.exists():
        return "【情報】このルームには、まだ知識グラフ（長期記憶）が構築されていません。"
    try:
        G = nx.read_graphml(graph_path)
    except Exception as e:
        return f"【エラー】知識グラフファイルの読み込みに失敗しました: {e}"

    if not G.nodes():
        return "【情報】知識グラフは存在しますが、まだ空です。"

    # 3. 質問文から、核となるエンティティを抽出
    doc = nlp(query)
    entities_in_query = [ent.text for ent in doc.ents]
    if not entities_in_query:
        # もし固有表現が見つからなければ、名詞を抽出するフォールバック
        entities_in_query = [token.text for token in doc if token.pos_ == "NOUN"]

    if not entities_in_query:
        return "【エラー】質問文から、検索の核となるキーワード（人名、場所、物事など）を特定できませんでした。"

    # 4. グラフ内から、関連する情報を検索
    found_facts = []
    # 質問に含まれる各エンティティについてループ
    for entity in entities_in_query:
        # グラフ内に、そのエンティティに部分一致するノードがあるか検索
        # （例：質問が「キャラクターA」なら、グラフの「キャラクターA」や「キャラクターABC」がヒットする）
        matching_nodes = [node for node in G.nodes() if entity in node]

        for node in matching_nodes:
            # そのノードに接続されている全てのエッジ（関係性）を取得
            for neighbor in G.neighbors(node):
                relation_data = G.get_edge_data(node, neighbor)
                relation = relation_data.get("relation", "不明な関係")
                fact = f"- 「{node}」は「{neighbor}」と「{relation}」の関係にあります。"
                if fact not in found_facts:
                    found_facts.append(fact)

    # 5. 結果を整形して返す
    if not found_facts:
        return f"【検索結果】「{', '.join(entities_in_query)}」に関する客観的な事実は、長期記憶の中に見つかりませんでした。"

    summary = f"【長期記憶からの検索結果】\n" + "\n".join(found_facts)
    return summary
