"""预览窗口：手部骨架、操作提示与性能信息的绘制。"""

import time

import cv2


# 每一对编号表示需要连接的两个手部关键点
HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),       # 拇指
    (0, 5), (5, 6), (6, 7), (7, 8),       # 食指
    (5, 9), (9, 10), (10, 11), (11, 12),  # 中指
    (9, 13), (13, 14), (14, 15), (15, 16), # 无名指
    (13, 17), (0, 17),
    (17, 18), (18, 19), (19, 20),          # 小指
]

# 预览刷新与识别分开限速，降低窗口绘制对手势控制的影响。
PREVIEW_TITLE = "Gesture Mouse"
PREVIEW_FPS = 12  # 仅限制预览刷新，不限制识别与鼠标输出


def open_preview(screen_width):
    """创建独立于摄像头分辨率的预览小窗，并放到屏幕右上方。"""
    cv2.namedWindow(PREVIEW_TITLE, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(PREVIEW_TITLE, 480, 360)
    cv2.moveWindow(PREVIEW_TITLE, max(0, screen_width - 520), 40)


def draw_hand(frame, landmarks):
    """把模型输出的归一化关键点转成像素，并画手部骨架和编号。"""
    height, width = frame.shape[:2]

    points = [
        (
            max(0, min(width - 1, int(point.x * width))),
            max(0, min(height - 1, int(point.y * height))),
        )
        for point in landmarks
    ]

    # 先画连线
    for start, end in HAND_CONNECTIONS:
        cv2.line(frame, points[start], points[end], (0, 255, 0), 2)

    # 再画关键点和编号
    for index, position in enumerate(points):
        cv2.circle(frame, position, 5, (0, 0, 255), -1)
        cv2.putText(
            frame,
            str(index),
            (position[0] + 6, position[1] - 6),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.4,
            (255, 255, 255),
            1,
        )

    # 突出显示食指指尖，第 8 号点
    cv2.circle(frame, points[8], 10, (0, 255, 255), 2)


def draw_preview(
    frame, *,
    control_enabled,
    result,
    click_controller,
    scroll_controller,
    last_action_time,
    last_action,
    pointer_moving,
    motion_hint,
    pointer_filter,
    tracking,
    frame_fps,
    moved_frames,
    movement_detail,
    click_hint,
    scroll_hint,
    action_counts,
    stage_ms,
    camera,
):
    """只绘制当前状态，不判断手势、不发送鼠标动作。"""
    height, width = frame.shape[:2]
    mode = "ACTIVE" if control_enabled else "PAUSED"
    if result.hand_landmarks:
        draw_hand(frame, result.hand_landmarks[0])
    status = (
        "Hand detected"
        if result.hand_landmarks
        else "No hand"
    )

    cv2.putText(
        frame,
        f"{mode} | {status}",
        (20, 35),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (0, 255, 0),
        2,
    )

    cv2.putText(
        frame,
        "F8: pause | F9: preview | F10: quit | S/Q: local",
        (20, 65),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (0, 255, 0),
        2,
    )

    if click_controller.dragging:
        action_text = "DRAGGING: move hand | release little pinch to DROP"
    elif click_controller.button == 'drag':
        action_text = "DRAG READY: hold thumb+little for 0.3s"
    elif scroll_controller.active:
        direction = {0: "PUSH UP/DOWN to start", 1: "UP", -1: "DOWN"}[scroll_controller.direction]
        action_text = f"SCROLL {direction} | fold middle to STOP"
    elif scroll_controller.candidate_since is not None:
        action_text = "SCROLL READY: hold V fingers for 0.16s"
    elif time.monotonic() - last_action_time < 2.0:
        action_text = last_action
    elif click_controller.button:
        action_text = f"PINCH {click_controller.button.upper()}: release to click"
    elif pointer_moving:
        action_text = "MOVE: hand motion | curl index to STOP"
    else:
        action_text = "index LEFT | middle RIGHT | ring DOUBLE | little DRAG"
    cv2.putText(
        frame, action_text, (20, 95),
        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1,
    )

    cv2.putText(
        frame, motion_hint, (20, 120),
        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1,
    )

    cv2.putText(
        frame,
        f"Pointer response: {pointer_filter.response:.1f} | Scroll speed: {scroll_controller.sensitivity:.0f}/s",
        (20, 145), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1,
    )

    cv2.putText(
        frame, tracking.message, (20, 170),
        cv2.FONT_HERSHEY_SIMPLEX, 0.5,
        (0, 165, 255) if tracking.near_edge or not tracking.ready else (0, 255, 0), 1,
    )
    cv2.putText(
        frame, f"FPS:{frame_fps:.1f} MOVE calls:{moved_frames} {movement_detail}",
        (20, 195), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1,
    )
    cv2.putText(
        frame, click_hint, (20, 220), cv2.FONT_HERSHEY_SIMPLEX,
        0.48, (0, 255, 255), 1,
    )
    cv2.putText(
        frame,
        f"SENT: L={action_counts['left']} R={action_counts['right']} D={action_counts['double_left']} drag={action_counts['left_down']}",
        (20, 245), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (255, 255, 255), 1,
    )
    cv2.putText(
        frame,
        "ms avg: cam:{capture:.1f} detect:{detect:.1f} ctrl:{control:.1f} ui:{preview:.1f}".format(**stage_ms),
        (20, 270), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1,
    )
    cv2.putText(
        frame,
        f"Camera:{camera.capture_fps:.1f}fps app wait:{camera.frame_age_ms:.1f}ms",
        (20, 295), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1,
    )
    cv2.putText(
        frame, scroll_hint, (20, 320), cv2.FONT_HERSHEY_SIMPLEX,
        0.48, (0, 255, 255), 1,
    )
    cv2.putText(
        frame,
        f"WHEEL SENT: UP={action_counts['wheel_up']} DOWN={action_counts['wheel_down']} (place cursor on webpage)",
        (20, 345), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1,
    )
    if tracking.near_edge:
        cv2.rectangle(frame, (3, 3), (width - 4, height - 4), (0, 165, 255), 3)

    cv2.imshow(PREVIEW_TITLE, frame)
