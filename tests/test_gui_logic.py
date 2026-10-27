import unittest

from model_automation.gui import reorder_steps
from model_automation.models import Preset, Step


class StepOrderingTests(unittest.TestCase):
    def test_reorder_steps_applies_requested_order(self) -> None:
        first = Step(name="第一步", kind="wait")
        second = Step(name="第二步", kind="wait")
        third = Step(name="第三步", kind="wait")
        preset = Preset(name="预设", steps=[first, second, third])

        changed = reorder_steps(preset, [third.id, first.id, second.id])

        self.assertTrue(changed)
        self.assertEqual([third.id, first.id, second.id], [step.id for step in preset.steps])

    def test_reorder_steps_removes_forward_dependencies(self) -> None:
        first = Step(name="第一步", kind="wait")
        second = Step(name="第二步", kind="wait", depends_on=[first.id])
        preset = Preset(name="预设", steps=[first, second])

        reorder_steps(preset, [second.id, first.id])

        self.assertEqual([], second.depends_on)

    def test_reorder_steps_rejects_unknown_ids(self) -> None:
        step = Step(name="步骤", kind="wait")
        preset = Preset(name="预设", steps=[step])

        with self.assertRaises(ValueError):
            reorder_steps(preset, ["unknown"])


if __name__ == "__main__":
    unittest.main()
