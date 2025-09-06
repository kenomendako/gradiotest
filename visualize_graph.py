import os
import sys
import argparse
import logging
from pathlib import Path
import networkx as nx
import matplotlib.pyplot as plt
import japanize_matplotlib

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def visualize_knowledge_graph(room_name: str):
    """
    Loads a knowledge graph and saves a visualization as a PNG file.
    """
    rag_data_path = Path("characters") / room_name / "rag_data"
    graph_path = rag_data_path / "knowledge_graph.graphml"
    output_dir = rag_data_path / "visualizations"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"graph_{room_name}.png"

    if not graph_path.exists():
        logging.error(f"Knowledge graph not found at {graph_path}")
        sys.exit(1)

    try:
        G = nx.read_graphml(graph_path)

        plt.figure(figsize=(16, 12))

        pos = nx.spring_layout(G, k=0.8, iterations=50)

        # Draw nodes
        nx.draw_networkx_nodes(G, pos, node_size=3000, node_color='skyblue')

        # Draw labels
        nx.draw_networkx_labels(G, pos, font_size=12, font_family='IPAexGothic')

        # Draw edges and edge labels
        edge_labels = nx.get_edge_attributes(G, 'relation')
        nx.draw_networkx_edges(G, pos, alpha=0.5)
        nx.draw_networkx_edge_labels(G, pos, edge_labels=edge_labels, font_color='red', font_size=10)

        plt.title(f"Knowledge Graph for {room_name}", size=20)
        plt.axis('off')
        plt.tight_layout()

        # Save the figure
        plt.savefig(output_path, format='png', dpi=150)

        # Print the success message and the path for the UI handler
        print(f"✅ Knowledge graph visualization successful.")
        print(f"Image saved to:")
        print(str(output_path))

    except Exception as e:
        logging.error(f"Failed to visualize graph: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Nexus Ark Knowledge Graph Visualizer")
    parser.add_argument("room_name", help="The name of the room to visualize.")
    args = parser.parse_args()
    visualize_knowledge_graph(args.room_name)
