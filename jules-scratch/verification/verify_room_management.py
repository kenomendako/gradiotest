import time
import shutil
import os
from playwright.sync_api import sync_playwright, expect

def run_verification(playwright):
    # Clean up previous test runs
    if os.path.exists("characters"):
        shutil.rmtree("characters")
        print("--- Cleaned up old 'characters' directory ---")

    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page()

    BASE_URL = "http://127.0.0.1:7860"

    try:
        page.goto(BASE_URL)
        print("--- Navigated to Nexus Ark ---")

        # 1. Open the Room Management Accordion
        room_accordion_button = page.get_by_text("チャットルームの作成・管理")
        expect(room_accordion_button).to_be_visible(timeout=30000) # Wait for app to load
        room_accordion_button.click()
        print("--- Opened Room Management Accordion ---")

        # 2. Test Room Creation
        print("--- Testing Room Creation ---")
        page.get_by_role("tab", name="新規作成").click()

        new_room_name_input = page.get_by_label("ルーム名（必須）")
        new_user_name_input = page.get_by_label("あなたの表示名（任意）")
        new_prompt_input = page.get_by_label("初期システムプロンプト（任意）")

        test_room_name = "Jules's Test Room"
        safe_test_room_name = "Jules's_Test_Room"

        new_room_name_input.fill(test_room_name)
        new_user_name_input.fill("Jules")
        new_prompt_input.fill("This is a test prompt.")

        page.get_by_role("button", name="ルームを作成").click()

        # Check for success toast and updated dropdown
        expect(page.get_by_text(f"新しいルーム「{test_room_name}」を作成しました。")).to_be_visible()
        main_room_dropdown = page.get_by_label("ルームを選択")
        expect(main_room_dropdown).to_have_value(safe_test_room_name) # Check internal value

        print("--- Room Creation Successful ---")
        page.screenshot(path="jules-scratch/verification/01_creation_success.png")

        # Add a small delay to ensure DOM updates are processed
        time.sleep(2)

        # 3. Test Room Management and Editing
        print("--- Testing Room Management and Editing ---")
        page.get_by_role("tab", name="管理").click()

        manage_selector_input = page.get_by_label("管理するルームを選択")
        manage_selector_input.click() # Click to open the dropdown
        page.get_by_role("option", name=test_room_name, exact=True).click()

        manage_form = page.locator("div.gradio-column", has=page.get_by_text("フォルダ名（編集不可）")).filter(has_text="ルーム名")
        expect(manage_form).to_be_visible()

        renamed_room_name = "Jules's Renamed Room"
        manage_room_name_input = manage_form.get_by_label("ルーム名")
        manage_description_input = manage_form.get_by_label("ルームの説明")

        expect(manage_room_name_input).to_have_value(test_room_name)
        manage_room_name_input.fill(renamed_room_name)
        manage_description_input.fill("This is an updated description.")

        page.get_by_role("button", name="変更を保存").click()

        expect(page.get_by_text(f"ルーム「{renamed_room_name}」の設定を保存しました。")).to_be_visible()

        # Verify dropdown text updated
        expect(main_room_dropdown.locator(f"text={renamed_room_name}")).to_be_visible()

        print("--- Room Editing Successful ---")
        page.screenshot(path="jules-scratch/verification/02_management_success.png")

        # 4. Test Room Deletion
        print("--- Testing Room Deletion ---")
        # The renamed room should still be selected in the management tab

        # Handle the confirm dialog
        page.on("dialog", lambda dialog: dialog.accept())

        page.get_by_role("button", name="このルームを削除").click()

        expect(page.get_by_text(f"ルーム「{safe_test_room_name}」を完全に削除しました。")).to_be_visible()

        # Verify dropdown no longer contains the deleted room
        expect(main_room_dropdown.locator(f"text={renamed_room_name}")).not_to_be_visible()

        print("--- Room Deletion Successful ---")
        page.screenshot(path="jules-scratch/verification/03_deletion_success.png")

    except Exception as e:
        print(f"An error occurred: {e}")
        page.screenshot(path="jules-scratch/verification/error.png")
        raise
    finally:
        browser.close()

if __name__ == "__main__":
    with sync_playwright() as p:
        run_verification(p)
