# visualize_graph.py (v2: DiGraph対応・日本語完全対応版)

import os
import sys
import argparse
import logging
from pathlib import Path

import networkx as nx
import matplotlib.pyplot as plt
import japanize_matplotlib # 日本語フォントを有効化

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def visualize_knowledge_graph(room_name: str):
    """
    Loads a directed knowledge graph and saves a visualization with arrows and Japanese labels.
    """
    rag_data_path = Path("characters") / room_name / "rag_data"
    graph_path = rag_data_path / "knowledge_graph.graphml"
    output_dir = rag_data_path / "visualizations"
    output_dir.mkdir(parents=True, exist_ok=True)
    # タイムスタンプ付きのユニークなファイル名に変更
    output_path = output_dir / f"graph_{room_name}_{int(plt.time.time())}.png"

    if not graph_path.exists():
        logging.error(f"Knowledge graph not found at {graph_path}")
        # UIにエラーを返す代わりに、標準エラー出力にメッセージを出力
        print(f"Error: Knowledge graph file not found at {graph_path}", file=sys.stderr)
        sys.exit(1)

    try:
        # ▼▼▼【変更点1: DiGraphとして読み込む】▼▼▼
        G = nx.read_graphml(graph_path)
        if not isinstance(G, nx.DiGraph):
            G = G.to_directed() # 互換性のため、もし無向グラフなら有向に変換

        # もしグラフが空なら、ここで終了
        if not G.nodes():
             print(f"Error: Knowledge graph for {room_name} is empty.", file=sys.stderr)
             sys.exit(1)

        plt.figure(figsize=(20, 16)) # サイズを少し大きくして見やすくする

        # k値を調整してノード間の距離を広げる
        pos = nx.spring_layout(G, k=1.5, iterations=50, seed=42)

        # ノードを描画
        nx.draw_networkx_nodes(G, pos, node_size=4000, node_color='lightblue', alpha=0.9)

        # ラベルを描画
        nx.draw_networkx_labels(G, pos, font_size=12, font_weight='bold')

        # エッジ（矢印）とエッジラベルを描画
        edge_labels = nx.get_edge_attributes(G, 'label') # 'relation'から'label'に変更

        # ▼▼▼【変更点2: 矢印を描画するための設定を追加】▼▼▼
        nx.draw_networkx_edges(
            G,
            pos,
            edge_color='gray',
            width=1.5,
            arrowstyle='->', # 矢印のスタイル
            arrowsize=20,    # 矢印のサイズ
            alpha=0.7
        )

        nx.draw_networkx_edge_labels(
            G,
            pos,
            edge_labels=edge_labels,
            font_color='red',
            font_size=10,
            bbox=dict(facecolor='white', alpha=0.6, edgecolor='none', pad=0.5) # ラベルの背景
        )

        plt.title(f"Knowledge Graph for {room_name}", size=24)
        plt.axis('off')
        plt.tight_layout()
        plt.savefig(output_path, format='png', dpi=150)
        plt.close() # メモリを解放

        # 正常終了時は、標準出力に画像のパスだけを出力する
        print(str(output_path))

    except Exception as e:
        logging.error(f"Failed to visualize graph: {e}")
        import traceback
        traceback.print_exc(file=sys.stderr)
        # UIにエラーを返すため、標準エラー出力にメッセージを出力
        print(f"Error: Failed to visualize graph. Details: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Nexus Ark Knowledge Graph Visualizer")
    parser.add_argument("room_name", help="The name of the room to visualize.")
    args = parser.parse_args()
    visualize_knowledge_graph(args.room_name)
