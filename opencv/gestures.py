"""与摄像头和系统鼠标分离的短捏合单击判断。"""


class PinchClickController:
    # 距离以手掌宽度为单位；进入和退出使用不同阈值。
    PINCH_ENTER = 0.25
    PINCH_EXIT = 0.40
    MIN_HOLD = 0.08
    MAX_HOLD = 0.60
    RELEASE_TIME = 0.06
    READY_TIME = 0.15
    COOLDOWN = 0.25
    MAX_FRAME_GAP = 0.25

    def __init__(self):
        self.reset()

    def reset(self):
        self.button = None
        self.started = None
        self.released = None
        self.neutral_since = None
        self.armed = False
        self.last_click = float("-inf")
        self.last_update = None

    def update(self, left_ratio, right_ratio, now):
        """返回 (单击按钮或 None, 是否锁住指针)。

        left_ratio 是拇指到中指的距离，right_ratio 是拇指到食指。
        长捏、双重捏合和数据中断只取消，不发送单击。
        """
        if (
            self.last_update is not None
            and now - self.last_update > self.MAX_FRAME_GAP
        ):
            self.reset()
        self.last_update = now

        distances = {"left": left_ratio, "right": right_ratio}
        neutral = min(distances.values()) > self.PINCH_EXIT

        if self.button is not None:
            other = "right" if self.button == "left" else "left"
            if (
                now - self.started > self.MAX_HOLD
                or distances[other] < self.PINCH_EXIT
            ):
                self.button = None
                self.released = None
                self.neutral_since = None
                self.armed = False
                return None, True

            if distances[self.button] > self.PINCH_EXIT:
                # 太短的捏合可能是抖动，不作为有效点击。
                if self.released is None:
                    if now - self.started < self.MIN_HOLD:
                        self.button = None
                        self.neutral_since = None
                        return None, True
                    self.released = now
                if now - self.released >= self.RELEASE_TIME:
                    button = self.button
                    self.button = None
                    self.released = None
                    self.neutral_since = None
                    self.last_click = now
                    return button, True
            else:
                self.released = None
            return None, True

        if neutral:
            if self.neutral_since is None:
                self.neutral_since = now
            if now - self.neutral_since >= self.READY_TIME:
                self.armed = True
            return None, False

        self.neutral_since = None
        if self.armed and now - self.last_click >= self.COOLDOWN:
            for button, distance in distances.items():
                other = "right" if button == "left" else "left"
                if (
                    distance < self.PINCH_ENTER
                    and distances[other] > self.PINCH_EXIT
                ):
                    self.button = button
                    self.started = now
                    self.released = None
                    self.armed = False
                    break

        # 不明确的捏合也锁住指针，并要求重新张开后再尝试。
        if self.button is None and max(distances.values()) < self.PINCH_EXIT:
            self.armed = False
        return None, True
