
import sys
import os

# Ensure we can import from the project root
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from game.chess_engine import game_instance
from tools.chess_tools import read_board_state, perform_move, get_legal_moves, reset_game

def test_chess_flow():
    print("--- Testing Chess Flow ---")
    
    # 1. Check Initial State
    print("1. Initial State:")
    print(read_board_state())
    assert "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR" in read_board_state()
    
    # 2. Make a Move via Tool
    print("\n2. Making Move 'e4'...")
    result = perform_move("e4")
    print(result)
    assert "Move 'e4' executed successfully" in result
    
    # 3. Check State Update
    state = read_board_state()
    print(f"\n3. New State: {state}")
    assert "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR" in state
    
    # 4. Check Legal Moves
    legal = get_legal_moves()
    print(f"\n4. Legal Moves: {legal[:50]}...") # Truncate for display
    assert "e5" in legal or "c5" in legal # Black's moves
    
    # 5. Reset
    print("\n5. Resetting Game...")
    reset_game()
    final_state = read_board_state()
    print(f"Final State: {final_state}")
    assert "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR" in final_state
    
    print("\n✅ Verification Successful!")

if __name__ == "__main__":
    test_chess_flow()
