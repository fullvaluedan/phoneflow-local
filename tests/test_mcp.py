"""Transport/image-boundary tests; no phone or live account required."""
import base64
import io
from pathlib import Path
import tempfile
import unittest

try:
    from PIL import Image
    from phoneflow_mcp import render, session_path
    AVAILABLE = True
except ImportError:
    AVAILABLE = False


@unittest.skipUnless(AVAILABLE, 'Install the mcp extra for connector tests')
class MCPTests(unittest.TestCase):
    def test_path_traversal_rejected(self):
        with self.assertRaises(ValueError):
            session_path('../other-session')

    def test_image_outside_session_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)/'session'
            folder.mkdir()
            outside = Path(temp)/'private.png'
            Image.new('RGB', (10, 10)).save(outside)
            with self.assertRaises(ValueError):
                render({'ok': True, 'result': {'screenshot': str(outside)}}, folder)

    def test_native_image_has_correct_coordinate_mapping(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            path = folder/'frame.png'
            Image.new('RGB', (1080, 2400), 'blue').save(path)
            result = render({'ok': True, 'result': {'screenshot': str(path)}}, folder)
            self.assertEqual([b.type for b in result.content], ['text', 'image'])
            mapping = result.structuredContent['result']['image_mapping']
            self.assertEqual(mapping['source_region_size'], [1080, 2400])
            with Image.open(io.BytesIO(base64.b64decode(result.content[1].data))) as im:
                self.assertEqual(list(im.size), mapping['returned_size'])
            self.assertAlmostEqual(mapping['returned_size'][0]*mapping['screen_pixels_per_returned_pixel'][0], 1080)

    def test_crop_retains_screen_origin(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'crop.png'
            Image.new('RGB', (80, 120)).save(path)
            result = render({'ok': True, 'result': {'crop': str(path), 'crop_origin': [900, 1300]}}, temp)
            self.assertEqual(result.structuredContent['result']['image_mapping']['origin_in_screen'], [900, 1300])

    def test_error_is_mcp_error_without_image(self):
        result = render({'ok': False, 'error': 'stale observation'}, Path.cwd())
        self.assertTrue(result.isError)
        self.assertEqual(len(result.content), 1)


if __name__ == '__main__':
    unittest.main()
