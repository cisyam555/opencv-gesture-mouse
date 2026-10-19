import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from document_scanner import (detect_document, enhance_document, order_points,
                              read_image, save_image, warp_document)


class ScannerTests(unittest.TestCase):
    def make_photo(self):
        image = np.full((1700, 1900, 3), 35, np.uint8)
        corners = np.float32([[300, 140], [1550, 260], [1650, 1540], [180, 1450]])
        cv2.fillConvexPoly(image, corners.astype(np.int32), (230, 230, 230))
        for y in range(400, 1300, 100):
            cv2.putText(image, 'Document OCR 123', (420, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.5, (20, 20, 20), 3)
        return image, corners

    def test_detect_and_preserve_resolution(self):
        image, expected = self.make_photo()
        points, _ = detect_document(image)
        self.assertIsNotNone(points)
        self.assertLess(float(np.max(np.linalg.norm(points - expected, axis=1))), 12)
        result = warp_document(image, points)
        self.assertGreater(result.shape[1], 1400)
        self.assertGreater(result.shape[0], 1200)

    def test_blank_has_no_document(self):
        points, _ = detect_document(np.full((500, 700, 3), 255, np.uint8))
        self.assertIsNone(points)

    def test_unordered_points_and_invalid_geometry(self):
        expected = np.float32([[10, 10], [110, 10], [110, 210], [10, 210]])
        np.testing.assert_equal(order_points(expected[[2, 0, 3, 1]]), expected)
        with self.assertRaises(ValueError):
            order_points([[0, 0], [0, 0], [10, 10], [10, 0]])

    def test_shadow_normalization_preserves_text(self):
        gradient = np.tile(np.linspace(90, 240, 800, dtype=np.uint8), (600, 1))
        cv2.putText(gradient, 'SCAN', (200, 340), cv2.FONT_HERSHEY_SIMPLEX, 2, 10, 3)
        gray, binary = enhance_document(cv2.cvtColor(gradient, cv2.COLOR_GRAY2BGR))
        self.assertLess(float(gray[:100].std()), float(gradient[:100].std()) / 4)
        self.assertEqual(set(np.unique(binary)), {0, 255})
        self.assertGreater(int((binary[270:350, 200:390] == 0).sum()), 200)

    def test_cli_and_chinese_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / '文档.png'
            save_image(source, self.make_photo()[0])
            result = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1]
                                    / 'document_scanner.py'), str(source), '-o', str(root / '结果')],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            for name in ('edges', 'detected', 'color', 'gray', 'scan'):
                self.assertGreater(read_image(root / '结果' / f'{name}.png').size, 0)


if __name__ == '__main__':
    unittest.main()
