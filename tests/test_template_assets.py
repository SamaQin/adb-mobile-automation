from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

import cv2
import numpy as np

from model_automation.vision import load_image, save_image
from web_server.template_assets import TemplateAssets


class TemplateAssetsTests(TestCase):
    def test_metadata_and_thumbnail_reuse_and_file_change_invalidation(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'image.png'
            save_image(path, np.zeros((20, 40, 3), dtype=np.uint8))
            assets = TemplateAssets()
            with patch('web_server.template_assets.load_image', wraps=load_image) as decode:
                first = assets.metadata(path)
                self.assertIs(assets.metadata(path), first)
                content, etag = assets.thumbnail(path, 10)
                self.assertEqual((5, 10), cv2.imdecode(np.frombuffer(content, np.uint8), cv2.IMREAD_COLOR).shape[:2])
                self.assertEqual((content, etag), assets.thumbnail(path, 10))
                self.assertEqual(2, decode.call_count)
                save_image(path, np.full((30, 50, 3), 127, dtype=np.uint8))
                changed = assets.metadata(path)
                changed_content, changed_etag = assets.thumbnail(path, 10)
                self.assertEqual((50, 30), (changed.width, changed.height))
                self.assertNotEqual(first.revision, changed.revision)
                self.assertNotEqual(etag, changed_etag)
                self.assertNotEqual(content, changed_content)
                path.unlink()
                self.assertIsNone(assets.metadata(path))
                self.assertIsNone(assets.thumbnail(path, 10))

    def test_corrupt_empty_assets_are_skipped(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'empty.png'
            path.write_bytes(b'')
            assets = TemplateAssets()
            self.assertIsNone(assets.metadata(path))
            self.assertIsNone(assets.thumbnail(path, 20))

    def test_caches_are_bounded_by_entry_count_and_encoded_bytes(self):
        with TemporaryDirectory() as directory:
            assets = TemplateAssets(max_entries=2, max_bytes=500)
            for index in range(5):
                path = Path(directory) / f'{index}.png'
                save_image(path, np.full((20, 40, 3), index, dtype=np.uint8))
                assets.metadata(path)
                assets.thumbnail(path, 10)
            self.assertLessEqual(len(assets._metadata), 2)
            self.assertLessEqual(len(assets._thumbnails), 2)
            self.assertLessEqual(assets._bytes, 500)
