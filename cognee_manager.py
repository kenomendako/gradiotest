# cognee_manager.py (新規作成)
import os

# このファイルがインポートされた時点で、Cogneeが使用する環境変数が設定されます。

# 1. Cogneeのデータ保存先を一元管理するベースパスを定義
COGNEE_DATA_PATH = os.path.abspath(os.path.join("cognee_data"))
os.makedirs(COGNEE_DATA_PATH, exist_ok=True)

# 2. LanceDB (ベクトルDB) の設定
LANCEDB_PATH = os.path.join(COGNEE_DATA_PATH, "vector_storage")
os.environ["VECTOR_DB_PROVIDER"] = "lancedb"
os.environ["VECTOR_DB_PATH"] = LANCEDB_PATH

# 3. DuckDB (グラフDB/リレーショナルストレージ) の設定
DUCKDB_PATH = os.path.join(COGNEE_DATA_PATH, "relational_storage.db")
os.environ["DUCKDB_PATH"] = DUCKDB_PATH

print("--- Cognee 環境変数を設定しました ---")
print(f"  - Vector DB Path: {LANCEDB_PATH}")
print(f"  - DuckDB Path: {DUCKDB_PATH}")

# Cogneeの機能（データ追加や検索）は、今後このマネージャー内の関数として実装していきます。
# フェーズ1では、このファイルの作成までとします。
