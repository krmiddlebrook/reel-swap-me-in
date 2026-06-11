import os
import tempfile
import unittest
from unittest import mock

from app import photos


class PhotoDirCase(unittest.TestCase):
    """Tests run against a throwaway assets dir."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        assets = self._tmp.name
        faces = os.path.join(assets, "faces")
        os.makedirs(faces)
        self._patches = [mock.patch.object(photos, "ASSETS_DIR", assets),
                         mock.patch.object(photos, "FACES_DIR", faces)]
        for patch in self._patches:
            patch.start()
        self.assets, self.faces = assets, faces

    def tearDown(self):
        for patch in self._patches:
            patch.stop()
        self._tmp.cleanup()

    def write(self, directory, name, data=b"x"):
        path = os.path.join(directory, name)
        with open(path, "wb") as fh:
            fh.write(data)
        return path


class TestDiscovery(PhotoDirCase):
    def test_main_photo_none_when_missing(self):
        self.assertIsNone(photos.main_photo())

    def test_main_photo_found(self):
        path = self.write(self.assets, "me.jpg")
        self.assertEqual(photos.main_photo(), path)

    def test_extra_photos_sorted_case_insensitive_ext(self):
        b = self.write(self.faces, "face-bb.jpg")
        a = self.write(self.faces, "face-aa.PNG")
        self.write(self.faces, "notes.txt")  # ignored
        self.assertEqual(photos.extra_photos(), [a, b])

    def test_list_photos_main_first_with_roles(self):
        self.write(self.assets, "me.png")
        self.write(self.faces, "face-aa.jpg")
        self.assertEqual(photos.list_photos(), [
            {"name": "me.png", "role": "main"},
            {"name": "face-aa.jpg", "role": "extra"},
        ])

    def test_list_photos_no_main(self):
        self.write(self.faces, "face-aa.jpg")
        self.assertEqual(photos.list_photos(),
                         [{"name": "face-aa.jpg", "role": "extra"}])


class TestPhotoPath(PhotoDirCase):
    def test_resolves_main_and_extra(self):
        main = self.write(self.assets, "me.jpg")
        extra = self.write(self.faces, "face-aa.jpg")
        self.assertEqual(photos.photo_path("me.jpg"), main)
        self.assertEqual(photos.photo_path("face-aa.jpg"), extra)

    def test_rejects_traversal_and_unknown(self):
        self.write(self.assets, "me.jpg")
        for bad in ("", None, "..", "../me.jpg", "a/b.jpg",
                    "/etc/passwd", "nope.jpg"):
            self.assertIsNone(photos.photo_path(bad), bad)

    def test_rejects_non_image_names(self):
        self.write(self.faces, ".DS_Store")
        self.write(self.faces, "notes.txt")
        self.assertIsNone(photos.photo_path(".DS_Store"))
        self.assertIsNone(photos.photo_path("notes.txt"))


class TestSave(PhotoDirCase):
    def test_save_main_replaces_old_main(self):
        self.write(self.assets, "me.png")
        path = photos.save_main(b"new", ".jpg")
        self.assertEqual(os.path.basename(path), "me.jpg")
        self.assertEqual(photos.main_photo(), path)
        self.assertFalse(os.path.exists(os.path.join(self.assets, "me.png")))

    def test_save_extra_unique_names(self):
        a = photos.save_extra(b"a", ".jpg")
        b = photos.save_extra(b"b", ".png")
        self.assertNotEqual(a, b)
        self.assertEqual(len(photos.extra_photos()), 2)
        self.assertTrue(os.path.basename(a).startswith("face-"))

    def test_save_main_failed_write_keeps_old_main(self):
        old_data = b"original"
        self.write(self.assets, "me.jpg", old_data)
        with mock.patch.object(photos.os, "replace", side_effect=OSError("boom")):
            with self.assertRaises(photos.PhotoError):
                photos.save_main(b"new", ".jpg")
        # old main must still exist with original bytes
        old_path = os.path.join(self.assets, "me.jpg")
        self.assertTrue(os.path.exists(old_path))
        with open(old_path, "rb") as fh:
            self.assertEqual(fh.read(), old_data)
        # no temp leftovers
        leftovers = [n for n in os.listdir(self.assets)
                     if n.startswith("me.tmp-")]
        self.assertEqual(leftovers, [])

    def test_save_main_normalizes_uppercase_ext(self):
        photos.save_main(b"x", ".JPG")
        main = photos.main_photo()
        self.assertIsNotNone(main)
        self.assertEqual(os.path.basename(main), "me.jpg")

    def test_save_rejects_unsupported_ext(self):
        with self.assertRaises(photos.PhotoError):
            photos.save_main(b"x", ".gif")
        with self.assertRaises(photos.PhotoError):
            photos.save_extra(b"x", ".gif")

    def test_save_extra_failed_write_raises_photo_error(self):
        with mock.patch("app.photos.open", side_effect=OSError("boom"),
                        create=True):
            with self.assertRaises(photos.PhotoError):
                photos.save_extra(b"x", ".jpg")


class TestDelete(PhotoDirCase):
    def test_delete_extra(self):
        path = photos.save_extra(b"a", ".jpg")
        photos.delete_extra(os.path.basename(path))
        self.assertEqual(photos.extra_photos(), [])

    def test_delete_unknown_is_404(self):
        with self.assertRaises(photos.PhotoError) as ctx:
            photos.delete_extra("nope.jpg")
        self.assertEqual(ctx.exception.status, 404)

    def test_delete_main_refused(self):
        self.write(self.assets, "me.jpg")
        with self.assertRaises(photos.PhotoError) as ctx:
            photos.delete_extra("me.jpg")
        self.assertEqual(ctx.exception.status, 400)

    def test_delete_vanished_file_is_404(self):
        path = photos.save_extra(b"a", ".jpg")
        name = os.path.basename(path)
        with mock.patch.object(photos.os, "remove",
                               side_effect=OSError("gone")):
            with self.assertRaises(photos.PhotoError) as ctx:
                photos.delete_extra(name)
        self.assertEqual(ctx.exception.status, 404)


class TestPromote(PhotoDirCase):
    def test_promote_swaps_roles(self):
        self.write(self.assets, "me.jpg", b"old-main")
        extra = self.write(self.faces, "face-aa.png", b"new-main")
        new_main = photos.promote("face-aa.png")
        self.assertEqual(os.path.basename(new_main), "me.png")
        with open(new_main, "rb") as fh:
            self.assertEqual(fh.read(), b"new-main")
        self.assertFalse(os.path.exists(extra))
        # the old main is preserved as an extra
        contents = []
        for path in photos.extra_photos():
            with open(path, "rb") as fh:
                contents.append(fh.read())
        self.assertIn(b"old-main", contents)

    def test_promote_bumps_mtime_for_sheet_cache(self):
        self.write(self.assets, "me.jpg")
        extra = self.write(self.faces, "face-aa.jpg")
        ancient = 1000000000
        os.utime(extra, (ancient, ancient))
        new_main = photos.promote("face-aa.jpg")
        self.assertGreater(os.path.getmtime(new_main), ancient)

    def test_promote_rolls_back_when_second_move_fails(self):
        self.write(self.assets, "me.jpg", b"old-main")
        self.write(self.faces, "face-aa.jpg")
        real_replace = os.replace
        calls = []

        def flaky_replace(src, dst):
            calls.append(src)
            if len(calls) == 2:
                raise OSError("disk full")
            real_replace(src, dst)

        with mock.patch.object(photos.os, "replace",
                               side_effect=flaky_replace):
            with self.assertRaises(photos.PhotoError):
                photos.promote("face-aa.jpg")
        self.assertEqual(os.path.basename(photos.main_photo()), "me.jpg")

    def test_promote_guards(self):
        with self.assertRaises(photos.PhotoError) as ctx:
            photos.promote("nope.jpg")
        self.assertEqual(ctx.exception.status, 404)
        self.write(self.assets, "me.jpg")
        with self.assertRaises(photos.PhotoError):
            photos.promote("me.jpg")  # already main

    def test_promote_rejects_non_image(self):
        self.write(self.faces, ".DS_Store")
        self.write(self.assets, "me.jpg")
        with self.assertRaises(photos.PhotoError) as ctx:
            photos.promote(".DS_Store")
        self.assertEqual(ctx.exception.status, 404)
        self.assertEqual(os.path.basename(photos.main_photo()), "me.jpg")


if __name__ == "__main__":
    unittest.main()
