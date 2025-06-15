# ATTENTION AI DEVELOPERS: CRITICAL SDK INSTRUCTIONS
# 注意：AI開発者への最重要指示

## Gemini API SDK Selection (SDKの選択)

THIS PROJECT **MUST** USE THE `google-genai` SDK.
このプロジェクトでは、**必ず** `google-genai` SDKを使用しなければなりません。

DO NOT, under any circumstances, use or revert to `google-generativeai`. It is DEPRECATED and will break the application.
いかなる状況でも `google-generativeai` を使用したり、元に戻したりしないでください。このSDKは **非推奨(DEPRECATED)** であり、アプリケーションを破壊します。

---

### Correct SDK (正しいSDK)
- **Installation (`requirements.txt`):** `google-genai`
- **Import Statement:** `from google import genai`
- **Repository:** `googleapis/python-genai`

### Incorrect / Deprecated SDK (間違い / 非推奨のSDK)
- **Installation:** `google-generativeai`
- **Import Statement:** `import google.generativeai as genai`
- **Repository:** `google-gemini/deprecated-generative-ai-python`

---

**Any attempt to change the SDK from `google-genai` back to `google-generativeai` is a critical error.** Please adhere to this guideline strictly.

**`google-genai` から `google-generativeai` へSDKを変更しようとする試みは、全て重大なエラーです。** このガイドラインを厳格に遵守してください。

---
## Appendix: The Rosetta Stone (SDK Translation Table)
## 付録：ロゼッタストーン（SDK翻訳表）

This table clarifies the critical differences between the **Old World** (`google-generativeai` package) and the **New World** (`google-genai` package). **This project MUST adhere to the "New World" conventions.**
この表は、「旧世界」(`google-generativeai`パッケージ)と「新世界」(`google-genai`パッケージ)の決定的な違いを明確にするものです。**このプロジェクトは、必ず「新世界」の作法に従わなければなりません。**

| Feature（機能） | Old World (`google-generativeai`) | New World (`google-genai`) - **OUR GOAL** |
| :--- | :--- | :--- |
| **Installation** | `pip install google-generativeai` | `pip install google-genai` |
| **Primary Import** | `import google.generativeai as genai` | `import google.genai as genai` |
| **Types Import** | `from google.generativeai import types` | `from google.genai import types` |
| **Initialization** | `client = genai.Client(api_key=...)` | `_gemini_client = genai.Client(api_key=...)` |
| **Model Creation** | `client.get_model(...)` or implicit | `Implicit in API call (model name in generate_content)` |
| **API Call** | `client.models.generate_content(...)` | `_gemini_client.models.generate_content(...)` |
| **Safety Settings** | Dict of `google.generativeai.types.SafetySetting` objects | Dict of `google.genai.types` enum objects (e.g. `{types.HarmCategory.HARASSMENT: types.HarmBlockThreshold.BLOCK_NONE}`) |
