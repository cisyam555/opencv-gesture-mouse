"""手势模块：把 MediaPipe 关键点转换成点击、双击、拖拽和移动动作。"""
import math


def is_move_pose(points):
    """判断食指是否伸直，用作鼠标移动的开关。

    points 是 21 个关键点的二维坐标；点 5/17 是掌部两侧，
    点 6 是食指中间关节，点 8 是食指指尖。
    """
    palm = math.dist(points[5], points[17])
    center = tuple((points[5][i] + points[17][i]) / 2 for i in range(2))
    # 指尖比中间关节更远离掌部中心一定比例，认为食指已经伸出。
    return (math.dist(center, points[8])
            > math.dist(center, points[6]) + palm * 0.08)


class PinchClickController:
    """将拇指与不同手指的距离变化识别为鼠标动作。

    食指左击、中指右击、无名指双击、小指长捏后拖拽。
    这里只返回动作，不直接调用真实鼠标，便于测试手势逻辑。
    """
    # 捏合距离以掌宽为单位；进入和退出门槛不同可减少边界抖动。
    PINCH_PREPARE = 0.44
    PREPARE_FREEZE_TIME = 0.12
    PINCH_ENTER = 0.36
    PINCH_EXIT = 0.46
    MIN_HOLD = 0.04
    MAX_HOLD = 1.80
    RELEASE_TIME = 0.04
    READY_TIME = 0.06
    COOLDOWN = 0.22
    POINTER_RELEASE_GUARD = 0.14
    MAX_FRAME_GAP = 0.75
    DRAG_HOLD = 0.30
    BUTTONS = ('left', 'right', 'double_left', 'drag')

    def __init__(self):
        """创建控制器并初始化所有手势状态。"""
        self.reset()

    def reset(self):
        """清除手势状态；若拖动按键仍按住，返回需要执行的释放动作。"""
        action = 'left_up' if getattr(self, 'dragging', False) else None
        self.dragging = False
        self.button = None
        self.started = self.close_since = self.released = None
        self.confirmed = False
        self.armed = dict.fromkeys(self.BUTTONS, False)
        self.neutral_since = dict.fromkeys(self.BUTTONS, None)
        self.last_click = float('-inf')
        self.last_update = None
        self.prepare_since = None
        self.hint = 'OPEN thumb and selected finger, then pinch'
        return action

    def cancel(self, reason):
        """取消当前手势，但保留冷却计时，避免取消后立即触发新点击。"""
        last_click, last_update = self.last_click, self.last_update
        action = self.reset()
        self.last_click, self.last_update = last_click, last_update
        self.hint = 'CANCEL: ' + reason
        return action, True

    def update(self, left_ratio, right_ratio, now, right_available=True,
               double_ratio=1.0, double_available=True, left_available=True,
               drag_ratio=1.0, drag_available=False):
        """根据当前各指距离推进手势状态机。

        距离参数都是“拇指到目标指尖的距离 / 掌宽”。
        返回 (鼠标动作或 None, 是否暂时锁住指针)。
        """
        if self.last_update is not None and now - self.last_update > self.MAX_FRAME_GAP:
            action = self.reset()
            self.last_update = now
            self.hint = 'CANCEL: frame gap; open selected finger again'
            return action, action is not None
        self.last_update = now
        # 将四种动作的测量值和可见性统一按动作名称索引。
        distances = dict(zip(self.BUTTONS, (left_ratio, right_ratio, double_ratio, drag_ratio)))
        available = dict(zip(self.BUTTONS, (left_available, right_available, double_available, drag_available)))
        # 拖拽已经开始后只检查小指松开/出画，其余手指不再切换操作。
        if self.dragging:
            if not drag_available or drag_ratio > self.PINCH_EXIT:
                action, freeze = self.cancel('')
                self.last_click = now
                self.hint = 'DRAG RELEASED: left button up'
                return action, freeze
            self.hint = 'DRAGGING: move hand; release little finger to drop'
            return None, False
        # 各指独立准备：其他手指自然收着，不会阻挡当前手指。
        for name in self.BUTTONS:
            if not available[name]:
                self.armed[name] = False
                self.neutral_since[name] = None
            elif name != self.button:
                if distances[name] > self.PINCH_EXIT:
                    if self.neutral_since[name] is None:
                        self.neutral_since[name] = now
                    if now - self.neutral_since[name] >= self.READY_TIME:
                        self.armed[name] = True
                else:
                    self.neutral_since[name] = None

        candidates = [name for name in self.BUTTONS
                      if available[name] and self.armed[name]
                      and distances[name] < self.PINCH_ENTER]
        if self.button is not None:
            if not available[self.button]:
                return self.cancel('selected fingertip outside camera')
            if candidates:
                return self.cancel('multiple pinches; open then retry')
            if now - self.started > self.MAX_HOLD:
                return self.cancel('pinch held too long')
            distance = distances[self.button]
            if not self.confirmed:
                # 先确认捏合持续足够久；拖拽比普通点击需要更长按压时间。
                if distance < self.PINCH_ENTER:
                    if self.close_since is None:
                        self.close_since = now
                    hold_time = self.DRAG_HOLD if self.button == 'drag' else self.MIN_HOLD
                    self.confirmed = now - self.close_since >= hold_time
                else:
                    self.close_since = None
            if self.button == 'drag' and self.confirmed:
                self.dragging = True
                self.hint = 'DRAGGING: move hand; release little finger to drop'
                return 'left_down', True
            if distance > self.PINCH_EXIT:
                if not self.confirmed:
                    return self.cancel('pinch too brief; hold about 0.15s')
                if self.released is None:
                    self.released = now
                if now - self.released >= self.RELEASE_TIME:
                    action = self.button
                    self.cancel('')
                    self.last_click = now
                    self.hint = 'SENT: ' + action.upper()
                    return action, True
            else:
                self.released = None
            if self.button == 'drag':
                self.hint = 'DRAG READY: keep little pinch for 0.3s'
                return None, True
            self.hint = ('CONFIRMED ' + self.button.upper() + ': release to click'
                         if self.confirmed else 'PINCH ' + self.button.upper() + ': hold briefly')
            return None, True

        # 点击/放下后的开指动作不映射为鼠标位移，随后重新建立掌部基准。
        if now - self.last_click < self.POINTER_RELEASE_GUARD:
            self.hint = 'HOLD: release fingers, pointer locked'
            return None, True

        if len(candidates) > 1:
            return self.cancel('multiple pinches; open then retry')
        if candidates and now - self.last_click >= self.COOLDOWN:
            self.button = candidates[0]
            self.armed[self.button] = False
            self.started = self.close_since = now
            self.confirmed = False
            self.released = None
            self.hint = 'PINCH ' + self.button.upper() + ': hold briefly'
            return None, True
        ready = [name for name in self.BUTTONS if self.armed[name]]
        self.hint = 'READY: ' + '/'.join(ready) if ready else 'OPEN selected finger away from thumb'
        # 接近捏合时就先锁指针，点击完成后松指不会带动鼠标跳动。
        preparing = any(available[name] and self.armed[name]
                        and distances[name] < self.PINCH_PREPARE for name in self.BUTTONS)
        if not preparing:
            self.prepare_since = None
            return None, False
        if self.prepare_since is None:
            self.prepare_since = now
        # 只有真正进入捏合才持续锁位；自然蜷曲停在准备区不能一直挡住移动。
        return None, now - self.prepare_since < self.PREPARE_FREEZE_TIME
