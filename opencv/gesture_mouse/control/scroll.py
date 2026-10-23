"""滚动模块：识别双指姿势，并把持续的上下移动转换为滚轮动作。"""
import math


def scroll_pose_status(points, relaxed=False, thumb_visible=True):
    """判断手是否摆出滚动用的 V 字姿势。

    points 使用图像像素坐标；返回 (是否符合姿势, 第一个不符合的提示)。
    用指尖伸出程度和掌宽比例而非绝对方向判断，因此兼容左右手和画面旋转。
    """
    def distance(a, b):
        return math.dist(points[a], points[b])

    palm = distance(5, 17)
    if palm < 20:
        return False, "Move hand closer"
    # 沿食指/中指朝向判断伸出程度。向掌心下方弯曲的指尖也可能
    # 距掌心很远，不能仅用距离把它误认为伸直（画面下缘尤其明显）。
    axis = tuple(points[6][i] + points[10][i] - points[5][i] - points[9][i]
                 for i in range(2))
    length = math.hypot(*axis)
    if length < palm * 0.1:
        return False, "Show INDEX and MIDDLE joints"
    axis = tuple(v / length for v in axis)

    def extended(base, joint, tip):
        def forward(index):
            return sum((points[index][i] - points[base][i]) * axis[i] for i in range(2))
        threshold = max(palm * (0.25 if relaxed else 0.35), forward(joint) * 1.10)
        return forward(tip) > threshold

    checks = [
        (extended(5, 6, 8), "Lift INDEX fingertip"),
        (extended(9, 10, 12), "Lift MIDDLE fingertip"),
        (not extended(13, 14, 16), "Relax/fold RING finger"),
        (not extended(17, 18, 20), "Relax/fold LITTLE finger"),
        (distance(8, 12) / palm >= 0.12, "Keep two fingertips visible"),
        (not thumb_visible or min(distance(4, tip) for tip in (8, 12)) / palm > 0.46,
         "Release INDEX/MIDDLE pinch"),
    ]
    for passed, reason in checks:
        if not passed:
            return False, reason
    return True, "V pose OK"



class ScrollController:
    """双指轻推选定滚动方向，保持姿势时连续滚动，收起手指即停止。"""
    ENTER_TIME = 0.16
    PUSH_DISTANCE = 0.10  # 手掌宽度比例；不用寻找或回到中心
    MAX_DELTA = 0.75
    MAX_FRAME_GAP = 0.25

    def __init__(self):
        """初始滚动速度为每秒 6 格，方向尚未选定。"""
        self.sensitivity = 6.0  # 每秒滚轮格数，初始慢速
        self.reset()

    def reset(self):
        """清空进入计时、滚动方向和移动基准。"""
        self.active = False
        self.candidate_since = None
        self.anchor_y = None
        self.last_y = None
        self.last_update = None
        self.last_scroll = None
        self.direction = 0

    def update(self, pose, y, palm_width, now, blocked=False):
        """更新滚动状态，返回 (本次滚轮格数, 滚动是否占用输入)。

        y 是食指与中指指尖中点的像素纵坐标；向上移动输出正数，向下移动输出负数。
        """
        if blocked or not pose or palm_width < 20:
            self.reset()
            return 0, False
        if self.last_update is not None and now - self.last_update > self.MAX_FRAME_GAP:
            self.reset()
        self.last_update = now
        if self.candidate_since is None:
            self.candidate_since = now
            # 准备时就记录位置，防止用户在等待进入时轻推被丢弃。
            self.anchor_y = self.last_y = y
            self.last_scroll = now

        if abs(y - self.last_y) / palm_width > self.MAX_DELTA:
            # 跟踪跳变后撤销方向，需要重新轻推，避免意外持续滚动。
            self.direction = 0
            self.anchor_y = y
        self.last_y = y
        displacement = (self.anchor_y - y) / palm_width
        if abs(displacement) >= self.PUSH_DISTANCE:
            # 轻推一次确定方向并重置基准；之后按时间持续输出滚动。
            self.direction = 1 if displacement > 0 else -1
            self.anchor_y = y
        if not self.active:
            if now - self.candidate_since < self.ENTER_TIME:
                return 0, False
            self.active = True
            self.last_scroll = now
            # 已在准备期间轻推，进入后立即给出一次滚动反馈。
            return self.direction, True
        interval = 1 / max(1.0, self.sensitivity)
        if not self.direction or now - self.last_scroll < interval:
            return 0, True
        self.last_scroll = now
        return self.direction, True
