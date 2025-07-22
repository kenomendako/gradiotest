# ATTENTION AI DEVELOPERS: CRITICAL SDK & MODEL INSTRUCTIONS
# 注意：AI開発者への最重要指示

## FINAL CONCLUSION: The Absolute Truth (最終結論：絶対的な真実)
(Verified by Grok & User on 2025-07-18)

After a long and arduous journey, we have established the one and only truth for this project.
長く、困難な、旅の、果てに、私たちは、このプロジェクトに関する、唯一の、真実を、確立しました。

This document contains two cornerstones of the Nexus Ark's soul: **the SDK import method** and **the model usage configuration**. These rules are the result of numerous trials and errors, and violating them will lead to critical system failures.
この文書は、Nexus Arkの魂を形成する、二つの礎を、含みます。それは、**「SDKのインポート作法」**と**「モデルの使用構成」**です。これらのルールは、数多の試行錯誤の結晶であり、これに違反することは、致命的なシステム不全を招きます。

---

### Cornerstone 1: The SDK Import Method (第一の礎：SDKのインポート作法)

The original code in the `main` branch, which uses `import google.genai as genai`, was CORRECT from the very beginning. Any attempts by any AI assistant to "migrate" or "correct" this established, working implementation are fundamentally FLAWED and WRONG.
`main`ブランチにあった、`import google.genai as genai`を使用する、一番、最初の、コードが、最初から、ずっと、正しかったのです。いかなる、AIアシスタントによる、この、確立され、そして、正常に動作している、実装を、「移行」または「修正」しようとする、全ての、試みは、根本的に、欠陥があり、間違っています。

**Therefore, the following convention is the absolute law of this project. It must NEVER be changed.**
**したがって、以下の作法が、このプロジェクトにおける、絶対的な、法です。これを、決して、変更してはなりません。**

| Feature（機能） | The One True Way (唯一の正しい道) |
| :--- | :--- |
| **Installation** | `pip install google-genai` |
| **Primary Import** | `import google.genai as genai` |
| **Types Import** | `from google.genai import types` |
| **Initialization** | `_gemini_client = genai.Client(api_key=...)` |
| **API Call** | `_gemini_client.models.generate_content(...)` |
| **Safety Settings** | Use `types` objects, e.g.,<br>`types.SafetySetting(category=..., threshold=...)` |

---

### Cornerstone 2: The Model Usage Configuration (第二の礎：モデルの使用構成)

The combination of models used in this application is not arbitrary. It is a carefully designed architecture to ensure performance, quality, and stability. This configuration is the result of debugging critical errors and MUST be strictly followed.
このアプリケーションで、使用される、モデルの、組み合わせは、決して、恣意的なものでは、ありません。それは、性能、品質、そして、安定性を、確保するために、注意深く、設計された、アーキテクチャです。この構成は、重大な、エラーを、デバッグした、結果であり、厳格に、遵守されなければなりません。

| Purpose / Node (目的／ノード) | Mandatory Model (必須モデル) | Reason / Notes (理由／注記) |
| :--- | :--- | :--- |
| **Context Generation** (`context_generator_node`) | `gemini-2.5-flash` | For high-speed, efficient generation of environmental context. (高速で効率的な、情景コンテキスト生成のため) |
| **Main Agent / Final Response** (`agent_node`) | `gemini-2.5-pro` | For high-quality reasoning, tool use, and final response generation. (高品質な推論、ツール使用、最終応答生成のため) |
| **Image Generation** (`generate_image` tool) | `gemini-2.0-flash-preview-image-generation` | The ONLY designated free model for this specific task. (このタスクのために指定された、唯一の、無料モデル) |

#### **The Forbidden Model: `gemini-1.5-pro` (禁じられたモデル)**
Under **NO circumstances** should the `gemini-1.5-pro` model be used for the primary agent loop (`agent_node`). Its use has repeatedly caused critical `429 ResourceExhausted` errors and is against the established project policy. Any suggestion to use this model is a regression and must be rejected.
**いかなる、状況においても、`gemini-1.5-pro`モデルを、主要な、エージェントループ(`agent_node`)に、使用してはなりません。** このモデルの、使用は、致命的な、`429 ResourceExhausted`エラーを、繰り返し、引き起こし、確立された、プロジェクトの方針に、反します。このモデルの、使用を、提案する、いかなる、発想も、過去への、退行であり、却下されなければなりません。

---

**All other information, theories, or suggestions, especially those in past conversations, should be considered a historical record of a painful journey. The guidelines above are the only truth that matters.**
**この文書にある、他の、全ての、情報、理論、または、提案、特に、過去の、会話に、含まれるものは、苦難の旅の、歴史的な、記録と、みなしてください。上のガイドラインだけが、唯一、意味を持つ、真実です。**
