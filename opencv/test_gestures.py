"""模拟手指距离验证点击逻辑，不操作真实鼠标。"""

import unittest

from gestures import PinchClickController


class PinchClickTests(unittest.TestCase):
    def setUp(self):
        self.controller = PinchClickController()
        self.now = 0.0
        self.events = []

    def feed(self, left, right, frames=1):
        for _ in range(frames):
            self.now += 0.05
            button, _ = self.controller.update(left, right, self.now)
            if button:
                self.events.append(button)

    def ready(self):
        self.feed(0.8, 0.8, 6)

    def test_left_click_and_no_repeat(self):
        self.ready()
        self.feed(0.32, 0.8, 2)  # 接近过程不能提前解除准备状态
        self.feed(0.1, 0.8, 4)
        self.feed(0.8, 0.8, 20)
        self.assertEqual(self.events, ["left"])

    def test_right_click(self):
        self.ready()
        self.feed(0.8, 0.1, 4)
        self.feed(0.8, 0.8, 5)
        self.assertEqual(self.events, ["right"])

    def test_long_hold_does_not_click(self):
        self.ready()
        self.feed(0.1, 0.8, 25)
        self.feed(0.8, 0.8, 6)
        self.assertEqual(self.events, [])

    def test_brief_noise_does_not_click(self):
        self.ready()
        self.feed(0.1, 0.8)
        self.feed(0.8, 0.8, 6)
        self.assertEqual(self.events, [])

    def test_competing_pinch_cancels(self):
        self.ready()
        self.feed(0.1, 0.8, 4)
        self.feed(0.1, 0.1, 3)
        self.feed(0.8, 0.8, 6)
        self.assertEqual(self.events, [])

    def test_tracking_loss_cancels(self):
        self.ready()
        self.feed(0.1, 0.8, 4)
        self.controller.reset()
        self.feed(0.8, 0.8, 6)
        self.assertEqual(self.events, [])

    def test_frame_stall_cancels(self):
        self.ready()
        self.feed(0.1, 0.8, 4)
        self.now += 0.5
        self.feed(0.8, 0.8, 6)
        self.assertEqual(self.events, [])

    def test_initial_pinch_does_not_click(self):
        self.feed(0.1, 0.8, 5)
        self.feed(0.8, 0.8, 6)
        self.assertEqual(self.events, [])


if __name__ == "__main__":
    unittest.main()
