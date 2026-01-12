
import chess

class ChessGame:
    def __init__(self):
        self.board = chess.Board()
        # Track illegal move attempts so the persona can teach the user
        self.illegal_attempts = []  # List of {"from": "a1", "to": "a8", "reason": "..."}

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
            # Clear illegal attempts on successful move (optional: keep history)
            # self.illegal_attempts = []
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
    
    def get_illegal_attempts(self) -> list:
        """Get the list of recent illegal move attempts."""
        return self.illegal_attempts
    
    def clear_illegal_attempts(self):
        """Clear the illegal attempts history."""
        self.illegal_attempts = []

    def get_fen(self) -> str:
        """Returns the current board state in FEN format."""
        return self.board.fen()

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

# Singleton instance for simple state management in this demo context
# In a multi-user environment, this would need to be session-scoped.
game_instance = ChessGame()
