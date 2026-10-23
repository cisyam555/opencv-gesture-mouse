"""兼容旧 python3-Xlib 的 X Shape 1.1 输入区域请求。

PyAutoGUI 附带的旧绑定将 region 限制为 0/1，无法传入 Input=2。
这里按同一 X11 协议补充输入区域，不修改第三方库或系统设置。
"""

from Xlib.protocol import rq, structs
from Xlib.ext import shape


class InputRectangles(rq.Request):
    """X Shape 的 SetRectangles 请求，用于设置窗口输入区域。"""

    # region=2 表示 ShapeInput；空矩形列表使窗口不接收鼠标输入。
    _request = rq.Struct(
        rq.Card8("opcode"), rq.Opcode(1), rq.RequestLength(),
        rq.Card8("operation"), rq.Card8("region"), rq.Card8("ordering"), rq.Pad(1),
        rq.Window("window"), rq.Int16("x"), rq.Int16("y"),
        rq.List("rectangles", structs.Rectangle),
    )


class GetInputRectangles(shape.GetRectangles):
    """X Shape 的 GetRectangles 请求，用于读取窗口输入区域。"""

    _request = rq.Struct(
        rq.Card8("opcode"), rq.Opcode(8), rq.RequestLength(),
        rq.Window("window"), rq.Card8("region"), rq.Pad(3),
    )


def make_click_through(window):
    """把窗口的鼠标输入区域设为空，让点击落到下方桌面窗口。"""
    InputRectangles(
        display=window.display,
        opcode=window.display.get_extension_major("SHAPE"),
        operation=0, region=2, ordering=0, window=window.id,
        x=0, y=0, rectangles=[],
    )


def get_input_rectangles(window):
    """读取窗口当前的 ShapeInput 矩形列表，主要用于检查和调试。"""
    return GetInputRectangles(
        display=window.display,
        opcode=window.display.get_extension_major("SHAPE"),
        window=window.id, region=2,
    ).rectangles
