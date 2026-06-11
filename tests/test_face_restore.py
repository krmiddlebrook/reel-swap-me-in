import unittest
from unittest import mock

from app import face_restore, photos


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
        with mock.patch.object(photos, "extra_photos",
                               return_value=["x/a.jpg", "x/b.jpg"]):
            self.assertEqual(face_restore.source_photos("me.jpg"),
                             ["me.jpg", "x/a.jpg", "x/b.jpg"])

    def test_primary_not_duplicated(self):
        with mock.patch.object(photos, "extra_photos",
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


class TestRestoreProviderFallback(unittest.TestCase):
    def _run(self, run_side_effect, output_exists=True):
        used = []

        def fake_run(cmd, **kwargs):
            used.append(cmd[cmd.index("--execution-providers") + 1])
            return run_side_effect(len(used))

        with mock.patch.object(face_restore, "available", return_value=True), \
                mock.patch.object(face_restore, "providers",
                                  return_value=["coreml", "cpu"]), \
                mock.patch.object(face_restore.subprocess, "run",
                                  side_effect=fake_run), \
                mock.patch.object(face_restore.os.path, "exists",
                                  return_value=output_exists):
            result = face_restore.restore("v.mp4", "o.mp4", ["me.jpg"])
        return used, result

    def test_falls_back_to_cpu_when_coreml_fails(self):
        used, result = self._run(
            lambda n: mock.Mock(returncode=1 if n == 1 else 0,
                                stdout="", stderr="coreml broke"))
        self.assertEqual(used, ["coreml", "cpu"])
        self.assertEqual(result, "o.mp4")

    def test_zero_exit_without_output_also_falls_back(self):
        used = []

        def fake_run(cmd, **kwargs):
            used.append(cmd[cmd.index("--execution-providers") + 1])
            return mock.Mock(returncode=0, stdout="", stderr="quiet fail")

        with mock.patch.object(face_restore, "available", return_value=True), \
                mock.patch.object(face_restore, "providers",
                                  return_value=["coreml", "cpu"]), \
                mock.patch.object(face_restore.subprocess, "run",
                                  side_effect=fake_run), \
                mock.patch.object(face_restore.os.path, "exists",
                                  return_value=False):
            with self.assertRaises(face_restore.FaceRestoreError) as ctx:
                face_restore.restore("v.mp4", "o.mp4", ["me.jpg"])
        self.assertEqual(used, ["coreml", "cpu"])
        self.assertIn("quiet fail", str(ctx.exception))


class TestPipelineRestoreFaces(unittest.TestCase):
    """A restore failure must never fail the job — the swap cost credits."""

    def test_failure_keeps_raw_video_and_warns(self):
        from app import pipeline
        events = []
        with mock.patch.object(
                face_restore, "restore",
                side_effect=face_restore.FaceRestoreError("nope")), \
                mock.patch.object(pipeline, "user_photo",
                                  return_value="me.jpg"):
            out = pipeline.restore_faces(
                "raw.mp4", "job1", lambda s, d: events.append((s, d)))
        self.assertEqual(out, "raw.mp4")
        self.assertEqual(events[-1][0], "warning")
        self.assertIn("nope", events[-1][1])

    def test_unexpected_exception_also_keeps_raw_video(self):
        from app import pipeline
        events = []
        with mock.patch.object(face_restore, "source_photos",
                               side_effect=TypeError("boom")), \
                mock.patch.object(pipeline, "user_photo",
                                  return_value="me.jpg"):
            out = pipeline.restore_faces(
                "raw.mp4", "job1", lambda s, d: events.append((s, d)))
        self.assertEqual(out, "raw.mp4")
        self.assertEqual(events[-1][0], "warning")


class TestLastLine(unittest.TestCase):
    def test_prefers_last_nonempty_line(self):
        self.assertEqual(face_restore._last_line("a\rb\n\nc\n  \n"), "c")

    def test_empty(self):
        self.assertEqual(face_restore._last_line(None), "")


if __name__ == "__main__":
    unittest.main()
