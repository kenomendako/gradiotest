# launch_builder.py

import gradio as gr
import webbrowser
import threading
import time

def open_browser(port):
    """指定されたポートのURLをブラウザで開く"""
    # サーバーが起動するのを少し待つ
    time.sleep(1)
    webbrowser.open(f"http://127.0.0.1:{port}")

if __name__ == "__main__":
    print("--- Gradio Theme Builderを起動します ---")

    theme_builder_app = gr.themes.builder()

    # 別スレッドでブラウザを開く準備
    threading.Thread(target=open_browser, args=(7861,)).start()

    try:
        # サーバーを起動
        # 自動リロード機能を無効化するため、watch_dirsに空リストを指定
        theme_builder_app.launch(server_port=7861, share=False, inbrowser=False, watch_dirs=[])

    except KeyboardInterrupt:
        print("\n--- Theme Builderを終了します ---")
        theme_builder_app.close()