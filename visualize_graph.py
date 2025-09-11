# visualize_graph.py (v3: キャッシュ強制再構築機能付き)

import os
import sys
import argparse
import logging
from pathlib import Path

import networkx as nx
import matplotlib
import matplotlib.pyplot as plt
import japanize_matplotlib

# ▼▼▼【ここからが最終修正：フォントキャッシュの強制再構築】▼▼▼
# サブプロセスとして実行された際に、正しいフォントキャッシュを読み込ませるための、おまじない
try:
    matplotlib.font_manager._load_fontmanager(try_read_cache=False)
    logging.info("Matplotlib font manager cache has been successfully rebuilt.")
except Exception as e:
    logging.warning(f"Could not force-rebuild font cache. This might cause issues on some environments. Error: {e}")
# ▲▲▲【修正はここまで】▲▲▲


# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def visualize_knowledge_graph(room_name: str):
    # ... (以降の関数の内容は、前回の修正のままで変更ありません) ...
    """
    Loads a directed knowledge graph and saves a visualization with arrows and Japanese labels.
    """
    rag_data_path = Path("characters") / room_name / "rag_data"
    graph_path = rag_data_path / "knowledge_graph.graphml"
    output_dir = rag_data_path / "visualizations"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"graph_{room_name}_{int(plt.time.time())}.png"

    if not graph_path.exists():
        print(f"Error: Knowledge graph file not found at {graph_path}", file=sys.stderr)
        sys.exit(1)

    try:
        G = nx.read_graphml(graph_path)
        if not isinstance(G, nx.DiGraph):
            G = G.to_directed()

        if not G.nodes():
             print(f"Error: Knowledge graph for {room_name} is empty.", file=sys.stderr)
             sys.exit(1)

        plt.figure(figsize=(20, 16))
        pos = nx.spring_layout(G, k=1.5, iterations=50, seed=42)
        nx.draw_networkx_nodes(G, pos, node_size=4000, node_color='lightblue', alpha=0.9)
        nx.draw_networkx_labels(G, pos, font_size=12, font_weight='bold')
        edge_labels = nx.get_edge_attributes(G, 'label')
        nx.draw_networkx_edges(
            G, pos, edge_color='gray', width=1.5,
            arrowstyle='->', arrowsize=20, alpha=0.7
        )
        nx.draw_networkx_edge_labels(
            G, pos, edge_labels=edge_labels, font_color='red', font_size=10,
            bbox=dict(facecolor='white', alpha=0.6, edgecolor='none', pad=0.5)
        )
        plt.title(f"Knowledge Graph for {room_name}", size=24)
        plt.axis('off')
        plt.tight_layout()
        plt.savefig(output_path, format='png', dpi=150)
        plt.close()

        print(str(output_path))

    except Exception as e:
        logging.error(f"Failed to visualize graph: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        print(f"Error: Failed to visualize graph. Details: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Nexus Ark Knowledge Graph Visualizer")
    parser.add_argument("room_name", help="The name of the room to visualize.")
    args = parser.parse_args()
    visualize_knowledge_graph(args.room_name)
