import google.genai as genai
from typing import List, TypedDict, Optional
from PIL import Image
import io # ヘルパー関数用にインポート

# グラフ全体で引き回す情報の器を定義
class AgentState(TypedDict):
    input_parts: List[any]
    perceived_content: str
    rag_results: Optional[str]
    response_outline: Optional[str]
    final_response: str
    chat_history: List[dict]
    api_key: str

# --- ヘルパー関数 ---
def _pil_to_bytes(img: Image.Image) -> bytes:
    """PIL ImageをJPEGバイトに変換する"""
    img_byte_arr = io.BytesIO()
    save_image = img.convert('RGB') if img.mode in ('RGBA', 'P') else img
    save_image.save(img_byte_arr, format='JPEG')
    return img_byte_arr.getvalue()

# --- 知覚ノードの実装 ---
def perceive_input_node(state: AgentState):
    """【聖典作法準拠】入力パーツを知覚し、テキストに変換するノード。"""
    print("--- 知覚ノード実行 ---")

    # 1. APIキーを使ってクライアントを生成
    try:
        client = genai.Client(api_key=state['api_key'])
    except Exception as e:
        print(f"致命的エラー: genai.Client の初期化に失敗。APIキーを確認してください。詳細: {e}")
        return {"perceived_content": f"[エラー: APIクライアントを準備できませんでした。APIキーを確認してください。]"}

    vision_model_name = 'models/gemini-2.5-flash' # 指示通り（旧 gemini-1.5-flash相当）

    input_parts = state["input_parts"]
    perceived_texts = []

    images = [p for p in input_parts if isinstance(p, Image.Image)]
    texts = [p for p in input_parts if isinstance(p, str)]
    user_text = "\n".join(texts)

    try:
        # 2. generate_contentに渡すためのペイロード（辞書のリスト）を作成
        if images:
            print(f"  - {len(images)}個の画像を知覚中...")
            # 画像とテキストを辞書形式でまとめる
            # ユーザーテキストと指示文をpartsの先頭に持ってくる方が自然か検討
            # visionモデルへの指示は明確に
            current_parts = [{'text': "以下のユーザー発言と添付画像を総合的に理解し、画像の内容を詳細に説明してください。"}]
            if user_text:
                current_parts.append({'text': f"ユーザーの発言:\n{user_text}"})

            for img in images:
                 # _pil_to_bytes がバイト列を返すので、それをそのまま 'data' に渡す
                 current_parts.append({'inline_data': {'mime_type': 'image/jpeg', 'data': _pil_to_bytes(img)}})

            contents_for_perception = [{'role': 'user', 'parts': current_parts}]

            # 3. client.models.generate_content を呼び出す
            response = client.models.generate_content(
                model=vision_model_name,
                contents=contents_for_perception
            )
            # response.text が利用可能か確認
            generated_description = response.text if hasattr(response, 'text') else "[画像内容の取得に失敗しました]"
            if response.prompt_feedback and response.prompt_feedback.block_reason:
                generated_description = f"[知覚ブロック: 安全性設定により画像内容の取得がブロックされました。理由: {response.prompt_feedback.block_reason}]"

            # ユーザーテキストがない場合の出力を調整
            if user_text:
                perceived_texts.append(f"ユーザーの発言：\n---\n{user_text}\n---\n\n添付画像の内容：\n---\n{generated_description}\n---")
            else:
                perceived_texts.append(f"添付画像の内容：\n---\n{generated_description}\n---")

        else: # 画像がない場合
            if user_text:
                perceived_texts.append(f"ユーザーの発言：\n---\n{user_text}\n---")
            else:
                # テキストも画像もない場合は、その旨を伝えるか、あるいはこのノードをスキップする条件分岐が上位であるべき
                perceived_texts.append("[ユーザーからの入力が空でした]")

    except Exception as e:
        print(f"  - 知覚処理中にエラー: {e}")
        # traceback.print_exc() # デバッグ用にトレースバック出力も有効
        perceived_texts.append(f"[知覚エラー：添付ファイルの処理に失敗しました。詳細：{e}]")

    combined_perception = "\n\n".join(perceived_texts)
    print(f"  - 知覚結果： {combined_perception[:200]}...")

    return {"perceived_content": combined_perception}


# --- 応答生成ノードの実装 ---
def generate_response_node(state: AgentState):
    """【聖典作法準拠】全ての情報を統合し、最終的な応答を生成するノード。"""
    print("--- 応答生成ノード実行 ---")

    # 1. APIキーを使ってクライアントを生成
    try:
        client = genai.Client(api_key=state['api_key'])
    except Exception as e:
        print(f"致命的エラー: genai.Client の初期化に失敗。APIキーを確認してください。詳細: {e}")
        return {"final_response": f"[エラー: APIクライアントを準備できませんでした。APIキーを確認してください。]"}

    response_model_name = 'models/gemini-2.5-pro' # 指示通り (旧 gemini-1.5-pro 相当)

    # 2. generate_contentに渡すためのペイロード（辞書のリスト）を作成
    #    google-generativeai v0.5.0以降、履歴は {'role': ..., 'parts': [...]} のリスト
    contents_for_generation = []

    # システムプロンプト (もしあれば)
    # ここでは、AgentStateにsystem_promptフィールドがないため、直接記述するか、別途渡す仕組みが必要
    # 例: contents_for_generation.append({'role': 'user', 'parts': [{'text': "あなたは猫です。猫になりきって回答してください。"}]})
    #     contents_for_generation.append({'role': 'model', 'parts': [{'text': "ニャンだ、わかったニャン！"}]})

    # 会話履歴を追加 (state['chat_history'] が正しい形式であることを期待)
    # state['chat_history'] は [{'role': 'user', 'parts': ['こんにちは']}, {'role': 'model', 'parts': ['はい、こんにちは！']}] のような形式
    for history_item in state['chat_history']:
        contents_for_generation.append(history_item)


    # 思考プロセスやRAGの結果をプロンプトに組み込む (指示書の形式を踏襲)
    # これらは perceived_content とは別に、ユーザーに見せない内部情報として扱うことが多い
    prompt_context_parts = []
    prompt_context_parts.append("# 知覚された情報")
    prompt_context_parts.append(state['perceived_content'])

    if state.get('rag_results'):
        prompt_context_parts.append("\n# 内部検索結果(RAG)")
        prompt_context_parts.append(state['rag_results'])

    if state.get('response_outline'):
        prompt_context_parts.append("\n# 思考の骨子")
        prompt_context_parts.append(state['response_outline'])

    # 最後のユーザー入力として、統合されたコンテキストを追加
    final_user_prompt = "\n".join(prompt_context_parts)
    contents_for_generation.append({'role': 'user', 'parts': [{'text': final_user_prompt}]})

    generated_text = "[応答生成エラー：不明な問題]"
    try:
        # 3. client.models.generate_content を呼び出す
        response = client.models.generate_content(
            model=response_model_name,
            contents=contents_for_generation
            # generation_config={"temperature": 0.7} # 必要に応じて設定
            # safety_settings={...} # 必要に応じて設定
        )

        # response.text が最も簡単な方法だが、より詳細な制御が必要な場合は candidates を見る
        if hasattr(response, 'text') and response.text:
            generated_text = response.text
        elif response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
            generated_text = "".join(part.text for part in response.candidates[0].content.parts if hasattr(part, 'text'))

        if response.prompt_feedback and response.prompt_feedback.block_reason:
            generated_text = f"[応答ブロック: 安全性設定により応答がブロックされました。理由: {response.prompt_feedback.block_reason}]"

        print(f"  - 生成された応答： {generated_text[:100]}...")
        return {"final_response": generated_text}
    except Exception as e:
        print(f"  - 応答生成中にエラー: {e}")
        # traceback.print_exc() # デバッグ用
        # エラーレスポンスにprompt_feedbackが含まれているか確認
        error_detail = f"詳細: {e}"
        if 'response' in locals() and hasattr(response, 'prompt_feedback') and response.prompt_feedback:
            error_detail += f" プロンプトフィードバック: {response.prompt_feedback}"
        return {"final_response": f"[エラー：応答生成に失敗しました。{error_detail}]"}


from langgraph.graph import StateGraph, END

# (RAG検索ノード、思考ノードなどがここにあると仮定)

workflow = StateGraph(AgentState)

# ノードをグラフに追加
workflow.add_node("perceive", perceive_input_node)
# workflow.add_node("rag_search", rag_search_node) # 既存のRAGノード
# workflow.add_node("think", think_node)           # 既存の思考ノード
workflow.add_node("generate", generate_response_node)

# グラフの実行順序を定義
workflow.set_entry_point("perceive")
# workflow.add_edge("perceive", "rag_search") # 知覚→RAG
# workflow.add_edge("rag_search", "think")    # RAG→思考
# workflow.add_edge("think", "generate")      # 思考→応答生成
workflow.add_edge("perceive", "generate") # ★もしRAGや思考ノードが未実装なら、一旦知覚から直接応答生成に繋ぐ

workflow.add_edge("generate", END)

# グラフをコンパイル
app = workflow.compile()
