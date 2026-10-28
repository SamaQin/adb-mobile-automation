from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from model_automation.adb_runtime import prepare_adb_environment


class AdbEnvironmentTests(TestCase):
    def test_project_local_runtime_directory_is_preferred(self):
        with TemporaryDirectory() as directory:
            environment = prepare_adb_environment(Path(directory))
            temp_dir = (Path(directory) / '.adb-runtime' / 'temp').resolve()

        self.assertEqual(str(temp_dir), environment['TEMP'])
        self.assertEqual(str(temp_dir), environment['TMP'])
        self.assertEqual(str(temp_dir / 'adb.log'), environment['ANDROID_ADB_LOG_PATH'])

    def test_falls_back_to_local_app_data_when_project_runtime_is_unusable(self):
        with TemporaryDirectory() as directory, TemporaryDirectory() as local_app_data:
            root = Path(directory)
            # A file in place of the runtime directory makes the preferred
            # location impossible to create.
            (root / '.adb-runtime').write_text('occupied', encoding='utf-8')
            with patch.dict(os.environ, {'LOCALAPPDATA': local_app_data}):
                environment = prepare_adb_environment(root)
            expected = (Path(local_app_data) / 'ADB-Automation' / '.adb-runtime' / 'temp').resolve()

        self.assertEqual(str(expected), environment['TEMP'])
        self.assertEqual(str(expected), environment['TMP'])
        self.assertEqual(str(expected / 'adb.log'), environment['ANDROID_ADB_LOG_PATH'])

    def test_inherits_environment_when_no_runtime_directory_is_usable(self):
        with TemporaryDirectory() as directory, TemporaryDirectory() as local_app_data:
            root = Path(directory)
            (root / '.adb-runtime').write_text('occupied', encoding='utf-8')
            (Path(local_app_data) / 'ADB-Automation').write_text('occupied', encoding='utf-8')
            with patch.dict(os.environ, {'LOCALAPPDATA': local_app_data}):
                environment = prepare_adb_environment(root)

        self.assertEqual(os.environ.get('TEMP'), environment.get('TEMP'))
        self.assertEqual(os.environ.get('TMP'), environment.get('TMP'))
