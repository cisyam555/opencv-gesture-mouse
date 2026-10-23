"""摄像头读取模块：在后台持续采集，只把最新画面交给识别程序。

单独采集可以避免识别速度跟不上摄像头时排队处理旧画面，
让手势控制尽量跟得上当前动作。
"""

import threading
import time


class LatestFrameCamera:
    """把 OpenCV 摄像头包装成“只读最新帧”的线程安全接口。

    后台线程独占 VideoCapture.read/release；主线程通过 read() 取帧。
    """

    def __init__(self, camera):
        # Condition 用来保护共享状态，并在新帧到达时唤醒等待中的主线程。
        self.camera = camera
        self.condition = threading.Condition()
        self.stopped = False
        self.failed = False
        self.latest = None
        self.sequence = 0
        self.consumed = 0
        self.capture_fps = 0.0
        self.frame_time = None
        self.frame_age_ms = 0.0
        # daemon 避免异常退出时后台线程单独阻止 Python 结束。
        self.thread = threading.Thread(target=self._capture, daemon=True)
        self.thread.start()

    def _capture(self):
        """后台采集循环；新帧覆盖旧帧，不建立积压队列。"""
        previous = None
        try:
            while True:
                with self.condition:
                    if self.stopped:
                        break
                success, frame = self.camera.read()
                captured = time.monotonic()
                with self.condition:
                    if not success:
                        self.failed = True
                        self.condition.notify_all()
                        break
                    if previous is not None:
                        # 用指数平滑避免摄像头帧率显示值每帧大幅跳动。
                        fps = 1 / max(0.001, captured - previous)
                        self.capture_fps = (fps if not self.capture_fps else
                                            self.capture_fps * 0.9 + fps * 0.1)
                    previous = captured
                    self.latest = (frame, captured)
                    self.sequence += 1
                    self.condition.notify_all()
        except Exception:
            with self.condition:
                self.failed = True
                self.condition.notify_all()
        finally:
            self.camera.release()

    def read(self, timeout=0.5):
        """等待一张新帧；断流、超时或画面过旧时返回失败。"""
        with self.condition:
            available = self.condition.wait_for(
                lambda: self.stopped or self.failed or self.sequence > self.consumed,
                timeout=timeout,
            )
            if not available or self.stopped or self.failed:
                return False, None
            frame, captured = self.latest
            self.consumed = self.sequence
            self.frame_time = captured
            # 这是应用收到帧后的等待时间，不包含曝光及驱动内部缓存。
            self.frame_age_ms = (time.monotonic() - captured) * 1000
            if self.frame_age_ms > 200:
                return False, None
            return True, frame

    def release(self):
        """通知采集线程停止并等待它结束。"""
        with self.condition:
            self.stopped = True
            self.condition.notify_all()
        # 不从主线程强行 release 正在 read 的 VideoCapture，避免驱动竞态。
        self.thread.join(timeout=1.0)
