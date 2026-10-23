"""Linux X11 全局快捷键：窗口失去焦点或隐藏预览时仍可控制程序。"""


class GlobalHotkeys:
    """监听 F8 暂停/恢复、F9 预览开关和 F10 退出。"""

    # 主循环根据这些命令更新应用状态，本类只负责监听按键。
    ACTIONS = {"F8": "pause", "F9": "preview", "F10": "quit"}

    def __init__(self):
        """尝试注册快捷键；失败时保留窗口内按键作为备用方案。"""
        self.connection = None
        self.actions = {}
        try:
            from Xlib import X, XK, display

            self.connection = display.Display()
            self.root = self.connection.screen().root
            # 同时兼容 CapsLock、NumLock，不抢占 Alt/Ctrl 组合键。
            self.modifiers = (0, X.LockMask, X.Mod2Mask, X.LockMask | X.Mod2Mask)
            errors = []
            for name, action in self.ACTIONS.items():
                keycode = self.connection.keysym_to_keycode(XK.string_to_keysym(name))
                self.actions[keycode] = action
                for modifiers in self.modifiers:
                    self.root.grab_key(
                        keycode, modifiers, False,
                        X.GrabModeAsync, X.GrabModeAsync,
                        onerror=lambda error, request: errors.append(error),
                    )
            self.connection.sync()
            if errors:
                raise RuntimeError("功能键已被其他程序占用")
            self.key_press = X.KeyPress
        except Exception as error:
            self.close()
            print(f"全局快捷键不可用：{error}。请保留预览窗口，使用 S/Q 等本地按键。")

    @property
    def available(self):
        """X11 连接是否成功建立。"""
        return self.connection is not None

    def poll(self):
        """读取已经到达的 X11 键盘事件并返回对应命令列表。"""
        actions = []
        if self.connection is not None:
            while self.connection.pending_events():
                event = self.connection.next_event()
                if event.type == self.key_press and event.detail in self.actions:
                    actions.append(self.actions[event.detail])
        return actions

    def close(self):
        """关闭 X11 连接，释放本程序占用的全局快捷键。"""
        if self.connection is not None:
            self.connection.close()
            self.connection = None
