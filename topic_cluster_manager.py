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
        
        # [v25] クラスタリングパラメータを設定から取得（デフォルト値はクラス定数）
        self.min_cluster_size = effective_settings.get("topic_cluster_min_size", self.MIN_CLUSTER_SIZE)
        self.min_samples = effective_settings.get("topic_cluster_min_samples", self.MIN_SAMPLES)
        self.cluster_selection_method = effective_settings.get("topic_cluster_selection_method", "eom")
        self.fixed_topics = effective_settings.get("topic_cluster_fixed_topics", [])
        
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
        if len(episodes) < self.min_cluster_size:
            msg = f"エピソード記憶が少なすぎます（{len(episodes)}件）。最低{self.min_cluster_size}件必要です。"
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
        
        if len(episode_texts) < self.min_cluster_size:
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
        
        # [Phase 2] ハイブリッド分類ロジック
        clusters_data = {"version": "1.0", "clusters": []}
        fixed_cluster_count = 0
        
        unassigned_indices = list(range(len(episode_texts)))
        
        # 固定トピックへの分類
        if self.fixed_topics:
            print(f"  - [TopicCluster] 固定トピックへの分類を実行中: {self.fixed_topics}")
            try:
                # 固定トピックをベクトル化
                topic_embeddings = provider.embed_documents(self.fixed_topics)
                
                # トピックごとのバケツを用意
                topic_buckets = {i: [] for i in range(len(self.fixed_topics))} # topic_index -> List[episode_index]
                
                # 未割り当てインデックスを更新するためのリスト
                remaining_indices = []
                
                # 各エピソードとトピックの類似度判定
                SIMILARITY_THRESHOLD = 0.6 # 閾値
                
                for idx in unassigned_indices:
                    ep_embedding = embeddings[idx]
                    
                    # 各トピックとの類似度を計算
                    similarities = np.dot(topic_embeddings, ep_embedding) / (
                        np.linalg.norm(topic_embeddings, axis=1) * np.linalg.norm(ep_embedding) + 1e-10
                    )
                    
                    best_match_idx = np.argmax(similarities)
                    max_sim = similarities[best_match_idx]
                    
                    if max_sim >= SIMILARITY_THRESHOLD:
                        topic_buckets[best_match_idx].append(idx)
                    else:
                        remaining_indices.append(idx)
                
                unassigned_indices = remaining_indices
                
                # 固定トピッククラスタを作成
                for i, topic_name in enumerate(self.fixed_topics):
                    indices = topic_buckets[i]
                    if indices:
                        cluster_episode_dates = [episode_dates[idx] for idx in indices]
                        cluster_embeddings = embeddings[indices]
                        centroid = np.mean(cluster_embeddings, axis=0)
                        
                        cluster_info = {
                            "cluster_id": f"cluster_fixed_{i:02d}",
                            "auto_label": topic_name, # 固定名はそのままラベルに
                            "persona_label": None,
                            "centroid_embedding": centroid.tolist(),
                            "episode_dates": cluster_episode_dates,
                            "episode_count": len(indices),
                            "summary": f"{topic_name} に関するエピソードグループ", # 簡易要約
                            "created_at": datetime.datetime.now().isoformat(),
                            "is_fixed": True, # 固定トピックフラグ
                            "episode_indices": indices # [一時的] ラベル生成用
                        }
                        clusters_data["clusters"].append(cluster_info)
                        fixed_cluster_count += 1
                        
                print(f"  - [TopicCluster] 固定トピック分類完了: {fixed_cluster_count}クラスタ ({len(episode_texts) - len(unassigned_indices)}件分類済み)")
                
            except Exception as e:
                print(f"  - [TopicCluster] 固定トピック分類エラー (スキップ): {e}")
                traceback.print_exc()

        # 残りのエピソードでHDBSCAN (自動クラスタリング)
        if len(unassigned_indices) >= self.min_cluster_size:
            # 部分ベクトル抽出
            partial_embeddings = embeddings[unassigned_indices]
            
            # 4. クラスタリング（HDBSCAN）
            try:
                import hdbscan
                print(f"  - [TopicCluster] HDBSCAN実行中 (対象: {len(unassigned_indices)}件, min_cluster_size={self.min_cluster_size}, min_samples={self.min_samples}, method={self.cluster_selection_method})")
                clusterer = hdbscan.HDBSCAN(
                    min_cluster_size=self.min_cluster_size,
                    min_samples=self.min_samples,
                    cluster_selection_method=self.cluster_selection_method,
                    metric='euclidean'
                )
                labels = clusterer.fit_predict(partial_embeddings)
                unique_labels = set(labels)
                n_clusters = len([l for l in unique_labels if l >= 0])
                n_noise = len([l for l in labels if l == -1])
                
                print(f"  - [TopicCluster] 自動クラスタリング完了: {n_clusters}クラスタ, {n_noise}件はノイズ")
                
                # 自動クラスタ情報を追加
                # 既存のクラスタIDと衝突しないようにオフセット
                id_offset = fixed_cluster_count 
                
                for cluster_id in sorted([l for l in unique_labels if l >= 0]):
                    # label上のインデックスは partial_embeddings に対するもの。
                    # 元の episode_texts に対するインデックスに変換が必要
                    # labels[local_idx] == cluster_id なる local_idx を探し、
                    # unassigned_indices[local_idx] で元の index を得る
                    
                    local_indices = [i for i, l in enumerate(labels) if l == cluster_id]
                    original_indices = [unassigned_indices[i] for i in local_indices]
                    
                    cluster_episode_dates = [episode_dates[i] for i in original_indices]
                    cluster_embeddings_subset = embeddings[original_indices]
                    
                    # クラスタの重心を計算
                    centroid = np.mean(cluster_embeddings_subset, axis=0)
                    
                    cluster_info = {
                        "cluster_id": f"cluster_{id_offset + cluster_id:03d}",
                        "auto_label": None,  # 後でAIが生成
                        "persona_label": None,
                        "centroid_embedding": centroid.tolist(),
                        "episode_dates": cluster_episode_dates,
                        "episode_count": len(original_indices),
                        "summary": None,  # 後でAIが生成
                        "created_at": datetime.datetime.now().isoformat(),
                        "is_fixed": False,
                        "episode_indices": original_indices # [一時的] ラベル生成用
                    }
                    clusters_data["clusters"].append(cluster_info)
                    
            except ImportError:
                msg = "hdbscanがインストールされていません。pip install hdbscan でインストールしてください。"
                print(f"  - [TopicCluster] {msg}")
                # ここでリターンせず、固定トピック分だけでも保存するなら続行すべきだが、
                # 一旦エラーメッセージを出して終了する（従来通り）
                return msg
            except Exception as e:
                msg = f"クラスタリングエラー: {e}"
                print(f"  - [TopicCluster] {msg}")
                traceback.print_exc()
                return msg
        else:
             print(f"  - [TopicCluster] 残存エピソードが少なすぎるため自動クラスタリングはスキップ ({len(unassigned_indices)} < {self.min_cluster_size})")

        # 6. 自動クラスタのラベルと要約を生成 (is_fixed=Falseのものだけ)
        # ラベル生成ロジック側でインデックス参照が必要なので、ここでの呼び出し方を少し変えるか、
        # _generate_cluster_labels を改修する必要がある。
        # 現在の _generate_cluster_labels は labels 配列と全テキストを渡す前提になっている。
        # しかしここでは「固定トピック割り当て済み」と「HDBSCAN結果」が混ざっている。
        
        # 解決策: _generate_cluster_labels は clusters_data を元に処理するように変更するのが最もクリーン。
        # episode_texts全体と、各クラスタが保持する(保持してない！) テキスト情報が必要。
        # -> クラスタ情報内にテキストインデックスかテキストそのものを持たせるのが良さそうだが、
        # 容量節約のためテキストは持っていない。
        # しかし _generate_cluster_labels は labels (numpy array) を使ってインデックスを逆引きしている。
        # 今回のハイブリッド化で labels 配列一つで全エピソードを表現できなくなった（固定割当があるため）。
        
        # よって、cluster_info に一時的に `episode_indices` を持たせて、ラベル生成後に削除する方式に修正する。
        # 上記のコードブロック内で episode_indices を追加する必要がある。
        
        # 修正: 上記ループ内で `episode_indices` を追加する。

        
        # 6. 各クラスタのラベルと要約を生成
        print(f"  - [TopicCluster] クラスタラベルを生成中...")
        clusters_data = self._generate_cluster_labels(clusters_data, episode_texts)
        
        # 7. 保存
        self._save_clusters(clusters_data)
        
        total_clusters = len(clusters_data["clusters"])
        msg = f"{total_clusters}個の話題クラスタを作成しました"
        print(f"--- [TopicCluster] 完了: {msg} ---")
        return msg
    
    def _generate_cluster_labels(self, clusters_data: Dict, episode_texts: List[str]) -> Dict:
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
            # 固定トピックかつ既にラベルがある場合はスキップも可能だが、要約生成のためにAIには通す
            # ただしラベルは固定名を変えないようにする
            
            cluster_indices = cluster_info.get("episode_indices", [])
            cluster_texts = [episode_texts[i] for i in cluster_indices[:5]]  # 最大5件
            
            # 使用済みインデックスは削除（保存ファイルに含めない）
            if "episode_indices" in cluster_info:
                del cluster_info["episode_indices"]
            
            if not cluster_texts:
                continue

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
                        if not cluster_info.get("is_fixed"):
                            cluster_info["auto_label"] = line.split(":", 1)[1].strip() if ":" in line else line.split("：", 1)[1].strip()
                    elif line.startswith("要約:") or line.startswith("要約："):
                        cluster_info["summary"] = line.split(":", 1)[1].strip() if ":" in line else line.split("：", 1)[1].strip()
                
                # フォールバック
                if not cluster_info["auto_label"]:
                    cluster_info["auto_label"] = f"話題グループ {cluster_info['cluster_id']}"
                if not cluster_info["summary"]:
                    cluster_info["summary"] = f"{len(cluster_indices)}件のエピソードを含むクラスタ"
                
                print(f"    ✅ {cluster_info['cluster_id']}: {cluster_info['auto_label']}")
                
                # API制限回避
                time.sleep(1)
                
            except Exception as e:
                print(f"    ! {cluster_info['cluster_id']} のラベル生成エラー: {e}")
                if not cluster_info.get("auto_label"):
                    cluster_info["auto_label"] = f"話題グループ {cluster_info['cluster_id']}"
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
