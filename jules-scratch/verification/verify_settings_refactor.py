import re
from playwright.sync_api import sync_playwright, expect

def run(playwright):
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()

    try:
        # 1. Navigate to the application
        page.goto("http://127.0.0.1:7860")

        # 2. Click the main settings accordion to open it
        settings_accordion = page.get_by_text("⚙️ 設定")
        expect(settings_accordion).to_be_visible()
        settings_accordion.click()

        # 3. Verify the new tab names
        expect(page.get_by_role("tab", name="共通")).to_be_visible()
        expect(page.get_by_role("tab", name="個別")).to_be_visible()
        expect(page.get_by_role("tab", name="🎨 パレット")).to_be_visible()

        # 4. Click on the "個別" tab
        individual_settings_tab = page.get_by_role("tab", name="個別")
        individual_settings_tab.click()

        # 5. Find and click the new "Streaming Display Settings" accordion
        streaming_accordion = page.get_by_text("📜 ストリーミング表示設定")
        expect(streaming_accordion).to_be_visible()
        streaming_accordion.click()

        # 6. Verify the checkbox and slider are now visible inside the new accordion
        typewriter_checkbox = page.get_by_label("タイプライター風の逐次表示を有効化")
        # Use get_by_role to be more specific and avoid strict mode violation
        speed_slider = page.get_by_role("slider", name="表示速度")

        expect(typewriter_checkbox).to_be_visible()
        expect(speed_slider).to_be_visible()

        # 7. Take a screenshot for visual confirmation
        page.screenshot(path="jules-scratch/verification/settings_refactor_verification.png")
        print("Screenshot taken successfully.")

    except Exception as e:
        print(f"An error occurred: {e}")
        page.screenshot(path="jules-scratch/verification/error_screenshot.png")

    finally:
        browser.close()

with sync_playwright() as playwright:
    run(playwright)