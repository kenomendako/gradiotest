from playwright.sync_api import sync_playwright, expect
import time

def run_verification():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        try:
            # 1. アプリケーションにアクセス
            page.goto("http://127.0.0.1:7860")

            # ページの主要な要素（チャット入力ボックス）が表示されるのを待つ
            # プレースホルダーテキストを使って、チャット入力ボックスを一意に特定する
            chat_input = page.get_by_placeholder("メッセージを入力し、ファイルをドラッグ＆ドロップまたは添付してください...")
            expect(chat_input).to_be_visible(timeout=20000)
            print("✅ チャット入力ボックスが正常に表示されました。")

            # 2. 簡単な操作を実行
            chat_input.fill("こんにちは、最終確認のテストです。")

            # 送信ボタンをクリックする代わりに、Enterキーを押してフォームを送信する
            chat_input.press("Enter")
            print("✅ Enterキーを押してメッセージを送信しました。")

            # AIの応答が表示されるのを待つ
            time.sleep(20) # 応答生成と表示のための待機時間を設定

            # 3. スクリーンショットを撮影
            screenshot_path = "jules-scratch/verification/verification.png"
            page.screenshot(path=screenshot_path)
            print(f"✅ スクリーンショットを撮影しました: {screenshot_path}")

        except Exception as e:
            print(f"❌ 検証中にエラーが発生しました: {e}")
            page.screenshot(path="jules-scratch/verification/error.png")
        finally:
            browser.close()

if __name__ == "__main__":
    run_verification()