"""手势鼠标主流程。

主循环依次读取最新摄像头画面、用 MediaPipe 定位手部关键点、
判断点击/滚动/移动动作，再将动作交给系统鼠标并更新预览窗口。
按 F8 或窗口内 S 暂停/恢复，按 F10 或窗口内 Q/Esc 退出。
"""


import time
from pathlib import Path
import numpy as np
import pyautogui

import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

from .camera import LatestFrameCamera
from .control.gestures import PinchClickController
from .desktop.mouse import MouseOutput
from .control.scroll import ScrollController, scroll_pose_status
from .control.pointer import PointerFilter, HandPointer
from .desktop.hotkeys import GlobalHotkeys
from .desktop.cursor import CursorHighlight
from .control.tracking import TrackingGuard, points_visible
from .desktop.preview import PREVIEW_TITLE, PREVIEW_FPS, open_preview, draw_preview


def main():
    """初始化设备和控制器，持续处理摄像头帧直至用户退出。"""
    # 模型位于 opencv/models，不依赖启动程序时的工作目录。
    model_path = (
        Path(__file__).resolve().parent.parent
        / "models"
        / "hand_landmarker.task"
    )

    if not model_path.is_file():
        print(f"找不到模型文件：{model_path}")
        return

    # VIDEO 模式会利用连续帧跟踪手部；阈值控制检测和跟踪的置信度。
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

    # 0 通常是系统默认摄像头；无法打开时不进入主循环。
    camera = cv2.VideoCapture(0)

    if not camera.isOpened():
        print("摄像头打开失败。")
        camera.release()
        return

    # 尝试减少摄像头缓存和处理分辨率；驱动不支持时可能忽略这些设置。
    camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    camera.set(cv2.CAP_PROP_FPS, 30)
    camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    last_timestamp = -1
    # 自动获取屏幕尺寸
    screen_width, screen_height = pyautogui.size()

    # PyAutoGUI 默认角落安全保护：把真实指针移到屏幕左上角可紧急停止。
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0

    # 独立控制器各司其职：平滑指针、解释手势、输出鼠标和保护跟踪状态。
    pointer_filter = PointerFilter(screen_width, screen_height)
    hand_pointer = HandPointer(screen_width, screen_height)

    # 从当前鼠标位置开始，避免程序刚启动时把指针跳到屏幕原点。
    current_position = pyautogui.position()
    smooth_x = float(current_position.x)
    smooth_y = float(current_position.y)
    pointer_filter.reset(smooth_x, smooth_y)

    # 默认暂停，用户明确启用后才允许手势控制电脑。
    control_enabled = False
    hand_was_present = False
    click_controller = PinchClickController()
    scroll_controller = ScrollController()
    mouse_output = MouseOutput(pyautogui)
    pointer_moving = False
    last_action = "Open fingers, then pinch"
    last_action_time = 0.0
    previous_frame_time = None
    frame_fps = 0.0
    moved_frames = 0
    action_counts = {"left": 0, "right": 0, "double_left": 0, "left_down": 0, "left_up": 0, "wheel_up": 0, "wheel_down": 0}
    # 下列界面辅助功能与手势控制分开初始化；某些 X11 功能不可用时可降级运行。
    hotkeys = GlobalHotkeys()
    highlight = CursorHighlight()
    tracking_guard = TrackingGuard()
    preview_visible = True
    next_preview_time = 0.0
    stage_ms = dict.fromkeys(("capture", "detect", "control", "preview"), 0.0)
    timing_samples = 0

    try:
        # LatestFrameCamera 在后台采集，主线程始终处理最新帧而不是旧帧队列。
        open_preview(screen_width)
        camera = LatestFrameCamera(camera)
        # detector 的上下文管理器负责释放 MediaPipe 模型资源。
        with vision.HandLandmarker.create_from_options(options) as detector:
            while True:
                loop_start = time.perf_counter()
                success, frame = camera.read()

                if not success:
                    print("摄像头断流、等待超时或画面过旧，已停止控制。")
                    break

                capture_done = time.perf_counter()
                # 镜像画面，让用户看到的左右方向更符合照镜子的直觉。
                frame = cv2.flip(frame, 1)

                # OpenCV 默认 BGR，MediaPipe 输入图像使用 RGB。
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                input_image = mp.Image(
                    image_format=mp.ImageFormat.SRGB,
                    data=rgb_frame,
                )

                # VIDEO 模式要求时间戳严格递增，单位为毫秒。
                timestamp = max(
                    int(camera.frame_time * 1000),
                    last_timestamp + 1,
                )
                last_timestamp = timestamp

                result = detector.detect_for_video(
                    input_image,
                    timestamp,
                )

                detect_done = time.perf_counter()
                now = time.monotonic()
                if previous_frame_time is not None:
                    frame_fps = 1 / max(0.001, now - previous_frame_time)
                previous_frame_time = now
                # 归一化坐标适合判断是否出画；像素坐标稍后用于距离和角度计算。
                normalized_points = (
                    [(p.x, p.y) for p in result.hand_landmarks[0]]
                    if result.hand_landmarks else None
                )
                tracking = tracking_guard.update(normalized_points, now)

                # 以下先处理手势和鼠标，再决定是否绘制预览，降低控制延迟。
                height, width = frame.shape[:2]
                motion_hint = (
                    "PAUSED: press F8 to start" if not control_enabled else
                    tracking.message if not tracking.ready else "HOLD: extend index"
                )
                movement_detail = ""
                scroll_hint = "SCROLL: " + motion_hint
                click_hint = "CLICK: " + (tracking.message if not tracking.ready else "press F8 to enable")
                if result.hand_landmarks:
                    landmarks = result.hand_landmarks[0]

                    # 只有控制已启用且关键点稳定时才计算并发送鼠标动作。
                    if control_enabled and tracking.ready:
                        if not hand_was_present:
                            position = pyautogui.position()
                            smooth_x = float(position.x)
                            smooth_y = float(position.y)
                            pointer_filter.reset(smooth_x, smooth_y)

                        # 所有距离判断共用像素坐标，避免画面宽高比影响比例。
                        points = np.array([(p.x * width, p.y * height) for p in landmarks])
                        palm_width = float(np.linalg.norm(points[5] - points[17]))
                        if palm_width >= 20:
                            left_ratio = float(np.linalg.norm(points[4] - points[8]) / palm_width)
                            right_ratio = float(np.linalg.norm(points[4] - points[12]) / palm_width)
                            double_ratio = float(np.linalg.norm(points[4] - points[16]) / palm_width)
                            drag_ratio = float(np.linalg.norm(points[4] - points[20]) / palm_width)
                            scroll_pose, scroll_reason = scroll_pose_status(
                                points, relaxed=scroll_controller.active,
                                thumb_visible=points_visible(normalized_points, (4,)),
                            )
                            # 各指独立张开准备：自然弯曲、未准备的手指不阻挡滚动；
                            # 已准备的主动捏合仍优先切换点击/拖拽。
                            if points_visible(normalized_points, (4,)):
                                action, freeze = click_controller.update(
                                    left_ratio, right_ratio, now,
                                    left_available=points_visible(normalized_points, (8,)),
                                    right_available=points_visible(normalized_points, (12,)),
                                    double_ratio=double_ratio,
                                    double_available=points_visible(normalized_points, (16,)),
                                    drag_ratio=drag_ratio,
                                    drag_available=points_visible(normalized_points, (20,)),
                                )
                            else:
                                # 拇指出画不能点击，但仍可用食指移动。
                                action = click_controller.reset()
                                freeze = action is not None
                            click_hint = (click_controller.hint if points_visible(normalized_points, (4,))
                                          else "CLICK BLOCKED: thumb outside camera")
                            scroll_allowed = (
                                scroll_pose and tracking.scroll_ready
                                and click_controller.button is None
                                and not click_controller.dragging and not freeze
                                and now - click_controller.last_click >= click_controller.POINTER_RELEASE_GUARD
                            )
                            if scroll_allowed:
                                steps, scroll_owns_input = scroll_controller.update(
                                    True, float((points[8][1] + points[12][1]) / 2),
                                    palm_width, now,
                                )
                                action, freeze = None, scroll_owns_input
                                click_hint = "SCROLL: pinch to click, or fold middle to exit"
                                scroll_hint = (
                                    "SCROLL: hold V briefly" if not scroll_controller.active else
                                    "SCROLL: move V fingertips UP/DOWN, then hold" if not scroll_controller.direction else
                                    "SCROLL: UP | fold middle to stop" if scroll_controller.direction > 0 else
                                    "SCROLL: DOWN | fold middle to stop"
                                )
                                if steps:
                                    pyautogui.scroll(steps)
                                    action_counts["wheel_up" if steps > 0 else "wheel_down"] += abs(steps)
                            else:
                                scroll_controller.reset()
                                scroll_owns_input = False
                                scroll_hint = "SCROLL: " + (
                                    scroll_reason if not scroll_pose else
                                    "required fingers outside camera" if not tracking.scroll_ready else
                                    "finish click / release drag first"
                                )
                            # 手掌移动负责相对控制指针；收起食指可锁住而不误移动。
                            if freeze:
                                hand_pointer.reset()
                                pointer_moving = False
                                motion_hint = (
                                    "SCROLL: fold middle to stop" if scroll_owns_input else
                                    click_controller.hint if click_controller.button == 'drag' else
                                    "CLICK: pointer locked"
                                )
                            else:
                                relative_target = hand_pointer.update(
                                    points, width, height, now, (smooth_x, smooth_y),
                                    dragging=click_controller.dragging
                                )
                                freeze = relative_target is None
                                if freeze:
                                    pointer_moving = False
                                    motion_hint = "HOLD: finger curled, pointer locked"
                                else:
                                    target_x, target_y = relative_target
                                    pointer_moving = True
                                    motion_hint = ("DRAGGING: release little pinch to drop" if click_controller.dragging
                                                   else "HOLD: stable pointer | move hand to resume" if hand_pointer.hover_anchor is not None
                                                   else "MOVE: move hand | small motion = precision")
                        else:
                            # 手太小或侧掌严重时不执行操作。
                            click_controller.reset()
                            scroll_controller.reset()
                            motion_hint = "Move hand closer / face palm to camera"
                            mouse_output.release()
                            hand_pointer.reset()
                            pointer_moving = False
                            action, freeze = None, True

                        movement_detail = (
                            f"L:{left_ratio:.2f} R:{right_ratio:.2f} D:{double_ratio:.2f} G:{drag_ratio:.2f} "
                            f"palm:{palm_width:.0f}px" if palm_width >= 20 else
                            f"palm:{palm_width:.0f}px (too small)"
                        )
                        mouse_output.apply(action)
                        if action in ("left_down", "left_up"):
                            position = pyautogui.position()
                            smooth_x, smooth_y = float(position.x), float(position.y)
                            pointer_filter.reset(smooth_x, smooth_y, now)
                        if not freeze:
                            smooth_x, smooth_y = pointer_filter.update(target_x, target_y, now)
                            pyautogui.moveTo(int(smooth_x), int(smooth_y))
                            moved_frames += 1
                        else:
                            pointer_filter.reset(smooth_x, smooth_y, now)

                        if action is not None:
                            action_counts[action] += 1
                            last_action = {
                                "left": "LEFT CLICK",
                                "right": "RIGHT CLICK",
                                "double_left": "LEFT DOUBLE CLICK",
                                "left_down": "DRAG STARTED",
                                "left_up": "DRAG RELEASED",
                            }[action]
                            last_action_time = now

                    else:
                        # 移动所需关键点出画或仍在恢复等待期时，停止输出并清理状态。
                        click_controller.reset()
                        scroll_controller.reset()
                        mouse_output.release()
                        hand_pointer.reset()
                        pointer_moving = False

                    hand_was_present = control_enabled and tracking.ready
                else:
                    hand_was_present = False
                    click_controller.reset()
                    scroll_controller.reset()
                    mouse_output.release()
                    hand_pointer.reset()
                    pointer_moving = False

                # 高亮箭头跟随系统鼠标；它是界面提示，不参与鼠标控制。
                if highlight.available:
                    position = pyautogui.position()
                    highlight.update(position.x, position.y)
                control_done = time.perf_counter()

                # 预览仅按 PREVIEW_FPS 刷新；隐藏时跳过绘制但识别仍继续。
                if preview_visible and time.monotonic() >= next_preview_time:
                    next_preview_time = time.monotonic() + 1 / PREVIEW_FPS
                    draw_preview(
                        frame,
                        control_enabled=control_enabled,
                        result=result,
                        click_controller=click_controller,
                        scroll_controller=scroll_controller,
                        last_action_time=last_action_time,
                        last_action=last_action,
                        pointer_moving=pointer_moving,
                        motion_hint=motion_hint,
                        pointer_filter=pointer_filter,
                        tracking=tracking,
                        frame_fps=frame_fps,
                        moved_frames=moved_frames,
                        movement_detail=movement_detail,
                        click_hint=click_hint,
                        scroll_hint=scroll_hint,
                        action_counts=action_counts,
                        stage_ms=stage_ms,
                        camera=camera,
                    )

                # 全局快捷键不依赖预览窗口；本地按键需窗口可见且被选中。
                key = (cv2.waitKey(1) & 0xFF) if preview_visible else 255
                commands = hotkeys.poll()
                if key == ord("s"):
                    commands.append("pause")
                elif key == ord("h"):
                    commands.append("preview")
                elif key == ord("q") or key == 27:
                    commands.append("quit")

                # 将快捷键统一转换为主程序命令，集中完成暂停、预览切换和退出。
                if "quit" in commands:
                    break
                if "pause" in commands:
                    control_enabled = not control_enabled
                    tracking_guard.reset()
                    hand_was_present = False
                    click_controller.reset()
                    scroll_controller.reset()
                    mouse_output.release()
                    hand_pointer.reset()
                    pointer_moving = False
                if "preview" in commands:
                    if hotkeys.available:
                        preview_visible = not preview_visible
                        if preview_visible:
                            open_preview(screen_width)
                            next_preview_time = 0.0
                        else:
                            cv2.destroyWindow(PREVIEW_TITLE)
                    else:
                        print("全局快捷键不可用，保留预览以便暂停或退出。可手动缩小窗口。")
                if key in (ord("+"), ord("=")):
                    pointer_filter.response = min(2.5, pointer_filter.response + 0.2)
                elif key == ord("-"):
                    pointer_filter.response = max(0.4, pointer_filter.response - 0.2)
                elif key == ord("]"):
                    scroll_controller.sensitivity = min(12, scroll_controller.sensitivity + 1)
                elif key == ord("["):
                    scroll_controller.sensitivity = max(2, scroll_controller.sensitivity - 1)

                # 平滑记录各阶段耗时，便于界面显示性能；不影响控制逻辑。
                durations = (
                    (capture_done - loop_start) * 1000,
                    (detect_done - capture_done) * 1000,
                    (control_done - detect_done) * 1000,
                    (time.perf_counter() - control_done) * 1000,
                )
                weight = 1.0 if timing_samples == 0 else 0.1
                for name, duration in zip(stage_ms, durations):
                    stage_ms[name] += weight * (duration - stage_ms[name])
                timing_samples += 1

    # 所有退出途径都走 finally，确保鼠标按键、线程、窗口和 X11 连接清理。
    except pyautogui.FailSafeException:
        print("鼠标到达屏幕角落，已触发安全停止。")
    except KeyboardInterrupt:
        print("程序已停止。")
    finally:
        try:
            mouse_output.release()
        finally:
            hotkeys.close()
            highlight.close()
            camera.release()
            cv2.destroyAllWindows()
            if timing_samples:
                print("[平均耗时 ms] 摄像头={capture:.1f} 识别预处理={detect:.1f} "
                      "控制={control:.1f} 预览事件={preview:.1f}".format(**stage_ms))
