import pandas as pd
import sys

def mock_handle_watchlist_delete(room_name, selected_row):
    print(f"Delete called for room: {room_name}")
    print(f"Selected row: {selected_row}")
    return "UI_UPDATE", "Success"

def test_delete_logic(df_data, selected_id):
    print(f"\nTesting with type: {type(df_data)}")
    # The logic from nexus_ark.py
    selected_row = None
    if df_data is not None:
        # Check if it behaves like a DataFrame (has truth value ambiguity)
        try:
            bool_val = bool(df_data)
            print(f"Truth value check: {bool_val}")
        except ValueError as e:
            print(f"Caught expected ValueError in direct truth check: {e}")

        # Improved logic
        if isinstance(df_data, pd.DataFrame):
            print("Processing as DataFrame")
            for _, row in df_data.iterrows():
                if str(row.iloc[0]) == selected_id:
                    selected_row = row.tolist()
                    break
        elif isinstance(df_data, list):
            print("Processing as List")
            for row in df_data:
                if str(row[0]) == selected_id:
                    selected_row = row
                    break
    
    return mock_handle_watchlist_delete("test_room", selected_row)

# Test cases
data = [
    ["id1", "Name1", "url1", "daily", "never", True, "grp1"],
    ["id2", "Name2", "url2", "manual", "never", True, "grp2"]
]

print("--- Case 1: List Input ---")
test_delete_logic(data, "id2")

print("\n--- Case 2: DataFrame Input ---")
df = pd.DataFrame(data, columns=["ID", "Name", "URL", "Freq", "Last", "Enabled", "Group"])
test_delete_logic(df, "id2")

print("\n--- Case 3: None Input ---")
test_delete_logic(None, "id2")
