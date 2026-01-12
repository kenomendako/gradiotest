
import chess
import json
import os
from pathlib import Path

# Get constants for ROOMS_DIR
try:
    import constants
    ROOMS_DIR = constants.ROOMS_DIR
except ImportError:
    ROOMS_DIR = "rooms"

class ChessGame:
    def __init__(self):
        self.board = chess.Board()
        self.room_name = None  # Current room for persistence
        # Track illegal move attempts so the persona can teach the user
        self.illegal_attempts = []  # List of {"from": "a1", "to": "a8", "reason": "..."}

    def set_room(self, room_name: str):
        """Set the current room and load saved game state if exists."""
        if self.room_name == room_name:
            return  # Already set to this room
        self.room_name = room_name
        self.load_state()
    
    def _get_state_path(self) -> Path:
        """Get the path to the chess state file for the current room."""
        if not self.room_name:
            return None
        return Path(ROOMS_DIR) / self.room_name / "chess_state.json"
    
    def save_state(self):
        """Save the current game state to the room's chess_state.json file."""
        state_path = self._get_state_path()
        if not state_path:
            return False
        
        try:
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state = {
                "fen": self.board.fen(),
                "illegal_attempts": self.illegal_attempts[-5:] if self.illegal_attempts else []
            }
            with open(state_path, 'w', encoding='utf-8') as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
            print(f"  - [Chess] State saved to {state_path}")
            return True
        except Exception as e:
            print(f"  - [Chess] Failed to save state: {e}")
            return False
    
    def load_state(self):
        """Load game state from the room's chess_state.json file if it exists."""
        state_path = self._get_state_path()
        if not state_path or not state_path.exists():
            # No saved state - keep current board state (don't reset)
            # This preserves moves made before file was created
            print(f"  - [Chess] No saved state found, keeping current board")
            return False
        
        try:
            with open(state_path, 'r', encoding='utf-8') as f:
                state = json.load(f)
            
            fen = state.get("fen")
            if fen:
                self.board.set_fen(fen)
                print(f"  - [Chess] Loaded state from {state_path}: {fen[:30]}...")
            
            self.illegal_attempts = state.get("illegal_attempts", [])
            return True
        except Exception as e:
            print(f"  - [Chess] Failed to load state: {e}")
            self.board.reset()
            self.illegal_attempts = []
            return False

    def make_move(self, move_str: str):
        """
        Attempts to make a move on the board.
        Accepts moves in SAN (Standard Algebraic Notation) or UCI (Universal Chess Interface) format.
        Examples: "e4", "Nf3", "e2e4".
        Returns True if successful, raises ValueError if illegal or invalid.
        """
        try:
            # Try to parse as SAN first (e.g., "e4", "Nf3")
            move = self.board.parse_san(move_str)
        except ValueError:
            try:
                # Try to parse as UCI (e.g., "e2e4")
                move = chess.Move.from_uci(move_str)
            except ValueError:
                raise ValueError(f"Invalid move format: {move_str}")

        if move in self.board.legal_moves:
            self.board.push(move)
            # Auto-save after each successful move
            self.save_state()
            return True
        else:
            raise ValueError(f"Illegal move: {move_str}")

    def record_illegal_attempt(self, from_sq: str, to_sq: str, reason: str):
        """Record an illegal move attempt for the persona to see."""
        self.illegal_attempts.append({
            "from": from_sq,
            "to": to_sq,
            "reason": reason
        })
        # Keep only the last 5 attempts to avoid clutter
        if len(self.illegal_attempts) > 5:
            self.illegal_attempts = self.illegal_attempts[-5:]
        # Save state with illegal attempts
        self.save_state()
    
    def get_illegal_attempts(self) -> list:
        """Get the list of recent illegal move attempts."""
        return self.illegal_attempts
    
    def clear_illegal_attempts(self):
        """Clear the illegal attempts history."""
        self.illegal_attempts = []
        self.save_state()

    def get_fen(self) -> str:
        """Returns the current board state in FEN format."""
        return self.board.fen()
    
    def set_position(self, fen: str):
        """Set the board position from a FEN string."""
        self.board.set_fen(fen)
        self.save_state()

    def get_legal_moves(self) -> list[str]:
        """Returns a list of all legal moves in SAN format."""
        return [self.board.san(move) for move in self.board.legal_moves]

    def is_game_over(self) -> bool:
        return self.board.is_game_over()

    def get_outcome(self) -> str:
        if not self.is_game_over():
            return "Game in progress"
        outcome = self.board.outcome()
        if outcome:
            return f"Game Over: {outcome.result()} ({outcome.termination.name})"
        return "Game Over"

    def reset_board(self):
        """Resets the board to the starting position."""
        self.board.reset()
        self.illegal_attempts = []
        self.save_state()

# Singleton instance for simple state management in this demo context
# In a multi-user environment, this would need to be session-scoped.
game_instance = ChessGame()
