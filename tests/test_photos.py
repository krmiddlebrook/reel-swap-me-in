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


if __name__ == "__main__":
    unittest.main()
