from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory

import numpy as np
import uvicorn

PROJECT_PATH = Path(__file__).resolve().parent.parent
if str(PROJECT_PATH) not in sys.path:
    sys.path.insert(0, str(PROJECT_PATH))

from model_automation.config import ConfigStore, PROJECT_ROOT
from model_automation.models import AppConfig, Preset, Step
from model_automation.vision import save_image
from web_server import create_app


class FakeDevice:
    def __init__(self) -> None:
        y, x = np.indices((720, 1280))
        self.screen = np.dstack(
            (
                (x // 5) % 255,
                (y // 3) % 255,
                ((x + y) // 7) % 255,
            )
        ).astype(np.uint8)

    def state(self) -> str:
        return "device"

    def screenshot(self) -> np.ndarray:
        return self.screen.copy()

    def screen_resolution(self) -> tuple[int, int]:
        return 1280, 720

    def tap(self, _x: int, _y: int) -> None:
        pass

    def swipe(
        self,
        _x1: int,
        _y1: int,
        _x2: int,
        _y2: int,
        _duration: int,
    ) -> None:
        pass


temporary = TemporaryDirectory()
root = Path(temporary.name)
store = ConfigStore(root / "config.json", root / "templates_file")
store.template_dir.mkdir(parents=True, exist_ok=True)
save_image(store.template_dir / "branch.png", np.full((20, 30, 3), 127, dtype=np.uint8))
wait = Step(name="等待停止验证", kind="wait", params={"seconds": 30})
tap = Step(
    name="截图坐标验证",
    kind="tap",
    params={"x": 640, "y": 360, "wait_after": 0},
    depends_on=[wait.id],
    screen_resolution=(1280, 720),
)
resume = Step(name="恢复默认流程", kind="wait", params={"seconds": 0})
branch_step = Step(name="模板命中分支", kind="end_loop")
recognition = Step(
    name="模板分支验证",
    kind="find_and_tap",
    params={
        "templates": [{"file": "branch.png", "threshold": 0.8}],
        "branches": {"0": [branch_step.to_dict()]},
    },
    screen_resolution=(1280, 720),
)
preset = Preset(name="浏览器联调验收", steps=[wait, tap, resume, recognition])
alternate_wait = Step(name="备用流程等待", kind="wait", params={"seconds": 1})
alternate_tap = Step(name="备用流程点击", kind="tap", params={"x": 320, "y": 180, "wait_after": 0})
alternate = Preset(name="切换预设验收", steps=[alternate_wait, alternate_tap])
store.save(AppConfig(presets=[preset, alternate], selected_preset_id=preset.id))
app = create_app(
    config_store=store,
    device=FakeDevice(),
    static_dir=PROJECT_ROOT / "web" / "dist",
)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8002, log_level="info")
