import unittest
from app import *

class TestTicTacToe(unittest.TestCase):
    def test_init(self):
        init()
        self.assertEqual(len(gameBoard), 3)
        self.assertEqual(len(gameBoard[0]), 3)
        self.assertEqual(currentPlayer, PLAYER_X)
        self.assertFalse(isGameOver)

    def test_reset(self):
        reset()
        self.assertEqual(len(gameBoard), 3)
        self.assertEqual(len(gameBoard[0]), 3)
        self.assertEqual(currentPlayer, PLAYER_X)
        self.assertFalse(isGameOver)

    def test_handleClick(self):
        handleClick(1, 1)
        self.assertEqual(gameBoard[1][1], PLAYER_X)
        self.assertEqual(currentPlayer, PLAYER_O)
        self.assertFalse(isGameOver)

    def test_checkWin(self):
        self.assertTrue(checkWin(0, 0))
        self.assertFalse(checkWin(1, 1))

if __name__ == '__main__':
    unittest.main()