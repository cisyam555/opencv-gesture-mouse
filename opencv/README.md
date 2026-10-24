# 手势鼠标：启动与源码导航

本目录是程序运行目录。完整的功能介绍、安装、手势、原理、参数、验证步骤与常见问题见[项目 README](../README.md)。

## 本机已有环境快速启动

下面的绝对路径对应开发者本机，其他设备按实际克隆位置替换：

```bash
cd "/home/cisyam/文档/ChatGPT/opencv项目/opencv"
source .venv/bin/activate
python main.py
```

版本演进及实现顺序见[项目 README 的版本说明](../README.md#版本演进)。

## 启动

首次使用请先按项目 README 安装依赖，并下载模型到 `models/hand_landmarker.task`。

已有环境时，在本目录执行：

```bash
source .venv/bin/activate
python main.py
```

程序默认暂停，**F8** 开始 / 暂停，**F9** 隐藏 / 显示预览，**F10** 退出。修改源码后退出旧程序，再重新启动。

## 手势速查

| 功能 | 操作 |
| --- | --- |
| 移动 / 停住 | 伸食指并移动手掌 / 收起食指 |
| 左键单击 | 拇指＋食指捏合，再松开 |
| 右键单击 | 拇指＋中指捏合，再松开 |
| 左键双击 | 拇指＋无名指捏合，再松开 |
| 拖拽 | 拇指＋小指捏合约 0.30 秒，出现 `DRAGGING` 后移动；松开放下 |
| 网页下滚 / 上滚 | 食指、中指伸出，其余两指自然弯曲；双指指尖下移 / 上移一点，再保持 |
| 停止滚动 | 收起中指 |

捏合前先张开对应手指准备。拇指可以自然放松；主动准备后的捏合优先于滚动。滚动前把指针放在网页正文，先验证向下滚，观察 `WHEEL SENT` 的 `DOWN` 是否增加。

## 从哪里看代码

| 位置 | 职责 |
| --- | --- |
| [main.py](main.py) | 唯一启动入口 |
| [gesture_mouse/app.py](gesture_mouse/app.py) | 采集 → 识别 → 操作互斥 → 输出 → 显示 |
| [gesture_mouse/camera.py](gesture_mouse/camera.py) | 摄像头后台最新帧采集与超时处理 |
| [control/gestures.py](gesture_mouse/control/gestures.py) | 单击、双击、小指拖拽状态机 |
| [control/pointer.py](gesture_mouse/control/pointer.py) | 手掌相对移动、防抖、收指保护和悬停 |
| [control/scroll.py](gesture_mouse/control/scroll.py) | 双指姿势、滚动方向和连续滚轮 |
| [control/tracking.py](gesture_mouse/control/tracking.py) | 必要关键点可见性及恢复等待 |
| [desktop/](gesture_mouse/desktop/) | 系统鼠标、预览、绿色箭头和全局快捷键 |

阅读顺序：**入口 → 主流程 → 捏合状态机 → 指针移动 → 滚动 → 桌面辅助**。

`models/` 是本地模型，`.venv/` 是第三方环境，`__pycache__/` 是运行缓存，均不提交到 Git。
