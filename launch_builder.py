# launch_builder.py
import gradio as gr

if __name__ == "__main__":
    print("--- Gradio Theme Builderを起動します ---")
    # Nexus Ark本体(7860)と衝突しないように、ポート7861を明示的に指定
    gr.themes.builder().launch(server_port=7861)