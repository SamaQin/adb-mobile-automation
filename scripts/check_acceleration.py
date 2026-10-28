r"""Run with .venv\Scripts\python.exe scripts/check_acceleration.py.

Uses reproducible images and optional read-only device screenshot. Does not save
configuration, templates, or screenshots. Timings include synchronized result
readback. OpenCL activation does not prove that every internal kernel used GPU.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import json
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import cv2
import numpy as np
from model_automation import vision
from model_automation.device import AdbClient


def sample(action, count):
    durations = []
    for _ in range(3):
        action()
    for _ in range(count):
        start = time.perf_counter()
        action()
        durations.append((time.perf_counter() - start) * 1000)
    return {'median_ms': round(statistics.median(durations), 3),
            'min_ms': round(min(durations), 3), 'samples': count}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', help='Optional authorized device to capture once; no touch input')
    parser.add_argument('--samples', type=int, default=12)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.samples < 1:
        parser.error('--samples must be positive')
    rng = np.random.default_rng(173)
    cases = []
    for width, height, tw, th in [(320, 480, 12, 12), (320, 480, 40, 40), (720, 1280, 80, 80), (1116, 2480, 120, 80)]:
        image = rng.integers(0, 255, (height, width, 3), dtype=np.uint8)
        left, top = width // 3, height // 3
        cases.append((f'synthetic-{width}x{height}-template-{tw}x{th}', image, image[top:top+th, left:left+tw].copy()))
    device_error = None
    if args.serial:
        try:
            adb = AdbClient(ROOT)
            adb.select_device(args.serial)
            image = adb.screenshot()
            height, width = image.shape[:2]
            left, top = width // 3, height // 3
            cases.append(('phone-screenshot', image, image[top:top+80, left:left+120].copy()))
        except Exception as exc:
            device_error = str(exc)
    report = {'opencv': cv2.__version__, 'optimized': cv2.useOptimized(),
              'cpu_threads': cv2.getNumThreads(), 'cuda_devices': cv2.cuda.getCudaEnabledDeviceCount(),
              'cuda_matcher_available': hasattr(cv2.cuda, 'createTemplateMatching'),
              'have_opencl': cv2.ocl.haveOpenCL(), 'device_capture_error': device_error,
              'note': 'OpenCL context and GPU device verified; OpenCV may internally fall back for individual operators. Timings cover matching/result readback and CPU candidate processing, not ADB capture.',
              'cases': []}
    # Reuse one worker to exercise context transitions across mode changes.
    with ThreadPoolExecutor(max_workers=1) as executor:
        for name, image, template in cases:
            gray, template_gray = vision.to_gray(image), vision.to_gray(template)
            values = {'name': name, 'screen': [image.shape[1], image.shape[0]],
                      'template': [template.shape[1], template.shape[0]], 'modes': []}
            baseline = None
            for requested in ['cpu', 'gpu', 'cpu']:
                applied = vision.set_acceleration(requested)
                def run():
                    result = vision._compute_match_result(gray, template_gray)
                    match = vision.find_template(gray, template_gray, .99)
                    return result, match
                result, match = executor.submit(run).result()
                if baseline is None:
                    baseline = result.copy()
                def measure():
                    compute = sample(lambda: vision._compute_match_result(gray, template_gray), args.samples)
                    complete = sample(lambda: vision.find_template(gray, template_gray, .99), args.samples)
                    color = sample(lambda: vision.find_template(image, template, .99), args.samples)
                    return compute, complete, color, cv2.ocl.useOpenCL()
                compute, complete, color, enabled = executor.submit(measure).result()
                item = {'requested': requested, 'applied': applied, 'mode_after': vision.get_acceleration(),
                        'backend': vision.acceleration_backend(), 'worker_opencl': enabled,
                        'compute': compute, 'gray_pipeline': complete, 'color_pipeline': color,
                        'max_score_difference': float(np.max(np.abs(baseline-result))),
                        'match': {key: float(value) if key == 'score' else int(value) for key, value in asdict(match).items()} if match else None}
                if requested == 'gpu' and enabled:
                    def info():
                        device = cv2.ocl.Device_getDefault()
                        return {'name': device.name(), 'vendor': device.vendorName(), 'version': device.version(),
                                'gpu_type': bool(device.type() & cv2.ocl.Device_TYPE_GPU)}
                    report['opencl_device'] = executor.submit(info).result()
                values['modes'].append(item)
            report['cases'].append(values)
    vision.set_acceleration('cpu')
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding='utf-8')
    print(text)


if __name__ == '__main__':
    main()
