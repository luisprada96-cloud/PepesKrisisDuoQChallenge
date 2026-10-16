import unittest
import urllib.request

import test_shell_penalties as fixtures


class OverlayFilesTests(unittest.TestCase):
    setUp = fixtures.ShellEndpointTests.setUp
    tearDown = fixtures.ShellEndpointTests.tearDown

    def test_overlay_assets_are_served_without_a_session(self):
        for filename, content_type in [('overlay.html', 'text/html'),
                                       ('overlay.js', 'javascript'),
                                       ('overlay.css', 'text/css')]:
            with self.subTest(filename=filename):
                with urllib.request.urlopen(self.base + '/' + filename) as response:
                    self.assertEqual(response.status, 200)
                    self.assertIn(content_type, response.headers['Content-Type'])
                    self.assertGreater(len(response.read()), 100)


if __name__ == '__main__':
    unittest.main()
