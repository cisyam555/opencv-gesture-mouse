"""跟踪保护模块：检查操作所需关键点是否在画面中，并等待稳定恢复。"""

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class TrackingStatus:
    """一帧跟踪检查的结果：是否可操作、是否靠近边缘及提示文字。"""

    ready: bool
    near_edge: bool
    message: str
    scroll_ready: bool = False


def points_visible(points, indices):
    """检查指定关键点是否存在且坐标为有效的归一化画面坐标 (0 到 1)。"""
    return bool(points) and all(
        index < len(points)
        and all(math.isfinite(value) and 0 <= value <= 1 for value in points[index])
        for index in indices
    )


class TrackingGuard:
    """检测手部丢失、关键点出画和重新出现后的短暂恢复期。"""

    RECOVER_TIME = 0.12
    EDGE_MARGIN = 0.06
    MOVE_POINTS = (5, 6, 8, 17)  # 食指与掌宽，不依赖手腕
    # 滚动只要求双指与掌宽点可见；弯曲的其他指尖靠近下缘不应拦住滚动。
    SCROLL_POINTS = (5, 6, 8, 9, 10, 12, 17)

    def __init__(self):
        """初始化恢复计时器。"""
        self.reset()

    def reset(self):
        """清除可见起始时间；下一次检测到手时重新等待稳定。"""
        self.visible_since = None

    def update(self, points, now):
        """根据归一化关键点返回 TrackingStatus，不执行鼠标操作。"""
        if not points:
            self.reset()
            return TrackingStatus(False, False, 'HAND LOST: return hand to camera')
        if not points_visible(points, self.MOVE_POINTS):
            self.reset()
            return TrackingStatus(False, True, 'INDEX/PALM OUT: move inward')
        near = any(
            min(x, y, 1 - x, 1 - y) < self.EDGE_MARGIN
            for x, y in points
        )
        if self.visible_since is None:
            self.visible_since = now
        if now - self.visible_since < self.RECOVER_TIME:
            return TrackingStatus(False, near, 'RECOVERING: hold hand steady')
        # 移动所需点仍可见时可继续移动；滚动另行检查更多关键点。
        partial = not points_visible(points, range(len(points)))
        message = (
            'PARTIAL HAND: index movement available' if partial else
            'NEAR CAMERA EDGE: movement available' if near else 'Tracking OK'
        )
        return TrackingStatus(
            True, near, message,
            scroll_ready=points_visible(points, self.SCROLL_POINTS),
        )
