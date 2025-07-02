from typing import List, TypedDict, Optional
from PIL import Image
import google.genai as genai
from langgraph.graph import StateGraph, END

# グラフ全体で引き回す情報の器を定義
class AgentState(TypedDict):
    # UIから直接渡される、生の入力パーツ (テキストや画像)
    input_parts: List[any]

    # 【知覚ノードが生成】全ての入力のテキスト表現
    perceived_content: str

    # 【RAGノードが生成】RAG検索の結果
    rag_results: Optional[str]

    # 【思考ノードが生成】応答の骨子
    response_outline: Optional[str]

    # 【応答生成ノードが生成】最終的なAIの応答
    final_response: str

    # UIから渡される会話履歴
    chat_history: List[dict]

    # ★追加：APIキーをグラフ内で引き回す
    api_key: str

# --- 知覚ノードの実装 ---
def perceive_input_node(state: AgentState):
    """入力パーツを解析し、すべての情報をテキストに変換（知覚）するノード。"""
    print("--- 知覚ノード実行 ---")

    # ★修正：StateからAPIキーを取得してモデルを初期化
    vision_model_name = 'models/gemini-2.5-flash'
    try:
        # transport="rest"を追加すると、より安定する場合があります
        vision_model = genai.GenerativeModel(
            model_name=vision_model_name,
            client=genai.Client(api_key=state['api_key'])
        )
    except Exception as e:
        print(f"致命的エラー: 知覚モデル'{vision_model_name}'の初期化に失敗。APIキー関連の問題の可能性あり。詳細: {e}")
        return {"perceived_content": f"[エラー: 知覚モデル '{vision_model_name}' を準備できませんでした。APIキーまたはモデル名を確認してください。]"}

    input_parts = state["input_parts"]
    perceived_texts = []

    # 画像と言語を分ける必要があるかもしれないため、分離して処理
    images = [p for p in input_parts if isinstance(p, Image.Image)]
    texts = [p for p in input_parts if isinstance(p, str)]
    user_text = "\n".join(texts)

    try:
        if images:
            print(f"  - {len(images)}個の画像を知覚中...")
            # 画像とテキストを同時に渡して説明を求める
            # prompt = ["以下のテキストと画像を考慮し、添付された画像の内容を詳細に説明してください。", user_text] + images # オリジナルのプロンプト
            # Gemini 2.5 Flash (gemini-1.5-flash-001) は content parts の先頭に文字列を許容しないため修正
            prompt_parts = [user_text, "以下のテキストと画像を考慮し、添付された画像の内容を詳細に説明してください。"] + images
            response = vision_model.generate_content(prompt_parts)
            perceived_texts.append(f"ユーザーの発言：\n---\n{user_text}\n---\n\n添付画像の内容：\n---\n{response.text}\n---")
        else:
            # 画像がない場合はテキストのみ
            perceived_texts.append(f"ユーザーの発言：\n---\n{user_text}\n---")

    except Exception as e:
        print(f"  - 知覚処理中にエラー: {e}")
        perceived_texts.append(f"[知覚エラー：添付ファイルの処理に失敗しました。詳細：{e}]")

    combined_perception = "\n\n".join(perceived_texts)
    print(f"  - 知覚結果： {combined_perception[:200]}...")

    return {"perceived_content": combined_perception}

# --- 応答生成ノードの実装 ---
def generate_response_node(state: AgentState):
    """全ての情報を統合し、最終的な応答を生成するノード。"""
    print("--- 応答生成ノード実行 ---")

    # ★修正：StateからAPIキーを取得してモデルを初期化
    response_model_name = 'models/gemini-2.5-pro'
    # response_model_name = 'models/gemini-1.5-pro-latest' # API利用可能性に応じてこちらを使用
    try:
        response_model = genai.GenerativeModel(
            model_name=response_model_name,
            client=genai.Client(api_key=state['api_key'])
        )
    except Exception as e:
        print(f"致命的エラー: 応答生成モデル'{response_model_name}'の初期化に失敗。APIキー関連の問題の可能性あり。詳細: {e}")
        return {"final_response": f"[エラー: 応答生成モデル '{response_model_name}' を準備できませんでした。APIキーまたはモデル名を確認してください。]"}

    # 応答生成に必要な全ての情報をプロンプトにまとめる
    prompt_context = f"""
# 命令
あなたは優秀な対話AIです。以下の情報を統合し、会話履歴を踏まえて、ユーザーへの応答を生成してください。

# 知覚された情報
{state['perceived_content']}

# 内部検索結果(RAG)
{state.get('rag_results', 'なし')}

# 思考の骨子
{state.get('response_outline', 'なし')}
"""
    # 会話履歴を結合
    # chat_session = response_model.start_chat(history=state['chat_history']) # 古い書き方
    # response = chat_session.send_message(prompt_context) # 古い書き方

    # 新しいAPI (v0.5.0以降) の推奨するやり方
    # https://ai.google.dev/gemini-api/docs/api-key-restrictions?lang=python#chat-history
    # https://github.com/google-gemini/cookbook/blob/main/quickstarts/Chat.ipynb
    messages = []
    # state['chat_history'] は既に {'role': ..., 'parts': [...]} の形式になっているはず
    for item in state['chat_history']:
        messages.append({'role': item['role'], 'parts': item['parts']})
    messages.append({'role': 'user', 'parts': [prompt_context]})

    generated_text = ""
    try:
        response = response_model.generate_content(messages)

        # より安全な応答テキストの取得
        if response.candidates:
            first_candidate = response.candidates[0]
            if first_candidate.content and first_candidate.content.parts:
                generated_text = "".join(part.text for part in first_candidate.content.parts if hasattr(part, 'text'))
            elif first_candidate.finish_reason != "SAFETY": # 安全性以外での終了理由でpartsがない場合
                 generated_text = f"[応答取得エラー: 応答パーツが空です。終了理由: {first_candidate.finish_reason}]"
            else: # 安全性によるブロックなど
                generated_text = f"[応答ブロック: 安全性設定により応答がブロックされました。詳細: {response.prompt_feedback if response.prompt_feedback else 'N/A'}]"

        if not generated_text and response.prompt_feedback:
            generated_text = f"[応答なし: プロンプトフィードバックあり: {response.prompt_feedback}]"
        elif not generated_text:
            generated_text = "[応答なし: 不明な理由]"

    except Exception as e:
        print(f"  - 応答生成中にエラー: {e}")
        error_message = f"[エラー: 応答生成中に問題が発生しました。詳細: {e}]"
        # 'response' 変数がこのスコープで定義されているか確認
        if 'response' in locals() and hasattr(response, 'prompt_feedback') and response.prompt_feedback:
             error_message += f"\nプロンプトフィードバック: {response.prompt_feedback}"
        return {"final_response": error_message}

    print(f"  - 生成された応答： {generated_text[:100]}...")
    return {"final_response": generated_text}


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
