"""X11 鼠标高亮模块：绘制透明穿透的绿色箭头，不抢焦点或拦截点击。

箭头尖端与系统鼠标位置对齐。该显示效果只用于提示鼠标位置，
不改变手势识别、鼠标点击或系统鼠标主题。
"""

import math

from .x11_shape import make_click_through


ARROW_OUTLINE = ((0, 0), (0, 48), (12, 37), (24, 62), (34, 57), (22, 33), (42, 33))
ARROW_FILL = ((3, 7), (3, 41), (13, 32), (26, 58), (30, 56), (18, 29), (34, 29))


def polygon_rectangles(vertices):
    """把多边形栅格化为每行矩形，供 X11 设置窗口可见区域。

    X Shape 接收矩形列表而不是多边形；轮廓外的像素不属于窗口区域，
    因此仍能看到下面的桌面。
    """
    rectangles = []
    for y in range(64):
        intersections = []
        # 扫描当前像素行与多边形各边的交点，交点成对表示填充区间。
        for (x1, y1), (x2, y2) in zip(vertices, vertices[1:] + vertices[:1]):
            if min(y1, y2) <= y + 0.5 < max(y1, y2):
                intersections.append(x1 + (y + 0.5 - y1) * (x2 - x1) / (y2 - y1))
        intersections.sort()
        for left, right in zip(intersections[::2], intersections[1::2]):
            x = math.ceil(left)
            width = math.ceil(right) - x
            if width > 0:
                rectangles.append((x, y, width, 1))
    return rectangles


# 填充矩形只计算一次，避免每次更新箭头都重新扫描多边形。
ARROW_FILL_RECTANGLES = polygon_rectangles(ARROW_FILL)


class CursorHighlight:
    """创建并更新置顶箭头窗口；X11 不可用时允许主程序继续运行。"""

    def __init__(self):
        """连接 X11，建立可见形状和空输入区域的置顶窗口。"""
        self.connection = None
        try:
            from Xlib import X, Xatom, display
            from Xlib.ext import shape

            self.connection = display.Display()
            if not self.connection.has_extension("SHAPE"):
                raise RuntimeError("X11 不支持透明穿透区域")
            self.X = X
            screen = self.connection.screen()
            self.green = screen.default_colormap.alloc_color(0, 65535, 34816).pixel
            self.white = screen.default_colormap.alloc_color(65535, 65535, 65535).pixel
            self.window = screen.root.create_window(
                0, 0, 64, 64, 0, screen.root_depth,
                X.InputOutput, X.CopyFromParent,
                override_redirect=1, background_pixel=self.white,
            )
            self.window.set_wm_name("Gesture Mouse Highlight")
            self.window.shape_rectangles(
                shape.ShapeBounding, shape.ShapeSet, X.Unsorted, 0, 0,
                polygon_rectangles(ARROW_OUTLINE),
            )
            # ShapeBounding 限定箭头外形；ShapeInput 为空，点击可以穿透。
            make_click_through(self.window)
            self.window.change_property(
                self.connection.intern_atom("_NET_WM_WINDOW_TYPE"), Xatom.ATOM, 32,
                [self.connection.intern_atom("_NET_WM_WINDOW_TYPE_NOTIFICATION")],
            )
            self.window.change_property(
                self.connection.intern_atom("_NET_WM_STATE"), Xatom.ATOM, 32,
                [self.connection.intern_atom(name) for name in (
                    "_NET_WM_STATE_ABOVE", "_NET_WM_STATE_SKIP_TASKBAR",
                    "_NET_WM_STATE_SKIP_PAGER",
                )],
            )
            self.color_gc = self.window.create_gc(foreground=self.green)
            self.border_gc = self.window.create_gc(foreground=self.white)
            self.connection.sync()
        except Exception as error:
            self.close()
            print(f"鼠标高亮不可用：{error}；手势控制仍可继续。")

    @property
    def available(self):
        """返回高亮窗口是否已成功初始化。"""
        return self.connection is not None

    def update(self, x, y):
        """把箭头尖端移动到系统指针的屏幕坐标，并绘制箭头。"""
        if not self.available:
            return
        # 箭头尖端就是实际指针位置；空输入区域保证所有点击穿透。
        self.window.configure(x=int(x), y=int(y), stack_mode=self.X.Above)
        self.window.map()
        self.window.fill_rectangle(self.border_gc, 0, 0, 64, 64)
        # 一次请求绘制所有色块，避免每帧逐行发送几十次 X11 请求。
        self.window.poly_fill_rectangle(self.color_gc, ARROW_FILL_RECTANGLES)
        self.connection.flush()

    def close(self):
        """关闭 X11 显示连接，清理高亮窗口资源。"""
        if self.connection is not None:
            self.connection.close()
            self.connection = None
