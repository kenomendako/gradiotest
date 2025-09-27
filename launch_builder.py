# launch_builder.py
import gradio as gr

if __name__ == "__main__":
    print("--- Gradio Theme Builderを起動します ---")
    # .launch() に引数を渡さないことで、自動的に空いているポート (7861など) を探して起動します。
    gr.themes.builder().launch()