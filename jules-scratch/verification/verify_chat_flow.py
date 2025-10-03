import re
from playwright.sync_api import sync_playwright, expect

def run_verification(playwright):
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()

    try:
        # 1. Navigate to the app
        page.goto("http://127.0.0.1:7860")

        # 2. Wait for the main chat UI to be ready
        # A good indicator is the chat input box being visible.
        chat_input = page.get_by_placeholder("メッセージを入力し、ファイルをドラッグ＆ドロップまたは添付してください...")
        expect(chat_input).to_be_visible(timeout=30000)
        print("Chat UI is ready.")

        # 3. Send a message to trigger a 2-step tool call
        command_to_send = "現在地を「玄関」に変更して"
        chat_input.fill(command_to_send)
        chat_input.press("Enter")
        print(f"Sent command: '{command_to_send}'")

        # 4. Verify the sequence of events
        # First, the UI should show it's thinking.
        expect(page.get_by_text(re.compile("思考中.*"))).to_be_visible(timeout=15000)
        print("AI is thinking...")

        # Then, a tool result popup should appear.
        # The prompt defines this as "Success: 現在地は..."
        expect(page.get_by_text(re.compile("Success: 現在地は.*"))).to_be_visible(timeout=30000)
        print("Tool result popup appeared.")

        # Finally, the AI should give its text-only report.
        # We expect a new message in the chatbot from the agent.
        # Let's wait for the last message in the chatbot to contain the confirmation.
        final_response_locator = page.locator("#chat_output_area .message-row-assistant").last
        expect(final_response_locator).to_contain_text("移動が完了しました", timeout=30000)
        print("Final confirmation message from AI is visible.")

        # 5. Take a screenshot for visual confirmation
        screenshot_path = "jules-scratch/verification/verification.png"
        page.screenshot(path=screenshot_path)
        print(f"Screenshot saved to {screenshot_path}")

    except Exception as e:
        print(f"An error occurred during verification: {e}")
        # On error, still try to take a screenshot for debugging
        page.screenshot(path="jules-scratch/verification/error_screenshot.png")
        raise

    finally:
        # 6. Clean up
        context.close()
        browser.close()

if __name__ == "__main__":
    with sync_playwright() as playwright:
        run_verification(playwright)