"""Characters keep their size in the room on a shorter (landscape) set picture."""
import unittest

from oddstudio.acting import HEIGHT, MIN_HEIGHT, scaled_height


class ScaleTest(unittest.TestCase):
    def test_portrait_unchanged_landscape_scaled(self):
        self.assertEqual(scaled_height(1536), (HEIGHT, MIN_HEIGHT))
        self.assertEqual(scaled_height(None), (HEIGHT, MIN_HEIGHT))
        self.assertEqual(scaled_height(1024), (round(HEIGHT * 1024 / 1536), round(MIN_HEIGHT * 1024 / 1536)))
        self.assertEqual(scaled_height(2048), (HEIGHT, MIN_HEIGHT))


if __name__ == "__main__":
    unittest.main()
