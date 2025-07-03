import google.genai as genai
from typing import List, TypedDict, Optional
from PIL import Image
import io
import traceback # print_exc() のために追加

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
        # final_user_prompt = state['perceived_content']
        # if state.get('rag_results'):
        #    final_user_prompt += f"\n\n# 参考情報:\n{state['rag_results']}"
        # contents_for_generation.append({'role': 'user', 'parts': [{'text': final_user_prompt}]})

        current_user_turn_content = state['perceived_content']
        if not current_user_turn_content.strip(): # 知覚結果が空やスペースのみの場合
            current_user_turn_content = "[ユーザーは何も入力しませんでした]"

        contents_for_generation.append({'role': 'user', 'parts': [{'text': current_user_turn_content}]})

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

workflow.add_node("perceive", perceive_input_node)
workflow.add_node("generate", generate_response_node)

workflow.set_entry_point("perceive")
workflow.add_edge("perceive", "generate")
workflow.add_edge("generate", END)

# グラフをコンパイル
app = workflow.compile()
