"""指针模块：平滑鼠标目标，并从手掌相对位移得到屏幕指针位置。"""

import math


class PointerFilter:
    """对屏幕坐标做自适应平滑，减少静止抖动并保持快速移动响应。"""

    def __init__(self, width, height, response=1.35):
        """width/height 是屏幕像素尺寸，response 控制跟随速度。"""
        self.width = width
        self.height = height
        self.diagonal = math.hypot(width, height)
        self.hover_radius = max(1.0, self.diagonal * 0.0004)
        self.response = response
        self.position = None
        self.last_time = None

    def reset(self, x, y, now=None):
        """把滤波器当前位置设为当前鼠标位置，避免重新启用时跳动。"""
        self.position = (float(x), float(y))
        self.last_time = now

    def update(self, x, y, now):
        """平滑趋近目标坐标，并返回新的屏幕坐标。"""
        if self.position is None:
            self.reset(x, y, now)
            return self.position
        dt = 1 / 30 if self.last_time is None else now - self.last_time
        self.last_time = now
        dt = max(0.001, min(0.1, dt))
        distance = math.dist((x, y), self.position)
        if distance <= self.hover_radius:
            self.position = self._snap_edges(x, y, *self.position)
            return self.position

        # 小幅误差慢跟随，大幅移动提高截止频率；不依赖固定帧率。
        cutoff = min(18.0, 4.0 + distance / self.diagonal * 120) * self.response
        alpha = 1 - math.exp(-2 * math.pi * cutoff * dt)
        old_x, old_y = self.position
        self.position = self._snap_edges(
            x, y, old_x + (x - old_x) * alpha,
            old_y + (y - old_y) * alpha,
        )
        return self.position

    def _snap_edges(self, target_x, target_y, x, y):
        # 防抖死区不能让指针永远停在边缘内侧，否则无法唤出隐藏 Dock。
        radius = self.hover_radius * 2
        if target_y >= self.height - 1 and y >= self.height - 1 - radius:
            y = float(self.height - 1)
        elif target_y <= 1 and y <= 1 + radius:
            y = 1.0
        if target_x <= 1 and x <= 1 + radius:
            x = 1.0
        elif target_x >= self.width - 2 and x >= self.width - 2 - radius:
            x = float(self.width - 2)
        return x, y


class HandPointer:
    """将手掌移动转换为相对鼠标位移，食指伸直时才允许普通移动。

    点击、收指和稳定悬停时会锁定目标；拖拽期间允许掌部持续移动。
    """

    def __init__(self, screen_width, screen_height):
        """记录屏幕尺寸并清空上一次手势的移动基准。"""
        self.width = screen_width
        self.height = screen_height
        self.diagonal = math.hypot(screen_width, screen_height)
        self.reset()

    def reset(self):
        """清除手部坐标、悬停计时和收指判断历史。"""
        self.hand_position = None
        self.target = None
        self.last_time = None
        self.reach_history = []
        self.retracting = False
        self.extended_reach = None
        self.retract_until = None
        self.hover_history = []
        self.hover_anchor = None

    def update(self, points, frame_width, frame_height, now, current, dragging=False):
        """根据 21 个手部关键点更新屏幕目标。

        返回 (x, y) 或 None（指针锁定）。手掌位移采用相对映射，
        这样手指弯曲可以停止指针，而不会让指尖弧线误带动鼠标。
        """
        from .gestures import is_move_pose

        palm = math.dist(points[5], points[17])
        if palm < 20 or (not dragging and not is_move_pose(points)):
            self.reset()
            return None
        if not dragging:
            reach = math.dist(points[5], points[8]) / palm
            self.reach_history = [(t, r) for t, r in self.reach_history if now - t <= 0.22]
            # 指尖相对掌部快速缩短，说明开始收指；整只手平移不改变此比例。
            reference = max((r for _, r in self.reach_history), default=reach)
            if reference - reach > 0.24 and not self.retracting:
                self.retracting = True
                self.extended_reach = reference
                self.retract_until = now + 0.12
            self.reach_history.append((now, reach))
            # 只短暂拦截开始收指的瞬间，避免姿态变化后一直无法解锁。
            if self.retracting:
                self.hand_position = None
                self.target = None
                if reach < self.extended_reach - 0.06 and now < self.retract_until:
                    return None
                self.retracting = False
                self.reach_history = [(now, reach)]

        # 食指根部（5号点）随手掌移动，弯曲指尖不会直接改变指针目标。
        hand = (float(points[5][0]) * self.width / (frame_width * 0.56),
                float(points[5][1]) * self.height / (frame_height * 0.50))
        if self.hand_position is None or now - self.last_time > 0.5:
            self.hand_position = hand
            self.target = tuple(current)
            self.last_time = now
            self.hover_history = [(now, hand)]
            self.hover_anchor = None
            return self.target
        # 在原始掌部输入上判断悬停，避免小噪声不断累积为目标漂移。
        # 锁定锚点保持不动；明确移出解锁半径后立即恢复相对移动。
        settle_radius = max(2.0, self.diagonal * 0.0007)
        wake_radius = max(3.0, self.diagonal * 0.0012)
        self.hover_history.append((now, hand))
        self.hover_history = [(t, h) for t, h in self.hover_history if now - t <= 0.55]
        if self.hover_anchor is not None:
            if math.dist(hand, self.hover_anchor) <= wake_radius:
                self.hand_position = hand
                self.target = tuple(current)
                self.last_time = now
                return self.target
            self.hover_anchor = None
            self.hover_history = [(now, hand)]
        elif (self.hover_history and now - self.hover_history[0][0] >= 0.45
              and all(math.dist(hand, h) <= settle_radius for _, h in self.hover_history)):
            self.hover_anchor = tuple(
                sum(h[i] for _, h in self.hover_history) / len(self.hover_history)
                for i in range(2)
            )
            self.hand_position = hand
            self.target = tuple(current)  # 丢弃尚未追上的平滑尾巴。
            self.last_time = now
            return self.target

        dt = max(0.01, min(0.2, now - self.last_time))
        self.last_time = now
        dx, dy = (hand[i] - self.hand_position[i] for i in range(2))
        distance = math.hypot(dx, dy)
        # 以相同屏幕/摄像头比例定义抖动死区；持续小移动可以累计跨过死区。
        deadzone = max(1.0, self.diagonal * 0.0003)
        if distance <= deadzone:
            return self.target
        speed = distance / self.diagonal / dt
        gain = 0.50 + 0.65 * min(1.0, speed / 0.45)
        self.target = (
            max(1.0, min(self.width - 2.0, self.target[0] + dx * gain)),
            max(1.0, min(self.height - 1.0, self.target[1] + dy * gain)),
        )
        self.hand_position = hand
        return self.target
