import unittest

from model_automation.models import AppConfig, Preset, Step
from model_automation.operations import (
    ValidationError,
    clone_preset,
    clone_step,
    config_from_payload,
    iter_steps,
    normalize_dependencies,
    run_preset_references,
    template_references,
    template_reference_index,
    update_template_reference_resolutions,
)
from model_automation.steps import step_definitions


def recognition(name: str, branches: dict[str, list[dict]] | None = None) -> Step:
    params = {"templates": [{"file": "target.png", "threshold": 0.8}]}
    if branches is not None:
        params["branches"] = branches
    return Step(
        name=name,
        kind="find_and_tap",
        params=params,
        screen_resolution=(100, 200),
    )


class RecursiveOperationTests(unittest.TestCase):
    def test_template_index_deduplicates_steps_and_includes_nested_references(self):
        nested = recognition("nested")
        root = recognition("root", {"0": [nested.to_dict()]})
        root.params["templates"] += [{"file": "TARGET.PNG"}, {"file": "other.png"}]
        owner = Preset(name="owner", steps=[root])
        index = template_reference_index(iter([owner]))
        self.assertEqual({"target.png", "other.png"}, set(index))
        self.assertEqual(["root", "nested"], [item["step_name"] for item in index["target.png"]])
        self.assertEqual(["root"], [item["step_name"] for item in index["other.png"]])
        self.assertEqual(index["target.png"], template_references([owner], "TARGET.PNG"))
        self.assertEqual([], template_references([owner], "absent.png"))

    def test_clone_preset_remaps_nested_ids_and_dependencies(self) -> None:
        nested_first = Step(name="nested first", kind="wait")
        nested_second = Step(
            name="nested second", kind="wait", depends_on=[nested_first.id]
        )
        branch_first = Step(name="branch first", kind="wait")
        branch_second = recognition(
            "branch second",
            {"0": [nested_first.to_dict(), nested_second.to_dict()]},
        )
        branch_second.depends_on = [branch_first.id]
        root = recognition(
            "root", {"0": [branch_first.to_dict(), branch_second.to_dict()]}
        )
        preset = Preset(name="source", steps=[root])

        cloned = clone_preset(preset, name="copy")

        original_ids = {step.id for step in iter_steps(preset)}
        cloned_steps = list(iter_steps(cloned))
        self.assertTrue(original_ids.isdisjoint({step.id for step in cloned_steps}))
        self.assertEqual("copy", cloned.name)
        cloned_branch_first = cloned_steps[1]
        cloned_branch_second = cloned_steps[2]
        cloned_nested_first = cloned_steps[3]
        cloned_nested_second = cloned_steps[4]
        self.assertEqual([cloned_branch_first.id], cloned_branch_second.depends_on)
        self.assertEqual([cloned_nested_first.id], cloned_nested_second.depends_on)

    def test_clone_step_preserves_external_dependency_and_remaps_branches(self) -> None:
        first = Step(name="first", kind="wait")
        second = Step(name="second", kind="wait", depends_on=[first.id])
        source = recognition("source", {"0": [first.to_dict(), second.to_dict()]})
        source.depends_on = ["external"]

        cloned = clone_step(source, name="source copy")
        cloned_steps = list(iter_steps(cloned))

        self.assertEqual(["external"], cloned.depends_on)
        self.assertEqual([cloned_steps[1].id], cloned_steps[2].depends_on)
        self.assertNotEqual(first.id, cloned_steps[1].id)

    def test_normalize_dependencies_is_recursive(self) -> None:
        branch_first = Step(name="first", kind="wait", depends_on=["ghost"])
        branch_second = Step(
            name="second",
            kind="wait",
            depends_on=[branch_first.id, branch_first.id, "ghost"],
        )
        root = recognition(
            "root", {"0": [branch_first.to_dict(), branch_second.to_dict()]}
        )
        preset = Preset(name="preset", steps=[root])

        normalize_dependencies(preset)

        normalized = list(iter_steps(preset))
        self.assertEqual([], normalized[1].depends_on)
        self.assertEqual([normalized[1].id], normalized[2].depends_on)

    def test_reference_scans_include_nested_branches(self) -> None:
        target = Preset(name="target")
        branch = Step(
            name="run nested",
            kind="run_preset",
            params={"preset_id": target.id, "preset_name": target.name},
        )
        root = recognition("root", {"0": [branch.to_dict()]})
        owner = Preset(name="owner", steps=[root])

        preset_refs = run_preset_references([owner, target], target.id)
        template_refs = template_references([owner, target], "TARGET.PNG")

        self.assertEqual("run nested", preset_refs[0]["step_name"])
        self.assertEqual("root", template_refs[0]["step_name"])

    def test_template_resolution_update_is_recursive(self) -> None:
        nested = recognition("nested")
        root = recognition("root", {"0": [nested.to_dict()]})
        owner = Preset(name="owner", steps=[root])

        updated = update_template_reference_resolutions(
            [owner], "TARGET.PNG", (200, 400)
        )

        self.assertEqual(2, updated)
        self.assertEqual(
            {"width": 200, "height": 400},
            owner.steps[0].params["templates"][0]["screen_resolution"],
        )
        nested_raw = owner.steps[0].params["branches"]["0"][0]
        self.assertEqual(
            {"width": 200, "height": 400},
            nested_raw["params"]["templates"][0]["screen_resolution"],
        )


class ConfigValidationTests(unittest.TestCase):
    def test_legacy_multi_tap_is_migrated_to_merged_recognition_step(self) -> None:
        legacy = Step(
            name="legacy multi",
            kind="find_and_multi_tap",
            params={
                "templates": [{"file": "target.png", "threshold": 0.8}],
                "click_count": 3,
                "offset_x": 5,
                "offset_y": -4,
            },
        )
        preset = Preset(name="preset", steps=[legacy])
        payload = AppConfig(presets=[preset], selected_preset_id=preset.id).to_dict()

        config = config_from_payload(payload)
        definitions = step_definitions()

        migrated = config.presets[0].steps[0]
        self.assertEqual("find_and_tap", migrated.kind)
        self.assertEqual("multi", migrated.params["tap_mode"])
        self.assertEqual((540, 1000), (migrated.params["click_x"], migrated.params["click_y"]))
        self.assertFalse(migrated.params["custom_click"])
        self.assertEqual((5, -4), (migrated.params["offset_x"], migrated.params["offset_y"]))
        self.assertNotIn("find_and_multi_tap", {item["key"] for item in definitions})
        action_field = next(
            field
            for item in definitions
            if item["key"] == "find_and_tap"
            for field in item["fields"]
            if field["key"] == "tap_mode"
        )
        self.assertEqual(["single", "multi"], [item["value"] for item in action_field["options"]])

    def test_return_target_validation_and_normalization(self) -> None:
        a = Step(name="A", kind="wait")
        b = Step(name="B", kind="wait")
        b.params["return_to"] = "later"
        c = Step(name="C", kind="wait")
        c.params["return_to"] = a.id
        preset = Preset(name="p", steps=[a, b, c])
        payload = AppConfig(presets=[preset], selected_preset_id=preset.id).to_dict()

        with self.assertRaisesRegex(ValidationError, "返回连接"):
            config_from_payload(payload, normalize_dependencies=False)

        config = config_from_payload(payload, normalize_dependencies=True)
        self.assertNotIn("return_to", config.presets[0].steps[1].params)
        self.assertEqual(a.id, config.presets[0].steps[2].params["return_to"])

    def test_clone_preset_remaps_return_target(self) -> None:
        a = Step(name="A", kind="wait")
        b = Step(name="B", kind="wait")
        b.params["return_to"] = a.id
        preset = Preset(name="p", steps=[a, b])

        cloned = clone_preset(preset)
        cloned_steps = list(iter_steps(cloned))

        self.assertEqual(cloned_steps[0].id, cloned_steps[1].params["return_to"])
        self.assertNotEqual(a.id, cloned_steps[0].id)

    def test_branch_return_to_main_step_roundtrips(self) -> None:
        a = Step(name="A", kind="wait")
        branch_x = Step(name="x", kind="wait")
        branch_y = Step(name="y", kind="wait")
        branch_y.params["return_to"] = a.id
        root = Step(
            name="recognize",
            kind="find_and_tap",
            params={
                "templates": [{"file": "target.png", "threshold": 0.8}],
                "branches": {"0": [branch_x.to_dict(), branch_y.to_dict()]},
            },
        )
        preset = Preset(name="p", steps=[a, root])
        payload = AppConfig(presets=[preset], selected_preset_id=preset.id).to_dict()

        config = config_from_payload(payload, normalize_dependencies=False)
        branch_steps = config.presets[0].steps[1].params["branches"]["0"]
        self.assertEqual(a.id, branch_steps[1]["params"]["return_to"])

    def test_branch_return_to_other_branch_is_rejected(self) -> None:
        z = Step(name="z", kind="wait")
        branch_x = Step(name="x", kind="wait")
        branch_x.params["return_to"] = z.id
        root = Step(
            name="recognize",
            kind="find_and_tap",
            params={
                "templates": [
                    {"file": "target.png", "threshold": 0.8},
                    {"file": "two.png", "threshold": 0.8},
                ],
                "branches": {"0": [branch_x.to_dict()], "1": [z.to_dict()]},
            },
        )
        preset = Preset(name="p", steps=[root])
        payload = AppConfig(presets=[preset], selected_preset_id=preset.id).to_dict()

        with self.assertRaisesRegex(ValidationError, "返回连接"):
            config_from_payload(payload, normalize_dependencies=False)

        config = config_from_payload(payload, normalize_dependencies=True)
        branch_steps = config.presets[0].steps[0].params["branches"]["0"]
        self.assertNotIn("return_to", branch_steps[0]["params"])

    def test_payload_normalizes_stale_dependencies_and_selected_preset(self) -> None:
        first = Step(name="first", kind="wait")
        second = Step(
            name="second",
            kind="wait",
            depends_on=[first.id, first.id, "ghost"],
        )
        preset = Preset(name="preset", steps=[first, second])
        payload = AppConfig(
            presets=[preset], selected_preset_id=preset.id
        ).to_dict()
        payload["selected_preset_id"] = "missing"

        config = config_from_payload(payload, normalize_dependencies=True)

        self.assertEqual(preset.id, config.selected_preset_id)
        self.assertEqual([first.id], config.presets[0].steps[1].depends_on)

    def test_duplicate_nested_step_id_is_rejected(self) -> None:
        branch = Step(name="branch", kind="wait")
        root = recognition("root", {"0": [branch.to_dict()]})
        duplicate = Step(name="duplicate", kind="wait", id=branch.id)
        preset = Preset(name="preset", steps=[root, duplicate])
        payload = AppConfig(
            presets=[preset], selected_preset_id=preset.id
        ).to_dict()

        with self.assertRaisesRegex(ValidationError, "重复的步骤 ID"):
            config_from_payload(payload)

    def test_non_failing_step_cannot_continue(self) -> None:
        step = Step(name="wait", kind="wait", on_failure="continue")
        preset = Preset(name="preset", steps=[step])
        payload = AppConfig(
            presets=[preset], selected_preset_id=preset.id
        ).to_dict()

        with self.assertRaisesRegex(ValidationError, "不支持失败后继续"):
            config_from_payload(payload)

    def test_cross_layer_dependency_is_rejected(self) -> None:
        parent = Step(name="parent", kind="wait")
        nested = Step(name="nested", kind="wait", depends_on=[parent.id])
        root = recognition("root", {"0": [nested.to_dict()]})
        preset = Preset(name="preset", steps=[parent, root])
        payload = AppConfig(
            presets=[preset], selected_preset_id=preset.id
        ).to_dict()

        with self.assertRaisesRegex(ValidationError, "跨层级"):
            config_from_payload(payload)

    def test_step_definition_defaults_are_deep_copied(self) -> None:
        definitions = step_definitions()
        template_field = next(
            field
            for definition in definitions
            if definition["key"] == "find_and_tap"
            for field in definition["fields"]
            if field["key"] == "templates"
        )
        template_field["default"].append({"file": "mutated.png"})

        fresh = step_definitions()
        fresh_field = next(
            field
            for definition in fresh
            if definition["key"] == "find_and_tap"
            for field in definition["fields"]
            if field["key"] == "templates"
        )
        self.assertEqual([], fresh_field["default"])


class FieldValidationTests(unittest.TestCase):
    def test_roi_fields_have_safe_defaults_and_validate_before_persistence(self):
        definitions = next(item for item in step_definitions() if item["key"] == "find_and_tap")
        fields = {field["key"]: field for field in definitions["fields"]}
        self.assertEqual(("bool", False), (fields["roi_enabled"]["kind"], fields["roi_enabled"]["default"]))
        for key, axis in (("search_x", "x"), ("search_y", "y"),
                          ("search_width", "x"), ("search_height", "y")):
            self.assertEqual(("int", 0, axis),
                             (fields[key]["kind"], fields[key]["default"], fields[key]["coordinate_axis"]))
        base = {"templates": [{"file": "target.png"}]}
        config = config_from_payload(self.payload("find_and_tap", base))
        self.assertFalse(config.presets[0].steps[0].params["roi_enabled"])
        invalid = [{"roi_enabled": True}, {"roi_enabled": "false"}, {"search_x": -1},
                   {"search_width": True}, {"search_height": 1.2},
                   {"roi_enabled": True, "search_width": 10, "search_height": 0}]
        for params in invalid:
            with self.subTest(params=params), self.assertRaises(ValidationError):
                config_from_payload(self.payload("find_and_tap", {**base, **params}))


    def payload(self, kind, params):
        preset = Preset(name="preset", steps=[Step(name="step", kind=kind, params=params)])
        return AppConfig(presets=[preset], selected_preset_id=preset.id).to_dict()

    def test_invalid_field_types_ranges_and_nonfinite_numbers_are_rejected(self):
        cases = [("tap", "x", True), ("tap", "y", 1.2), ("tap", "x", -1),
                 ("swipe", "duration", -1), ("wait", "seconds", -0.1),
                 ("wait", "seconds", "nan"), ("wait", "seconds", float("inf")),
                 ("find_and_tap", "attempts", -1),
                 ("find_and_tap", "attempts", 1.2),
                 ("find_and_tap", "require_all", "false"),
                 ("find_and_tap", "tap_mode", []),
                 ("find_and_tap", "click_count", 0),
                 ("find_and_tap", "click_interval", -0.1)]
        for kind, key, value in cases:
            with self.subTest(kind=kind, key=key, value=value):
                params = {key: value}
                if kind == "find_and_tap":
                    params["templates"] = [{"file": "target.png"}]
                with self.assertRaises(ValidationError):
                    config_from_payload(self.payload(kind, params))

    def test_defaults_numeric_strings_and_negative_offsets_remain_compatible(self):
        config = config_from_payload(self.payload("tap", {"x": "12", "wait_after": "0.0"}))
        self.assertEqual({"x": 12, "y": 1000, "wait_after": 0.0}, config.presets[0].steps[0].params)
        params = {"templates": [{"file": "target.png"}], "offset_x": "-12", "attempts": "0"}
        config = config_from_payload(self.payload("find_and_tap", params))
        self.assertEqual(-12, config.presets[0].steps[0].params["offset_x"])
        self.assertEqual(0, config.presets[0].steps[0].params["attempts"])

    def test_template_threshold_types_and_nonfinite_values_are_rejected(self):
        for value in (True, float("nan"), float("inf"), -0.1, 1.1):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                config_from_payload(self.payload("find_and_tap", {
                    "templates": [{"file": "target.png", "threshold": value}]}))


if __name__ == "__main__":
    unittest.main()
