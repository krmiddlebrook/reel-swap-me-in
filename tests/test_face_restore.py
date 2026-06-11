import unittest
from unittest import mock

from app import face_restore


class TestBuildCommand(unittest.TestCase):
    def test_sources_target_output(self):
        cmd = face_restore.build_command(
            ["a.jpg", "b.png"], "in.mp4", "out.mp4", "cpu")
        self.assertEqual(cmd[2], "headless-run")
        i = cmd.index("-s")
        self.assertEqual(cmd[i + 1:i + 3], ["a.jpg", "b.png"])
        self.assertEqual(cmd[cmd.index("-t") + 1], "in.mp4")
        self.assertEqual(cmd[cmd.index("-o") + 1], "out.mp4")
        self.assertEqual(cmd[cmd.index("--execution-providers") + 1], "cpu")

    def test_swap_and_enhance_processors(self):
        cmd = face_restore.build_command(["a.jpg"], "t", "o", "coreml")
        i = cmd.index("--processors")
        self.assertEqual(cmd[i + 1:i + 3], ["face_swapper", "face_enhancer"])

    def test_aac_audio_for_player_compatibility(self):
        cmd = face_restore.build_command(["a.jpg"], "t", "o", "cpu")
        self.assertEqual(cmd[cmd.index("--output-audio-encoder") + 1], "aac")


class TestProviders(unittest.TestCase):
    def test_apple_silicon_tries_coreml_then_cpu(self):
        with mock.patch("platform.system", return_value="Darwin"), \
                mock.patch("platform.machine", return_value="arm64"):
            self.assertEqual(face_restore.providers(), ["coreml", "cpu"])

    def test_everything_else_is_cpu_only(self):
        with mock.patch("platform.system", return_value="Linux"):
            self.assertEqual(face_restore.providers(), ["cpu"])


class TestSourcePhotos(unittest.TestCase):
    def test_primary_first_then_extras(self):
        with mock.patch.object(face_restore, "extra_photos",
                               return_value=["x/a.jpg", "x/b.jpg"]):
            self.assertEqual(face_restore.source_photos("me.jpg"),
                             ["me.jpg", "x/a.jpg", "x/b.jpg"])

    def test_primary_not_duplicated(self):
        with mock.patch.object(face_restore, "extra_photos",
                               return_value=["me.jpg", "x/a.jpg"]):
            self.assertEqual(face_restore.source_photos("me.jpg"),
                             ["me.jpg", "x/a.jpg"])


class TestRestoreGuards(unittest.TestCase):
    def test_not_installed(self):
        with mock.patch.object(face_restore, "available",
                               return_value=False):
            with self.assertRaises(face_restore.FaceRestoreError):
                face_restore.restore("v.mp4", "o.mp4", ["me.jpg"])

    def test_no_photos(self):
        with mock.patch.object(face_restore, "available", return_value=True):
            with self.assertRaises(face_restore.FaceRestoreError):
                face_restore.restore("v.mp4", "o.mp4", [])


if __name__ == "__main__":
    unittest.main()
