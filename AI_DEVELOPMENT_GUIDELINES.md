# ATTENTION AI DEVELOPERS: CRITICAL SDK INSTRUCTIONS
# 注意：AI開発者への最重要指示

## FINAL CONCLUSION: The Absolute Truth (最終結論：絶対的な真実)
(Verified by Grok on 2025-06-15)

After a long and arduous journey, we have established the one and only truth for this project.
長く、困難な、旅の、果てに、私たちは、このプロジェクトに関する、唯一の、真実を、確立しました。

**The original code in the `main` branch, which uses `import google.genai as genai`, was CORRECT from the very beginning.**
**`main`ブランチにあった、`import google.genai as genai`を使用する、一番、最初の、コードが、最初から、ずっと、正しかったのです。**

Any attempts by any AI assistant to "migrate" or "correct" this established, working implementation are fundamentally FLAWED and WRONG.
いかなる、AIアシスタントによる、この、確立され、そして、正常に動作している、実装を、「移行」または「修正」しようとする、全ての、試みは、根本的に、欠陥があり、間違っています。

**Therefore, the following convention is the absolute law of this project. It must NEVER be changed.**
**したがって、以下の作法が、このプロジェクトにおける、絶対的な、法です。これを、決して、変更してはなりません。**

| Feature（機能） | The One True Way (唯一の正しい道) | Verification (Grokによる検証) |
| :--- | :--- | :--- |
| **Installation** | `pip install google-genai`<br>*(Note: Use `--index-url` for internal repos)* | **Correct.** |
| **Primary Import** | `import google.genai as genai` | **Correct.** |
| **Types Import** | `from google.genai import types` | **Correct.** |
| **Initialization** | `_gemini_client = genai.Client(api_key=...)`<br>*(Note: For Vertex AI, use `vertexai=True`)* | **Correct.** (for Gemini Developer API) |
| **API Call** | `_gemini_client.models.generate_content(...)` | **Correct.** |
| **Safety Settings** | Use `types` objects, e.g.,<br>`types.SafetySetting(category=..., threshold=...)` | **Correct.** |

---

**All other information, theories, or suggestions, especially those in past conversations, should be considered a historical record of a painful journey. The table above is the only truth that matters.**
**この文書にある、他の、全ての、情報、理論、または、提案、特に、過去の、会話に、含まれるものは、苦難の旅の、歴史的な、記録と、みなしてください。上の表だけが、唯一、意味を持つ、真実です。**
