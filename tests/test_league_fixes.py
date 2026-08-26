"""Tests for league.leaderboard aggregating anonymous parallel runs."""
import unittest

from agent_hub import league


class LeaderboardParallelTest(unittest.TestCase):
    def test_parallel_run_included(self):
        runs = [{
            "recipe": "parallel",
            "status": "done",
            "state": {
                "category": "algorithm",
                "results": {
                    "alice": {"avg": 8.0, "n": 2, "best": 1, "adopted": True, "time": 12.0},
                    "bob": {"avg": 5.0, "n": 2, "best": 0, "adopted": False, "time": 20.0},
                },
            },
        }]
        board = league.leaderboard(runs)
        self.assertIn("alice", board)
        self.assertIn("bob", board)
        self.assertEqual(board["alice"]["algorithm"]["avg"], 8.0)
        self.assertEqual(board["alice"]["algorithm"]["n"], 2)
        self.assertEqual(board["alice"]["algorithm"]["best"], 1)
        self.assertEqual(board["alice"]["algorithm"]["adopted"], 1)
        self.assertEqual(board["alice"]["all"]["avg"], 8.0)
        self.assertEqual(board["bob"]["algorithm"]["avg"], 5.0)

    def test_parallel_run_without_results_skipped(self):
        runs = [{
            "recipe": "parallel",
            "status": "done",
            "state": {"category": "web"},
        }]
        board = league.leaderboard(runs)
        self.assertEqual(board, {})

    def test_review_panel_still_aggregated(self):
        runs = [{
            "recipe": "review_panel",
            "status": "done",
            "state": {
                "category": "design",
                "results": {"carol": {"avg": 7.0, "n": 1, "best": 0, "adopted": False, "time": None}},
            },
        }]
        board = league.leaderboard(runs)
        self.assertEqual(board["carol"]["design"]["avg"], 7.0)


if __name__ == "__main__":
    unittest.main()
