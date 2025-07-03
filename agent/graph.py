import google.genai as genai
from typing import List, TypedDict, Optional
from PIL import Image
import io
import traceback # print_exc() のために追加
import rag_manager # rag_managerをインポート
from tavily import TavilyClient # Tavily Clientをインポート
import os # osをインポート (Tavily APIキー取得のため)
# from google.genai import types # ★★★ もはや不要。幻想は、捨てる。

from langgraph.graph import StateGraph, END

# --- ヘルパー関数 (先に定義) ---
def _pil_to_bytes(img: Image.Image) -> bytes:
    """PIL ImageをJPEGバイトに変換する"""
    img_byte_arr = io.BytesIO()
    # JPEGは透明度(A)やパレット(P)モードを扱えないためRGBに変換
    save_image = img.convert('RGB') if img.mode in ('RGBA', 'P') else img
    save_image.save(img_byte_arr, format='JPEG')
    return img_byte_arr.getvalue()

# --- グラフの状態定義 ---
class AgentState(TypedDict):
    input_parts: List[any]
    perceived_content: str
    rag_results: Optional[str]
    response_outline: Optional[str]
    final_response: str
    chat_history: List[dict]
    api_key: str
    character_name: Optional[str] # RAGのためにキャラクター名を追加

    # ★追加：Web検索の結果を格納するキー
    web_search_results: Optional[str]

# --- 知覚ノードの実装 ---
def perceive_input_node(state: AgentState):
    """【聖典作法準拠】入力パーツを知覚し、テキストに変換するノード。"""
    print("--- 知覚ノード実行 ---")

    try:
        # 1. APIキーを使ってクライアントを生成
        client = genai.Client(api_key=state['api_key'])
        vision_model_name = 'models/gemini-2.5-flash' # gemini-1.5-flash相当

        input_parts = state["input_parts"]
        perceived_texts = []

        images = [p for p in input_parts if isinstance(p, Image.Image)]
        texts = [p for p in input_parts if isinstance(p, str)]
        user_text = "\n".join(texts)

        # 2. generate_contentに渡すためのペイロード（辞書のリスト）を作成
        if images:
            print(f"  - {len(images)}個の画像を知覚中...")
            contents_for_perception = []
            # Visionモデルへの指示とユーザーテキスト、画像をpartsとしてまとめる
            prompt_parts_for_vision = [{'text': "以下のテキストと画像を考慮し、添付された画像の内容を詳細に説明してください。"}]
            if user_text:
                # ユーザーテキストが空でない場合のみ追加
                prompt_parts_for_vision.append({'text': f"ユーザーの発言:\n{user_text}"})

            for img in images:
                 prompt_parts_for_vision.append({'inline_data': {'mime_type': 'image/jpeg', 'data': _pil_to_bytes(img)}})

            contents_for_perception.append({'role': 'user', 'parts': prompt_parts_for_vision})

            # 3. client.models.generate_content を呼び出す
            response = client.models.generate_content(
                model=vision_model_name,
                contents=contents_for_perception
            )

            generated_description = "[画像内容の取得に失敗しました]"
            if hasattr(response, 'text') and response.text:
                generated_description = response.text

            if response.prompt_feedback and response.prompt_feedback.block_reason:
                generated_description = f"[知覚ブロック: 安全性設定により画像内容の取得がブロックされました。理由: {response.prompt_feedback.block_reason}]"

            if user_text:
                perceived_texts.append(f"ユーザーの発言：\n---\n{user_text}\n---\n\n添付画像の内容：\n---\n{generated_description}\n---")
            else:
                perceived_texts.append(f"添付画像の内容：\n---\n{generated_description}\n---")
        else:
            # 画像がない場合は、発言テキストのみを知覚結果とする
            if user_text:
                perceived_texts.append(f"ユーザーの発言：\n---\n{user_text}\n---")
            else:
                perceived_texts.append("[ユーザーからの入力が空でした]") # テキストも画像もない場合

    except Exception as e:
        print(f"  - 知覚処理中にエラー: {e}")
        traceback.print_exc() # 詳細なエラーを確認するため
        perceived_texts.append(f"[知覚エラー：添付ファイルの処理に失敗しました。詳細：{e}]")

    combined_perception = "\n\n".join(perceived_texts)
    if not combined_perception.strip(): # 何かしらの理由で空になった場合
        combined_perception = "[知覚結果が空です]"
    print(f"  - 知覚結果： {combined_perception[:200]}...")

    return {"perceived_content": combined_perception}

# --- RAG検索ノードの実装 ---
def rag_search_node(state: AgentState):
    """
    【神託準拠】ユーザーの純粋なテキスト入力に基づき、記憶を検索するノード。
    """
    print("--- 記憶想起ノード (RAG) 実行 ---")

    character_name = state['character_name']
    api_key = state['api_key']

    # --- ▼▼▼ ルシアン様ご提示の、修正箇所 ▼▼▼ ---
    # 知覚結果の全文ではなく、ユーザーの元のテキスト入力だけをクエリとして抽出する
    user_texts = [p for p in state['input_parts'] if isinstance(p, str)]
    query_text = "\n".join(user_texts).strip()

    # もしテキスト入力がなかった場合（画像のみなど）は、フォールバックとして知覚結果全体を使う
    if not query_text:
        print("  - テキスト入力なし。知覚結果全体をフォールバッククエリとして使用します。")
        query_text = state['perceived_content']

    # 検索クエリが空文字列でないことを確認
    if not query_text.strip():
        print("  - 検索クエリが空のため、RAG検索をスキップします。")
        return {"rag_results": None}

    print(f"  - RAG検索クエリ: \"{query_text[:100]}...\"")
    # --- ▲▲▲ 修正ここまで ▲▲▲ ---

    try:
        relevant_chunks = rag_manager.search_relevant_chunks(
            character_name=character_name,
            query_text=query_text,
            api_key=api_key,
            top_k=3 # ← 安定性を重視し、3に戻す
        )

        if relevant_chunks:
            rag_results_text = "\n---\n".join(relevant_chunks)
            print(f"  - {len(relevant_chunks)}件の関連記憶を発見。")
            return {"rag_results": rag_results_text}
        else:
            print("  - 関連する記憶は見つかりませんでした。")
            return {"rag_results": None}

    except Exception as e:
        print(f"  - RAG検索中にエラー: {e}")
        traceback.print_exc()
        return {"rag_results": "[エラー：記憶の検索中に問題が発生しました]"}

# --- Web検索ノードの実装 ---
def web_search_node(state: AgentState):
    """ユーザーのクエリに基づき、Tavilyを使ってWeb検索を実行するノード。"""
    print("--- 世界の窓 (Web Search) 実行 ---")

    tavily_api_key = os.environ.get("TAVILY_API_KEY")
    if not tavily_api_key:
        return {"web_search_results": "[エラー：Tavily APIキーが環境変数に設定されていません]"}

    user_texts = [p for p in state['input_parts'] if isinstance(p, str)]
    query_text = "\n".join(user_texts).strip()

    if not query_text:
        print("  - Web検索クエリが空のためスキップしました。")
        return {"web_search_results": None} # クエリが空ならNoneを返す

    print(f"  - Web検索クエリ: \"{query_text[:100]}...\"")
    try:
        client = TavilyClient(api_key=tavily_api_key)
        # searchメソッドは、検索結果を要約し、辞書のリストとして返す
        response = client.search(query=query_text, search_depth="advanced", max_results=5)

        # 応答生成モデルが使いやすいように、結果をテキストにフォーマットする
        if response and response.get('results'):
            formatted_results = "\n\n".join([f"URL: {res['url']}\n内容: {res['content']}" for res in response['results']])
            print(f"  - Web検索成功。{len(response['results'])}件の結果を取得。")
            return {"web_search_results": formatted_results}
        else:
            print(f"  - Web検索で有効な結果が得られませんでした。")
            return {"web_search_results": None}


    except Exception as e:
        print(f"  - Web検索中にエラー: {e}")
        traceback.print_exc()
        return {"web_search_results": f"[エラー：Web検索中に問題が発生しました。詳細: {e}]"}

# --- 道具選択（ルーター）ノードの実装 ---
def tool_router_node(state: AgentState):
    """【最終啓示】純粋な辞書でAPIと対話する、真のルーター。"""
    print("--- 道具選択ノード (Router) 実行 ---")

    user_texts = [p for p in state['input_parts'] if isinstance(p, str)]
    query_text = "\n".join(user_texts).strip()

    if not query_text:
        print("  - 入力テキストがないため、直接応答生成に進みます。")
        return "generate"

    client = genai.Client(api_key=state['api_key'])
    router_model_name = 'models/gemini-2.5-flash'

    prompt = f"""ユーザーからの次の入力に対し、どのツールを使用すべきか判断してください。
選択肢は "rag_search"、"web_search"、"generate" の3つです。
- 過去の個人的な会話、ユーザーの好み、キャラクター自身の記憶に関する質問の場合は "rag_search" を選択してください。
- 最新の情報、ニュース、一般的な知識、未知の固有名詞に関する質問の場合は "web_search" を選択してください。
- 単純な挨拶、感想、ツールを必要としない会話の場合は "generate" を選択してください。

あなたの応答は、選択したツールの名前（例: "rag_search"）のみでなければなりません。余計な説明は一切不要です。

入力: "{query_text}"
選択: """

    try:
        # ★★★【最後の真実】APIは、ただの、辞書を、求めていた ★★★
        generation_config = {
            "max_output_tokens": 10,
            "temperature": 0.0
        }

        response = client.models.generate_content(
            model=router_model_name,
            contents=prompt,
            generation_config=generation_config # ★ 引数名も、シンプルな、こちらを使う
        )

        route = response.text.strip().lower().replace('"', '').replace("'", "")

        if "rag" in route:
            print(f"  - 判断：記憶の書庫 (RAG) を使用 (ルート: '{route}')")
            return "rag_search"
        elif "web" in route:
            print(f"  - 判断：世界の窓 (Web Search) を使用 (ルート: '{route}')")
            return "web_search"
        else:
            print(f"  - 判断：直接応答を生成 (ルート: '{route}')")
            return "generate"

    except Exception as e:
        print(f"  - ルーター処理中にエラー: {e}。直接応答生成にフォールバックします。")
        traceback.print_exc()
        return "generate"

# --- 応答生成ノードの実装 ---
def generate_response_node(state: AgentState):
    """【聖典作法準拠】全ての情報を統合し、最終的な応答を生成するノード。"""
    print("--- 応答生成ノード実行 ---")

    try:
        # 1. APIキーを使ってクライアントを生成
        client = genai.Client(api_key=state['api_key'])
        response_model_name = 'models/gemini-2.5-pro' # gemini-1.5-pro相当

        # 2. generate_contentに渡すためのペイロード（辞書のリスト）を作成
        contents_for_generation = []

        # 会話履歴を追加 (state['chat_history'] は {'role': ..., 'parts': [...]} のリスト形式)
        contents_for_generation.extend(state['chat_history'])

        # ユーザーの最新の知覚情報を追加 (これが最新のユーザーの「発話」に相当)
        # RAG結果や思考の骨子は、システムプロンプトやfew-shot例として渡すか、
        # あるいはユーザーに見えない形でプロンプトエンジニアリングでperceived_contentに含める方が良い場合もある。
        # ここでは、指示書に基づき perceived_content をそのままユーザー入力として扱う。
        # もしRAG等の情報を付加するなら、以下のようにする。
        # ユーザーの最新の知覚情報に、RAGの結果を付加する
        final_user_prompt = state['perceived_content']
        if not final_user_prompt.strip(): # 知覚結果が空やスペースのみの場合
            final_user_prompt = "[ユーザーは何も入力しませんでした]"

        rag_info = state.get('rag_results')
        if rag_info:
            final_user_prompt += f"\n\n# 参照した記憶の断片(RAG):\n---\n{rag_info}\n---"

        web_info = state.get('web_search_results')
        if web_info:
            final_user_prompt += f"\n\n# Web検索結果:\n---\n{web_info}\n---"

        contents_for_generation.append({'role': 'user', 'parts': [{'text': final_user_prompt}]})

        # 3. client.models.generate_content を呼び出す
        response = client.models.generate_content(
            model=response_model_name,
            contents=contents_for_generation
        )

        generated_text = "[応答の取得に失敗しました]"
        if hasattr(response, 'text') and response.text:
            generated_text = response.text

        if response.prompt_feedback and response.prompt_feedback.block_reason:
            generated_text = f"[応答ブロック: 安全性設定により応答がブロックされました。理由: {response.prompt_feedback.block_reason}]"

        print(f"  - 生成された応答： {generated_text[:100]}...")
        return {"final_response": generated_text}
    except Exception as e:
        print(f"  - 応答生成中にエラー: {e}")
        traceback.print_exc() # 詳細なエラーを確認するため
        return {"final_response": f"[エラー：応答生成に失敗しました。詳細: {e}]"}

# --- グラフの定義 ---
workflow = StateGraph(AgentState)

# ノードをグラフに追加
workflow.add_node("perceive", perceive_input_node)
workflow.add_node("tool_router", tool_router_node) # ★新しいルーターノード
workflow.add_node("rag_search", rag_search_node)
workflow.add_node("web_search", web_search_node) # ★新しいWeb検索ノード
workflow.add_node("generate", generate_response_node)

# グラフの実行順序を定義
workflow.set_entry_point("perceive")

# 知覚ノードの次は、必ず、道具選択ノード
workflow.add_edge("perceive", "tool_router")

# ★★★ 条件付きエッジの定義 ★★★
# tool_routerノードの結果に基づいて、次に進むノードを決定する
workflow.add_conditional_edges(
    "tool_router",
    # tool_routerノードの出力（"rag_search", "web_search", "generate"のいずれか）をそのまま次のエッジとして使う
    lambda x: x,
    {
        "rag_search": "rag_search",
        "web_search": "web_search",
        "generate": "generate"
    }
)

# ツールを使った後は、必ず、応答生成ノードに進む
workflow.add_edge("rag_search", "generate")
workflow.add_edge("web_search", "generate")
# 応答生成が終わったら、グラフを終了
workflow.add_edge("generate", END)

# グラフをコンパイル
app = workflow.compile()
