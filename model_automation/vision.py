from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np


ACCELERATION_CPU = "cpu"
ACCELERATION_GPU = "gpu"
ACCELERATION_LABELS = {
    ACCELERATION_CPU: "CPU 加速",
    ACCELERATION_GPU: "GPU 加速",
}

_ACCELERATION = ACCELERATION_CPU
_GPU_BACKEND: str | None = None
_CUDA_MATCHER: Any = None


@dataclass(frozen=True)
class Match:
    x: int
    y: int
    score: float


def _cuda_error() -> tuple[type[BaseException], ...]:
    return (cv2.error, SystemError, RuntimeError)


def _probe_cuda_matcher() -> bool:
    if not hasattr(cv2, "cuda") or not hasattr(cv2.cuda, "createTemplateMatching"):
        return False
    try:
        if cv2.cuda.getCudaEnabledDeviceCount() <= 0:
            return False
        matcher = cv2.cuda.createTemplateMatching(
            cv2.CV_32F, cv2.TM_CCOEFF_NORMED
        )
        template = np.zeros((8, 8), dtype=np.float32)
        image = np.zeros((16, 16), dtype=np.float32)
        result = matcher.match(
            cv2.cuda_GpuMat(template), cv2.cuda_GpuMat(image)
        )
        return result.download().shape == (9, 9)
    except _cuda_error():
        return False


def _probe_opencl() -> bool:
    cv2.ocl.setUseOpenCL(True)
    if not cv2.ocl.haveOpenCL():
        return False
    try:
        small = np.zeros((16, 16), dtype=np.uint8)
        result = cv2.matchTemplate(
            cv2.UMat(small), cv2.UMat(small), cv2.TM_CCOEFF_NORMED
        )
        return result.get().shape == (1, 1)
    except cv2.error:
        cv2.ocl.setUseOpenCL(False)
        return False


def set_acceleration(mode: str) -> str:
    """切换加速模式，返回实际生效的模式（GPU 不可用时回退到 CPU）。"""
    global _ACCELERATION, _GPU_BACKEND, _CUDA_MATCHER
    if mode not in ACCELERATION_LABELS:
        raise ValueError(f"不支持的加速模式：{mode}")
    cv2.setUseOptimized(True)
    cv2.ocl.setUseOpenCL(False)
    _ACCELERATION = ACCELERATION_CPU
    _GPU_BACKEND = None
    _CUDA_MATCHER = None
    if mode == ACCELERATION_GPU:
        if _probe_cuda_matcher():
            _ACCELERATION = ACCELERATION_GPU
            _GPU_BACKEND = "cuda"
            _CUDA_MATCHER = cv2.cuda.createTemplateMatching(
                cv2.CV_32F, cv2.TM_CCOEFF_NORMED
            )
        elif _probe_opencl():
            _ACCELERATION = ACCELERATION_GPU
            _GPU_BACKEND = "ocl"
    return _ACCELERATION


def get_acceleration() -> str:
    return _ACCELERATION


def acceleration_backend() -> str | None:
    return _GPU_BACKEND


def load_image(path: Path) -> np.ndarray | None:
    try:
        data = np.fromfile(path, dtype=np.uint8)
    except OSError:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def save_image(path: Path, image: np.ndarray) -> None:
    extension = path.suffix or ".png"
    success, encoded = cv2.imencode(extension, image)
    if not success:
        raise OSError(f"无法编码图片: {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded.tofile(path)


def _compute_match_result(
    screen_gray: np.ndarray, template_gray: np.ndarray
) -> np.ndarray:
    if _ACCELERATION == ACCELERATION_GPU:
        try:
            if _GPU_BACKEND == "cuda" and _CUDA_MATCHER is not None:
                result = _CUDA_MATCHER.match(
                    cv2.cuda_GpuMat(template_gray.astype(np.float32)),
                    cv2.cuda_GpuMat(screen_gray.astype(np.float32)),
                )
                return result.download()
            if _GPU_BACKEND == "ocl":
                result = cv2.matchTemplate(
                    cv2.UMat(screen_gray),
                    cv2.UMat(template_gray),
                    cv2.TM_CCOEFF_NORMED,
                )
                return result.get()
        except _cuda_error():
            pass
    return cv2.matchTemplate(
        screen_gray, template_gray, cv2.TM_CCOEFF_NORMED
    )


def _collect_matches(
    result: np.ndarray,
    threshold: float,
    template_width: int,
    template_height: int,
) -> Match | None:
    kernel = np.ones(
        (max(1, template_height), max(1, template_width)),
        dtype=np.uint8,
    )
    local_maximum = cv2.dilate(result, kernel)
    candidate_mask = np.logical_and(
        result >= threshold,
        result >= local_maximum - 1e-12,
    ).astype(np.uint8)
    component_count, labels, stats, _ = cv2.connectedComponentsWithStats(
        candidate_mask,
        connectivity=8,
    )
    candidates: list[Match] = []
    for component in range(1, component_count):
        left, top, width, height, _ = stats[component]
        component_scores = result[top : top + height, left : left + width].copy()
        component_labels = labels[top : top + height, left : left + width]
        component_scores[component_labels != component] = -1.0
        _, maximum, _, location = cv2.minMaxLoc(component_scores)
        candidates.append(
            Match(
                x=left + location[0] + template_width // 2,
                y=top + location[1] + template_height // 2,
                score=float(maximum),
            )
        )
    return min(candidates, key=lambda match: (match.y, match.x)) if candidates else None


def find_template(
    screen: np.ndarray,
    template: np.ndarray,
    threshold: float,
) -> Match | None:
    screen_gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
    template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
    screen_height, screen_width = screen_gray.shape
    template_height, template_width = template_gray.shape
    if template_height > screen_height or template_width > screen_width:
        return None

    result = _compute_match_result(screen_gray, template_gray)
    return _collect_matches(result, threshold, template_width, template_height)


def fit_image_to_bounds(
    image: np.ndarray,
    max_width: int,
    max_height: int,
) -> tuple[np.ndarray, float]:
    image_height, image_width = image.shape[:2]
    if image_width <= 0 or image_height <= 0:
        raise ValueError("图片尺寸无效")
    scale = min(
        1.0,
        max(1, max_width) / image_width,
        max(1, max_height) / image_height,
    )
    if scale >= 1.0:
        return image.copy(), 1.0
    display_width = max(1, round(image_width * scale))
    display_height = max(1, round(image_height * scale))
    display = cv2.resize(
        image,
        (display_width, display_height),
        interpolation=cv2.INTER_AREA,
    )
    return display, scale


def select_region(
    title: str,
    image: np.ndarray,
    max_width: int = 1280,
    max_height: int = 720,
) -> tuple[int, int, int, int] | None:
    display, _scale = fit_image_to_bounds(image, max_width, max_height)
    x, y, width, height = cv2.selectROI(
        title, display, showCrosshair=True, fromCenter=False
    )
    cv2.destroyAllWindows()
    if width <= 0 or height <= 0:
        return None
    image_height, image_width = image.shape[:2]
    scale_x = display.shape[1] / image_width
    scale_y = display.shape[0] / image_height
    left = min(image_width - 1, max(0, round(x / scale_x)))
    top = min(image_height - 1, max(0, round(y / scale_y)))
    right = min(image_width, max(left + 1, round((x + width) / scale_x)))
    bottom = min(image_height, max(top + 1, round((y + height) / scale_y)))
    return left, top, right - left, bottom - top


def select_point(
    title: str,
    image: np.ndarray,
    max_width: int = 1280,
    max_height: int = 720,
) -> tuple[int, int] | None:
    image_height, image_width = image.shape[:2]
    display, _scale = fit_image_to_bounds(image, max_width, max_height)
    scale_x = display.shape[1] / image_width
    scale_y = display.shape[0] / image_height

    cursor = [display.shape[1] // 2, display.shape[0] // 2]
    selected: list[tuple[int, int]] = []

    def original_position(x: int, y: int) -> tuple[int, int]:
        original_x = min(image_width - 1, max(0, round(x / scale_x)))
        original_y = min(image_height - 1, max(0, round(y / scale_y)))
        return original_x, original_y

    def mouse_callback(event: int, x: int, y: int, _flags: int, _data: object) -> None:
        if event in {cv2.EVENT_MOUSEMOVE, cv2.EVENT_LBUTTONDOWN}:
            cursor[0], cursor[1] = x, y
        if event == cv2.EVENT_LBUTTONDOWN:
            selected.append(original_position(x, y))

    cv2.namedWindow(title, cv2.WINDOW_AUTOSIZE)
    cv2.setMouseCallback(title, mouse_callback)
    try:
        while True:
            canvas = display.copy()
            x, y = cursor
            original_x, original_y = original_position(x, y)
            cv2.line(canvas, (x, 0), (x, canvas.shape[0] - 1), (0, 220, 255), 1)
            cv2.line(canvas, (0, y), (canvas.shape[1] - 1, y), (0, 220, 255), 1)
            label = f"X: {original_x}  Y: {original_y}"
            label_x = min(max(8, x + 12), max(8, canvas.shape[1] - 170))
            label_y = min(max(24, y - 12), max(24, canvas.shape[0] - 8))
            cv2.rectangle(
                canvas,
                (label_x - 5, label_y - 19),
                (label_x + 158, label_y + 5),
                (20, 20, 20),
                -1,
            )
            cv2.putText(
                canvas,
                label,
                (label_x, label_y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (255, 255, 255),
                1,
                cv2.LINE_AA,
            )
            if selected:
                cv2.circle(canvas, (x, y), 7, (40, 220, 40), 2)
            cv2.imshow(title, canvas)

            key = cv2.waitKey(20) & 0xFF
            if selected:
                cv2.waitKey(120)
                return selected[-1]
            if key == 27 or cv2.getWindowProperty(title, cv2.WND_PROP_VISIBLE) < 1:
                return None
    finally:
        try:
            cv2.destroyWindow(title)
        except cv2.error:
            pass


def select_swipe(
    title: str,
    image: np.ndarray,
    max_width: int = 1280,
    max_height: int = 720,
) -> tuple[int, int, int, int] | None:
    image_height, image_width = image.shape[:2]
    display, _scale = fit_image_to_bounds(image, max_width, max_height)
    scale_x = display.shape[1] / image_width
    scale_y = display.shape[0] / image_height
    start: list[tuple[int, int]] = []
    cursor = [display.shape[1] // 2, display.shape[0] // 2]
    selected: list[tuple[tuple[int, int], tuple[int, int]]] = []

    def original_position(x: int, y: int) -> tuple[int, int]:
        original_x = min(image_width - 1, max(0, round(x / scale_x)))
        original_y = min(image_height - 1, max(0, round(y / scale_y)))
        return original_x, original_y

    def mouse_callback(event: int, x: int, y: int, _flags: int, _data: object) -> None:
        if event == cv2.EVENT_LBUTTONDOWN:
            start.clear()
            start.append((x, y))
            cursor[0], cursor[1] = x, y
            selected.clear()
        elif event == cv2.EVENT_MOUSEMOVE:
            cursor[0], cursor[1] = x, y
        elif event == cv2.EVENT_LBUTTONUP and start:
            cursor[0], cursor[1] = x, y
            if (x, y) != start[0]:
                selected.append((start[0], (x, y)))

    cv2.namedWindow(title, cv2.WINDOW_AUTOSIZE)
    cv2.setMouseCallback(title, mouse_callback)
    try:
        while True:
            canvas = display.copy()
            if start:
                cv2.arrowedLine(
                    canvas,
                    start[0],
                    (cursor[0], cursor[1]),
                    (0, 220, 255),
                    2,
                    cv2.LINE_AA,
                    tipLength=0.04,
                )
                start_x, start_y = original_position(*start[0])
                end_x, end_y = original_position(cursor[0], cursor[1])
                label = f"({start_x}, {start_y}) -> ({end_x}, {end_y})"
                cv2.rectangle(canvas, (8, 8), (318, 38), (20, 20, 20), -1)
                cv2.putText(
                    canvas,
                    label,
                    (14, 30),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.55,
                    (255, 255, 255),
                    1,
                    cv2.LINE_AA,
                )
            cv2.imshow(title, canvas)

            key = cv2.waitKey(20) & 0xFF
            if selected:
                cv2.waitKey(120)
                display_start, display_end = selected[-1]
                x1, y1 = original_position(*display_start)
                x2, y2 = original_position(*display_end)
                return x1, y1, x2, y2
            if key == 27 or cv2.getWindowProperty(title, cv2.WND_PROP_VISIBLE) < 1:
                return None
    finally:
        try:
            cv2.destroyWindow(title)
        except cv2.error:
            pass
