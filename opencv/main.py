import time
from pathlib import Path
import numpy as np
import pyautogui

import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

from gestures import PinchClickController


# 每一对编号表示需要连接的两个手部关键点
HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),       # 拇指
    (0, 5), (5, 6), (6, 7), (7, 8),       # 食指
    (5, 9), (9, 10), (10, 11), (11, 12),  # 中指
    (9, 13), (13, 14), (14, 15), (15, 16), # 无名指
    (13, 17), (0, 17),
    (17, 18), (18, 19), (19, 20),          # 小指
]


def draw_hand(frame, landmarks):
    """将模型坐标转换为像素坐标，并绘制骨架。"""
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


def main():
    # 相对于 main.py 定位模型，避免运行目录不同导致找不到文件
    model_path = (
        Path(__file__).resolve().parent
        / "models"
        / "hand_landmarker.task"
    )

    if not model_path.is_file():
        print(f"找不到模型文件：{model_path}")
        return

    options = vision.HandLandmarkerOptions(
        base_options=python.BaseOptions(
            model_asset_path=str(model_path)
        ),
        running_mode=vision.RunningMode.VIDEO,
        num_hands=1,
        min_hand_detection_confidence=0.6,
        min_hand_presence_confidence=0.6,
        min_tracking_confidence=0.6,
    )

    camera = cv2.VideoCapture(0)

    if not camera.isOpened():
        print("摄像头打开失败。")
        camera.release()
        return

    last_timestamp = -1
    # 自动获取屏幕尺寸
    screen_width, screen_height = pyautogui.size()

    # 保留安全保护：指针到达屏幕角落时可触发停止
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0

    # 鼠标平滑系数：越小越平滑，但跟随越慢
    smooth_factor = 0.25

    # 从当前鼠标位置开始，避免初始化为屏幕左上角
    current_position = pyautogui.position()
    smooth_x = float(current_position.x)
    smooth_y = float(current_position.y)

    # 默认暂停，按 S 才开始控制
    control_enabled = False
    hand_was_present = False
    click_controller = PinchClickController()
    last_action = "Open fingers, then pinch"
    last_action_time = 0.0

    try:
        with vision.HandLandmarker.create_from_options(options) as detector:
            while True:
                success, frame = camera.read()

                if not success:
                    print("读取摄像头画面失败。")
                    break

                frame = cv2.flip(frame, 1)

                # OpenCV 默认 BGR，MediaPipe 需要 RGB
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                input_image = mp.Image(
                    image_format=mp.ImageFormat.SRGB,
                    data=rgb_frame,
                )

                # 视频模式要求时间戳严格递增，单位是毫秒
                timestamp = max(
                    time.monotonic_ns() // 1_000_000,
                    last_timestamp + 1,
                )
                last_timestamp = timestamp

                result = detector.detect_for_video(
                    input_image,
                    timestamp,
                )

                height, width = frame.shape[:2]
                left, right = int(width * 0.15), int(width * 0.85)
                top, bottom = int(height * 0.15), int(height * 0.85)
                cv2.rectangle(
                    frame, (left, top), (right, bottom), (255, 200, 0), 2
                )

                if result.hand_landmarks:
                    landmarks = result.hand_landmarks[0]
                    draw_hand(frame, landmarks)

                    # 食指负责移动；短捏合中指为左键，食指为右键。
                    finger_x = landmarks[8].x * width
                    finger_y = landmarks[8].y * height
                    target_x = float(np.interp(
                        finger_x, [left, right], [5, screen_width - 6]
                    ))
                    target_y = float(np.interp(
                        finger_y, [top, bottom], [5, screen_height - 6]
                    ))

                    if control_enabled:
                        if not hand_was_present:
                            position = pyautogui.position()
                            smooth_x = float(position.x)
                            smooth_y = float(position.y)

                        # 使用像素距离计算比例，避免画面宽高比影响距离。
                        def point(index):
                            return np.array([
                                landmarks[index].x * width,
                                landmarks[index].y * height,
                            ])

                        palm_width = float(np.linalg.norm(point(5) - point(17)))
                        now = time.monotonic()
                        if palm_width >= 20:
                            left_ratio = float(
                                np.linalg.norm(point(4) - point(12)) / palm_width
                            )
                            right_ratio = float(
                                np.linalg.norm(point(4) - point(8)) / palm_width
                            )
                            button, freeze = click_controller.update(
                                left_ratio, right_ratio, now
                            )
                        else:
                            # 手太小或侧掌严重时不执行操作。
                            click_controller.reset()
                            button, freeze = None, True

                        if not freeze:
                            smooth_x += (target_x - smooth_x) * smooth_factor
                            smooth_y += (target_y - smooth_y) * smooth_factor
                            pyautogui.moveTo(int(smooth_x), int(smooth_y))

                        if button is not None:
                            pyautogui.click(button=button)
                            last_action = f"{button.upper()} CLICK"
                            last_action_time = now

                    hand_was_present = True
                else:
                    hand_was_present = False
                    click_controller.reset()

                mode = "ACTIVE" if control_enabled else "PAUSED"
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
                    "S: start/pause | Q / Esc: quit",
                    (20, 65),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (0, 255, 0),
                    2,
                )

                if time.monotonic() - last_action_time < 1.0:
                    action_text = last_action
                elif click_controller.button:
                    action_text = f"PINCH {click_controller.button.upper()}: release to click"
                else:
                    action_text = "Thumb+middle: LEFT | Thumb+index: RIGHT"
                cv2.putText(
                    frame, action_text, (20, 95),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1,
                )

                cv2.imshow("Gesture Mouse", frame)

                key = cv2.waitKey(1) & 0xFF
                if key == ord("s"):
                    control_enabled = not control_enabled
                    hand_was_present = False
                    click_controller.reset()
                elif key == ord("q") or key == 27:
                    break

    except pyautogui.FailSafeException:
        print("鼠标到达屏幕角落，已触发安全停止。")
    except KeyboardInterrupt:
        print("程序已停止。")
    finally:
        camera.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
