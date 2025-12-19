# topic_cluster_manager.py
# 話題クラスタリング記憶システムの中核モジュール

import os
import json
import time
import datetime
import traceback
import numpy as np
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import logging

import constants
import config_manager

logger = logging.getLogger(__name__)

# --- エンベディングモデルの抽象化 ---

class EmbeddingProvider:
    """エンベディング生成のための抽象基底クラス"""
    
    def embed_documents(self, texts: List[str]) -> np.ndarray:
        raise NotImplementedError
    
    def embed_query(self, text: str) -> np.ndarray:
        raise NotImplementedError


class GeminiEmbeddingProvider(EmbeddingProvider):
    """Gemini API を使用したエンベディング生成"""
    
    def __init__(self, api_key: str):
        from langchain_google_genai import GoogleGenerativeAIEmbeddings
        self.embeddings = GoogleGenerativeAIEmbeddings(
            model=constants.EMBEDDING_MODEL,
            google_api_key=api_key,
            task_type="retrieval_document"
        )
        self.query_embeddings = GoogleGenerativeAIEmbeddings(
            model=constants.EMBEDDING_MODEL,
            google_api_key=api_key,
            task_type="retrieval_query"
        )
    
    def embed_documents(self, texts: List[str]) -> np.ndarray:
        embeddings = self.embeddings.embed_documents(texts)
        return np.array(embeddings)
    
    def embed_query(self, text: str) -> np.ndarray:
        embedding = self.query_embeddings.embed_query(text)
        return np.array(embedding)


class LocalEmbeddingProvider(EmbeddingProvider):
    """sentence-transformers を使用したローカルエンベディング生成"""
    
    MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
    
    def __init__(self):
        try:
            from sentence_transformers import SentenceTransformer
            print(f"[TopicCluster] ローカルエンベディングモデルをロード中: {self.MODEL_NAME}")
            self.model = SentenceTransformer(self.MODEL_NAME)
            print(f"[TopicCluster] モデルロード完了")
        except ImportError:
            raise ImportError(
                "sentence-transformers がインストールされていません。\n"
                "pip install sentence-transformers でインストールしてください。"
            )
    
    def embed_documents(self, texts: List[str]) -> np.ndarray:
        return self.model.encode(texts, convert_to_numpy=True)
    
    def embed_query(self, text: str) -> np.ndarray:
        return self.model.encode([text], convert_to_numpy=True)[0]


def get_embedding_provider(api_key: str, mode: str = "api") -> EmbeddingProvider:
    """
    設定に基づいてエンベディングプロバイダーを取得
    
    Args:
        api_key: Gemini APIキー（mode="api"の場合に使用）
        mode: "api" または "local"
    """
    if mode == "local":
        return LocalEmbeddingProvider()
    else:
        return GeminiEmbeddingProvider(api_key)


# --- メインクラス ---

class TopicClusterManager:
    """
    話題クラスタ管理クラス
    
    エピソード記憶を話題ごとにクラスタリングし、
    想起時に関連する話題クラスタを検索する機能を提供する。
    """
    
    # クラスタリングのパラメータ
    MIN_CLUSTER_SIZE = 3      # 最小クラスタサイズ
    MIN_SAMPLES = 2           # HDBSCANのmin_samples
    
    def __init__(self, room_name: str, api_key: str):
        self.room_name = room_name
        self.api_key = api_key
        self.room_dir = Path(constants.ROOMS_DIR) / room_name
        self.memory_dir = self.room_dir / "memory"
        self.clusters_file = self.memory_dir / "topic_clusters.json"
        self.episodic_file = self.memory_dir / "episodic_memory.json"
        
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        
        # エンベディングモードを設定から取得
        effective_settings = config_manager.get_effective_settings(room_name)
        self.embedding_mode = effective_settings.get("embedding_mode", "api")
        
        self._embedding_provider: Optional[EmbeddingProvider] = None
    
    def _get_embedding_provider(self) -> EmbeddingProvider:
        """遅延初期化されたエンベディングプロバイダーを取得"""
        if self._embedding_provider is None:
            self._embedding_provider = get_embedding_provider(
                self.api_key, 
                self.embedding_mode
            )
        return self._embedding_provider
    
    def _load_clusters(self) -> Dict:
        """クラスタ情報をファイルから読み込む"""
        if self.clusters_file.exists():
            try:
                with open(self.clusters_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except json.JSONDecodeError:
                return {"version": "1.0", "clusters": [], "last_updated": None}
        return {"version": "1.0", "clusters": [], "last_updated": None}
    
    def _save_clusters(self, data: Dict):
        """クラスタ情報をファイルに保存"""
        data["last_updated"] = datetime.datetime.now().isoformat()
        with open(self.clusters_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def _load_episodes(self) -> List[Dict]:
        """エピソード記憶を読み込む"""
        if self.episodic_file.exists():
            try:
                with open(self.episodic_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except json.JSONDecodeError:
                return []
        return []
    
    def run_clustering(self) -> str:
        """
        クラスタリング処理のメインエントリポイント
        
        Returns:
            処理結果のメッセージ
        """
        print(f"--- [TopicCluster] {self.room_name} のクラスタリングを開始 ---")
        
        # 1. エピソード記憶を読み込み
        episodes = self._load_episodes()
        if len(episodes) < self.MIN_CLUSTER_SIZE:
            msg = f"エピソード記憶が少なすぎます（{len(episodes)}件）。最低{self.MIN_CLUSTER_SIZE}件必要です。"
            print(f"  - [TopicCluster] {msg}")
            return msg
        
        # 2. 未クラスタリングのエピソードを抽出
        # 全エピソードを対象にベクトル化（差分更新は将来実装）
        episode_texts = []
        episode_dates = []
        for ep in episodes:
            summary = ep.get("summary", "")
            date = ep.get("date", "unknown")
            if summary:
                episode_texts.append(f"日付: {date}\n{summary}")
                episode_dates.append(date)
        
        if len(episode_texts) < self.MIN_CLUSTER_SIZE:
            msg = f"有効なエピソードが少なすぎます（{len(episode_texts)}件）"
            print(f"  - [TopicCluster] {msg}")
            return msg
        
        print(f"  - [TopicCluster] {len(episode_texts)}件のエピソードをベクトル化中... (Mode: {self.embedding_mode})")
        
        # 3. ベクトル化
        try:
            provider = self._get_embedding_provider()
            embeddings = provider.embed_documents(episode_texts)
            print(f"  - [TopicCluster] ベクトル化完了: shape={embeddings.shape}")
        except Exception as e:
            msg = f"ベクトル化エラー: {e}"
            print(f"  - [TopicCluster] {msg}")
            traceback.print_exc()
            return msg
        
        # 4. クラスタリング（HDBSCAN）
        try:
            import hdbscan
            clusterer = hdbscan.HDBSCAN(
                min_cluster_size=self.MIN_CLUSTER_SIZE,
                min_samples=self.MIN_SAMPLES,
                metric='euclidean'
            )
            labels = clusterer.fit_predict(embeddings)
            unique_labels = set(labels)
            n_clusters = len([l for l in unique_labels if l >= 0])
            n_noise = len([l for l in labels if l == -1])
            
            print(f"  - [TopicCluster] クラスタリング完了: {n_clusters}クラスタ, {n_noise}件はノイズ")
        except ImportError:
            msg = "hdbscanがインストールされていません。pip install hdbscan でインストールしてください。"
            print(f"  - [TopicCluster] {msg}")
            return msg
        except Exception as e:
            msg = f"クラスタリングエラー: {e}"
            print(f"  - [TopicCluster] {msg}")
            traceback.print_exc()
            return msg
        
        # 5. クラスタ情報を構築
        clusters_data = {"version": "1.0", "clusters": []}
        
        for cluster_id in sorted([l for l in unique_labels if l >= 0]):
            # このクラスタに属するエピソードのインデックス
            cluster_indices = [i for i, l in enumerate(labels) if l == cluster_id]
            cluster_episode_dates = [episode_dates[i] for i in cluster_indices]
            cluster_embeddings = embeddings[cluster_indices]
            
            # クラスタの重心を計算
            centroid = np.mean(cluster_embeddings, axis=0)
            
            # このクラスタのテキストを抽出（ラベル生成用）
            cluster_texts = [episode_texts[i] for i in cluster_indices]
            
            cluster_info = {
                "cluster_id": f"cluster_{cluster_id:03d}",
                "auto_label": None,  # 後でAIが生成
                "persona_label": None,
                "centroid_embedding": centroid.tolist(),
                "episode_dates": cluster_episode_dates,
                "episode_count": len(cluster_indices),
                "summary": None,  # 後でAIが生成
                "created_at": datetime.datetime.now().isoformat()
            }
            clusters_data["clusters"].append(cluster_info)
        
        # 6. 各クラスタのラベルと要約を生成
        print(f"  - [TopicCluster] クラスタラベルを生成中...")
        clusters_data = self._generate_cluster_labels(clusters_data, episode_texts, labels)
        
        # 7. 保存
        self._save_clusters(clusters_data)
        
        msg = f"{n_clusters}個の話題クラスタを作成しました"
        print(f"--- [TopicCluster] 完了: {msg} ---")
        return msg
    
    def _generate_cluster_labels(self, clusters_data: Dict, episode_texts: List[str], labels: np.ndarray) -> Dict:
        """
        各クラスタにラベルと要約を生成する
        
        AIを使用して各クラスタの代表的なテーマを抽出
        """
        from gemini_api import get_configured_llm
        effective_settings = config_manager.get_effective_settings(self.room_name)
        
        try:
            llm = get_configured_llm(constants.INTERNAL_PROCESSING_MODEL, self.api_key, effective_settings)
        except Exception as e:
            print(f"    ! ラベル生成用LLMの初期化エラー: {e}")
            return clusters_data
        
        for cluster_info in clusters_data["clusters"]:
            cluster_id_num = int(cluster_info["cluster_id"].split("_")[1])
            cluster_indices = [i for i, l in enumerate(labels) if l == cluster_id_num]
            cluster_texts = [episode_texts[i] for i in cluster_indices[:5]]  # 最大5件
            
            combined_text = "\n---\n".join(cluster_texts)
            
            prompt = f"""以下は同じ話題に関連する会話エピソードです。
このグループに共通するテーマを分析し、以下の形式で出力してください。

【エピソード群】
{combined_text}

【出力形式】
ラベル: （話題を表す短いフレーズ、5-15文字程度）
要約: （この話題群の概要、1-2文）"""
            
            try:
                response = llm.invoke(prompt).content.strip()
                
                # パース
                lines = response.split("\n")
                for line in lines:
                    if line.startswith("ラベル:") or line.startswith("ラベル："):
                        cluster_info["auto_label"] = line.split(":", 1)[1].strip() if ":" in line else line.split("：", 1)[1].strip()
                    elif line.startswith("要約:") or line.startswith("要約："):
                        cluster_info["summary"] = line.split(":", 1)[1].strip() if ":" in line else line.split("：", 1)[1].strip()
                
                # フォールバック
                if not cluster_info["auto_label"]:
                    cluster_info["auto_label"] = f"話題グループ {cluster_id_num + 1}"
                if not cluster_info["summary"]:
                    cluster_info["summary"] = f"{len(cluster_indices)}件のエピソードを含むクラスタ"
                
                print(f"    ✅ {cluster_info['cluster_id']}: {cluster_info['auto_label']}")
                
                # API制限回避
                time.sleep(1)
                
            except Exception as e:
                print(f"    ! {cluster_info['cluster_id']} のラベル生成エラー: {e}")
                cluster_info["auto_label"] = f"話題グループ {cluster_id_num + 1}"
                cluster_info["summary"] = f"{len(cluster_indices)}件のエピソードを含むクラスタ"
        
        return clusters_data
    
    def get_relevant_clusters(self, query: str, top_k: int = 2) -> List[Dict]:
        """
        クエリに関連するクラスタを検索
        
        Args:
            query: 検索クエリ
            top_k: 返すクラスタの最大数
            
        Returns:
            関連クラスタのリスト（スコア順）
        """
        clusters_data = self._load_clusters()
        if not clusters_data["clusters"]:
            return []
        
        try:
            provider = self._get_embedding_provider()
            query_embedding = provider.embed_query(query)
        except Exception as e:
            print(f"[TopicCluster] クエリベクトル化エラー: {e}")
            return []
        
        # 各クラスタとの類似度を計算
        results = []
        for cluster in clusters_data["clusters"]:
            centroid = np.array(cluster["centroid_embedding"])
            
            # コサイン類似度
            similarity = np.dot(query_embedding, centroid) / (
                np.linalg.norm(query_embedding) * np.linalg.norm(centroid) + 1e-10
            )
            
            results.append({
                "cluster_id": cluster["cluster_id"],
                "label": cluster.get("persona_label") or cluster.get("auto_label") or "不明",
                "summary": cluster.get("summary", ""),
                "episode_count": cluster.get("episode_count", 0),
                "episode_dates": cluster.get("episode_dates", []),
                "similarity": float(similarity)
            })
        
        # 類似度でソートして上位を返す
        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results[:top_k]
    
    def get_cluster_context_for_prompt(self, query: str, top_k: int = 2) -> str:
        """
        プロンプト注入用：関連クラスタの要約をテキスト化
        
        Args:
            query: 検索クエリ
            top_k: 使用するクラスタの最大数
            
        Returns:
            プロンプトに挿入するテキスト
        """
        relevant = self.get_relevant_clusters(query, top_k)
        if not relevant:
            return ""
        
        parts = []
        for cluster in relevant:
            if cluster["similarity"] < 0.3:  # 類似度が低すぎるものは除外
                continue
            
            label = cluster["label"]
            summary = cluster["summary"]
            dates = cluster["episode_dates"]
            date_range = f"{min(dates)} 〜 {max(dates)}" if dates else "不明"
            
            parts.append(f"【{label}】（{date_range}）\n{summary}")
        
        if not parts:
            return ""
        
        return "▼ 関連する話題の記憶 ▼\n" + "\n\n".join(parts)
    
    def set_persona_label(self, cluster_id: str, label: str) -> bool:
        """
        ペルソナによるクラスタ愛称を設定
        
        Args:
            cluster_id: クラスタID
            label: ペルソナが付けた愛称
            
        Returns:
            成功したかどうか
        """
        clusters_data = self._load_clusters()
        
        for cluster in clusters_data["clusters"]:
            if cluster["cluster_id"] == cluster_id:
                cluster["persona_label"] = label
                self._save_clusters(clusters_data)
                return True
        
        return False
    
    def get_all_clusters(self) -> List[Dict]:
        """全クラスタの情報を取得（UI表示用）"""
        clusters_data = self._load_clusters()
        return clusters_data.get("clusters", [])
