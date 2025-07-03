import google.genai as genai
from typing import List, TypedDict, Optional
from PIL import Image
import io
import traceback # print_exc() のために追加
import rag_manager # rag_managerをインポート

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
    知覚された内容に基づき、FAISSから関連性の高い記憶の断片を検索するノード。
    """
    print("--- 記憶想起ノード (RAG) 実行 ---")

    # ★★★ Stateから直接キャラクター名を取得する ★★★
    character_name = state['character_name']
    query_text = state['perceived_content'] # 知覚結果をクエリとして使用

    # character_nameがNoneや空文字の場合の考慮を追加（基本的には渡されるはずだが念のため）
    if not character_name:
        print("  -警告: RAG検索ノードでcharacter_nameが取得できませんでした。\"Default\"を使用します。")
        character_name = "Default"

    try:
        # rag_managerの関数を呼び出す
        relevant_chunks = rag_manager.search_relevant_chunks(
            character_name=character_name,
            query_text=query_text,
            top_k=3 # 取得するチャンク数（調整可能）
        )

        if relevant_chunks:
            rag_results_text = "\n---\n".join(relevant_chunks)
            print(f"  - {len(relevant_chunks)}件の関連記憶を発見。")
            return {"rag_results": rag_results_text}
        else:
            print("  - 関連する記憶は見つかりませんでした。")
            return {"rag_results": None} # 何も見つからなかった場合はNoneを返す

    except Exception as e:
        print(f"  - RAG検索中にエラー: {e}")
        traceback.print_exc()
        return {"rag_results": "[エラー：記憶の検索中に問題が発生しました]"}

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

        rag_info = state.get('rag_results') # StateからRAG結果を取得
        if rag_info:
            # RAG結果が存在する場合、プロンプトに情報を追加
            final_user_prompt += f"\n\n# 参照した記憶の断片:\n---\n{rag_info}\n---"

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
workflow.add_node("rag_search", rag_search_node) # ★新しいRAGノードを追加
workflow.add_node("generate", generate_response_node)

# グラフの実行順序を定義
workflow.set_entry_point("perceive")
workflow.add_edge("perceive", "rag_search")   # 知覚 → RAG検索
workflow.add_edge("rag_search", "generate") # RAG検索 → 応答生成
workflow.add_edge("generate", END)

# グラフをコンパイル
app = workflow.compile()
