"""文档扫描预处理：自动检测、原图透视矫正、光照归一化。"""
import argparse
from pathlib import Path

import cv2
import numpy as np


def read_image(path):
    # imdecode 支持中文文件路径。
    image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"无法解码图片：{path}")
    return image


def save_image(path, image):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, encoded = cv2.imencode(path.suffix, image)
    if not ok:
        raise ValueError(f"无法编码图片：{path}")
    encoded.tofile(str(path))


def order_points(points):
    """按左上、右上、右下、左下排列；避免和/差法在菱形处重复选点。"""
    points = np.asarray(points, dtype=np.float32).reshape(4, 2)
    if not np.isfinite(points).all() or len(np.unique(points, axis=0)) != 4:
        raise ValueError("需要四个不同的有效角点")
    center = points.mean(axis=0)
    angles = np.arctan2(points[:, 1] - center[1], points[:, 0] - center[0])
    points = points[np.argsort(angles)]
    points = np.roll(points, -int(np.argmin(points.sum(axis=1))), axis=0)
    contour = points.reshape(-1, 1, 2)
    if not cv2.isContourConvex(contour) or cv2.contourArea(contour) < 25:
        raise ValueError("四点必须构成面积足够的凸四边形")
    return points


def detect_document(image, max_side=1400, min_area_ratio=0.15):
    h, w = image.shape[:2]
    scale = min(1.0, max_side / max(h, w))
    small = cv2.resize(image, (max(1, round(w * scale)), max(1, round(h * scale))))
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    # 亮纸张掩膜可补充弱边缘；保留内部轮廓，以便背景框中仍能找到纸张。
    _, bright = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    candidates = []
    sh, sw = gray.shape
    for mask in (edges, bright):
        contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            if cv2.contourArea(contour) < sh * sw * min_area_ratio:
                continue
            perimeter = cv2.arcLength(contour, True)
            for epsilon in (0.015, 0.025, 0.04):
                polygon = cv2.approxPolyDP(contour, epsilon * perimeter, True)
                if len(polygon) != 4 or not cv2.isContourConvex(polygon):
                    continue
                points = polygon.reshape(4, 2).astype(np.float32)
                # 整张照片的外框不是文档检测结果。
                touches = ((points[:, 0] <= 2) | (points[:, 0] >= sw - 3)
                           | (points[:, 1] <= 2) | (points[:, 1] >= sh - 3))
                if touches.all():
                    continue
                try:
                    ordered = order_points(points)
                except ValueError:
                    continue
                area = cv2.contourArea(ordered)
                if area < sh * sw * min_area_ratio:
                    continue
                if np.min(np.linalg.norm(ordered - np.roll(ordered, 1, axis=0), axis=1)) < 20:
                    continue
                candidates.append((area, ordered))
                break
    if not candidates:
        return None, edges
    points = max(candidates, key=lambda item: item[0])[1]
    # 分别使用实际缩放比例，消除 resize 整数取整引入的偏差。
    return points * np.array([w / sw, h / sh], dtype=np.float32), edges


def warp_document(image, points):
    points = order_points(points)
    tl, tr, br, bl = points
    width = round(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl)))
    height = round(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr)))
    if min(width, height) < 5:
        raise ValueError("文档区域太小")
    destination = np.float32([[0, 0], [width - 1, 0],
                              [width - 1, height - 1], [0, height - 1]])
    matrix = cv2.getPerspectiveTransform(points, destination)
    return cv2.warpPerspective(image, matrix, (width, height), flags=cv2.INTER_CUBIC)


def enhance_document(image, block_size=41, threshold_c=12):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    # 低分辨率估计缓慢变化的光照，膨胀抑制黑色文字，再放大回原图。
    h, w = gray.shape
    scale = min(1.0, 1000 / max(h, w))
    small = cv2.resize(gray, (max(1, round(w * scale)), max(1, round(h * scale))))
    background = cv2.dilate(small, np.ones((15, 15), np.uint8))
    background = cv2.GaussianBlur(background, (0, 0), 15)
    background = cv2.resize(background, (w, h))
    normalized = cv2.divide(gray, np.maximum(background, 1), scale=255)
    normalized = cv2.medianBlur(normalized, 3)
    binary = cv2.adaptiveThreshold(normalized, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                   cv2.THRESH_BINARY, block_size, threshold_c)
    return normalized, binary


def select_points(image):
    """点击四角，Enter 确认，R 重选，Esc 取消。需要桌面 GUI 版 OpenCV。"""
    h, w = image.shape[:2]
    scale = min(1.0, 1200 / w, 800 / h)
    preview = cv2.resize(image, (max(1, round(w * scale)), max(1, round(h * scale))))
    points = []
    window = "Select 4 corners | Enter: confirm | R: reset | Esc: cancel"

    def on_mouse(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN and len(points) < 4:
            points.append((x, y))

    try:
        cv2.namedWindow(window, cv2.WINDOW_AUTOSIZE)
        cv2.setMouseCallback(window, on_mouse)
        while True:
            canvas = preview.copy()
            for index, (x, y) in enumerate(points):
                cv2.circle(canvas, (x, y), 6, (0, 0, 255), -1)
                cv2.putText(canvas, str(index + 1), (x + 8, y),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            cv2.imshow(window, canvas)
            key = cv2.waitKey(30) & 0xFF
            if key == 27 or cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1:
                raise ValueError("已取消手动选点")
            if key in (ord('r'), ord('R')):
                points.clear()
            if key in (10, 13) and len(points) == 4:
                factor = np.float32([w / preview.shape[1], h / preview.shape[0]])
                return order_points(np.float32(points) * factor)
    finally:
        cv2.destroyAllWindows()


def parse_points(value):
    try:
        return order_points([[float(v) for v in pair.split(',')] for pair in value.split(';')])
    except (ValueError, TypeError) as exc:
        raise argparse.ArgumentTypeError('格式应为 "x1,y1;x2,y2;x3,y3;x4,y4"') from exc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path, help='输入图片路径')
    parser.add_argument('-o', '--output-dir', type=Path, default=Path('output'))
    parser.add_argument('--manual', action='store_true', help='打开鼠标选四点窗口')
    parser.add_argument('--points', type=parse_points, help='原图四点坐标，适用于无桌面环境')
    parser.add_argument('--block-size', type=int, default=41, help='自适应阈值邻域，奇数且 >= 3')
    parser.add_argument('--threshold-c', type=float, default=12, help='自适应阈值偏移')
    args = parser.parse_args()
    if args.block_size < 3 or args.block_size % 2 == 0:
        parser.error('--block-size 必须为 >= 3 的奇数')
    if args.manual and args.points is not None:
        parser.error('--manual 与 --points 不能同时使用')
    try:
        image = read_image(args.input)
        points, edges = detect_document(image)
        save_image(args.output_dir / 'edges.png', edges)
        if args.points is not None:
            points = args.points
        elif args.manual:
            points = select_points(image)
        if points is None:
            raise ValueError('未找到可靠的文档四边形，请使用 --manual 或 --points 指定四角')
        h, w = image.shape[:2]
        if ((points < 0).any() or (points[:, 0] > w - 1).any()
                or (points[:, 1] > h - 1).any()):
            raise ValueError('角点超出原图范围')
        overlay = image.copy()
        cv2.polylines(overlay, [points.astype(np.int32)], True, (0, 255, 0), 3)
        color = warp_document(image, points)
        gray, binary = enhance_document(color, args.block_size, args.threshold_c)
        for name, result in [('detected', overlay), ('color', color),
                             ('gray', gray), ('scan', binary)]:
            save_image(args.output_dir / f'{name}.png', result)
        print(f'扫描完成：{args.output_dir.resolve() / "scan.png"}')
        print(f'输出尺寸：{color.shape[1]} × {color.shape[0]}，请检查 detected.png 中的四角。')
    except (OSError, ValueError, cv2.error) as exc:
        parser.exit(1, f'处理失败：{exc}\n')


if __name__ == '__main__':
    main()
