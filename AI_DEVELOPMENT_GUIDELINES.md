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
