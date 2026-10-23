"""鼠标输出模块：把手势动作交给 PyAutoGUI，并负责可靠释放拖动按键。"""

class MouseOutput:
    """鼠标后端的薄封装，便于主程序统一处理各类动作。"""

    def __init__(self, backend):
        """backend 通常是 pyautogui，也可以是测试用的模拟对象。"""
        self.backend = backend
        self.left_held = False

    def apply(self, action):
        """执行手势控制器返回的动作；None 表示当前无需鼠标操作。"""
        if action == "left_down" and not self.left_held:
            # 即使底层调用中途失败，清理逻辑也会尝试释放。
            self.left_held = True
            self.backend.mouseDown(button="left")
        elif action == "left_up":
            self.release()
        elif action == "double_left":
            # 同一主循环内输出两次点击，期间不发送指针移动。
            self.backend.doubleClick(interval=0.12, button="left")
        elif action in ("left", "right"):
            self.backend.click(button=action)

    def release(self):
        """若拖动左键仍按住则释放；重复调用不会重复发送抬起事件。"""
        if not self.left_held:
            return
        # 角落安全停止后仍必须释放按键。只对清理调用临时绕过保护，
        # 不执行移动或点击，并立即恢复原设置。
        failsafe = self.backend.FAILSAFE
        try:
            self.backend.FAILSAFE = False
            self.backend.mouseUp(button="left")
            self.left_held = False
        finally:
            self.backend.FAILSAFE = failsafe
