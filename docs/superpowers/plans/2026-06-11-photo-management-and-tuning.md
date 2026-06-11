# Photo Management & Face-Restore Tuning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One collapsed "Photos & tuning" card on the main page: view/add/remove/promote the photos behind both identity systems, and tune the FaceFusion face-restore knobs with persisted settings.

**Architecture:** New `app/photos.py` owns all photo file management (main photo `assets/me.*` + extras `assets/faces/`); `app/face_restore.py` gains a validated, persisted settings store consumed by `build_command`; `app/server.py` replaces the `/api/photo` + `/api/faces` split with a unified `/api/photos` resource plus `/api/settings`; `public/index.html` renders the gallery card. Spec: `docs/superpowers/specs/2026-06-11-photo-management-and-tuning-design.md`.

**Tech Stack:** Python 3.8 stdlib only (http.server, unittest, mock), vanilla JS, no build step. Tests run with `python3 -m unittest`.

**Conventions you must follow:** terse stdlib Python, `%` formatting, user-safe error messages, 4-space indent, tests in `unittest` style matching `tests/test_pipeline.py`. Run the full suite with `python3 -m unittest discover -s tests` — it must pass before every commit.

---

### Task 1: `app/photos.py` — discovery and safe lookup

**Files:**
- Create: `app/photos.py`
- Create: `tests/test_photos.py`

- [ ] **Step 1.1: Write the failing tests**

Create `tests/test_photos.py`:

```python
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


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 1.2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_photos -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.photos'` (or ImportError).

- [ ] **Step 1.3: Write the implementation**

Create `app/photos.py`:

```python
"""Photo management for both identity systems: the main photo
(assets/me.* — drives the Higgsfield character sheet) and extra photos
(assets/faces/ — feed the local face restore together with the main one)."""
import os
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS_DIR = os.path.join(ROOT, "assets")
FACES_DIR = os.path.join(ASSETS_DIR, "faces")
MAIN_EXTS = ("jpg", "jpeg", "png")
MAX_EXTRAS = 9


class PhotoError(Exception):
    """An error whose message is safe to show to the user."""

    def __init__(self, message, status=400):
        Exception.__init__(self, message)
        self.status = status


def main_photo():
    """Path of the stored main photo (me.jpg/jpeg/png), or None."""
    for ext in MAIN_EXTS:
        path = os.path.join(ASSETS_DIR, "me." + ext)
        if os.path.exists(path):
            return path
    return None


def extra_photos():
    """Extra face photos under assets/faces/, in stable order."""
    try:
        names = os.listdir(FACES_DIR)
    except OSError:
        return []
    return sorted(os.path.join(FACES_DIR, name) for name in names
                  if name.lower().endswith((".jpg", ".jpeg", ".png")))


def list_photos():
    """[{"name", "role"}] for the UI gallery — main photo first."""
    items = []
    main = main_photo()
    if main:
        items.append({"name": os.path.basename(main), "role": "main"})
    items.extend({"name": os.path.basename(path), "role": "extra"}
                 for path in extra_photos())
    return items


def photo_path(name):
    """Absolute path for a gallery photo name, or None.

    The single anti-traversal choke point: the name must be a bare
    basename and resolve to the current main photo or a file that exists
    inside assets/faces/."""
    if not name or name != os.path.basename(name):
        return None
    main = main_photo()
    if main and name == os.path.basename(main):
        return main
    path = os.path.join(FACES_DIR, name)
    if os.path.isfile(path):
        return path
    return None
```

(`uuid` and `PhotoError.status` are used by Task 2/3 code — included now so the module is written once.)

- [ ] **Step 1.4: Run tests to verify they pass**

Run: `python3 -m unittest tests.test_photos -v`
Expected: all PASS.

- [ ] **Step 1.5: Commit**

```bash
git add app/photos.py tests/test_photos.py
git commit -m "feat: photos module — discovery, listing, safe path lookup"
```

---

### Task 2: `app/photos.py` — save and delete

**Files:**
- Modify: `app/photos.py`
- Test: `tests/test_photos.py`

- [ ] **Step 2.1: Write the failing tests** (append to `tests/test_photos.py`)

```python
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
```

- [ ] **Step 2.2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_photos -v`
Expected: new tests FAIL with `AttributeError: ... no attribute 'save_main'`.

- [ ] **Step 2.3: Write the implementation** (append to `app/photos.py`)

```python
_VALID_EXTS = tuple("." + e for e in MAIN_EXTS)  # (".jpg", ".jpeg", ".png")


def _check_ext(ext):
    """Normalize and validate ext (includes the dot); raises PhotoError if bad."""
    ext = ext.lower()
    if ext not in _VALID_EXTS:
        raise PhotoError("Unsupported image type.")
    return ext


def save_main(data, ext):
    """Replace the main photo (ext includes the dot); returns its path.

    Atomic: writes to a temp name inside ASSETS_DIR first, then
    os.replace onto the final target, then removes other-ext leftovers.
    The old main is never touched until the write is known to succeed."""
    ext = _check_ext(ext)
    os.makedirs(ASSETS_DIR, exist_ok=True)
    tmp_path = os.path.join(ASSETS_DIR, "me.tmp-%s" % uuid.uuid4().hex[:8])
    target = os.path.join(ASSETS_DIR, "me" + ext)
    try:
        with open(tmp_path, "wb") as fh:
            fh.write(data)
        os.replace(tmp_path, target)
    except OSError:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise PhotoError("Couldn't save the photo.")
    # remove other-extension leftovers (safe — new file is already in place)
    for old in MAIN_EXTS:
        old_path = os.path.join(ASSETS_DIR, "me." + old)
        if old_path != target and os.path.exists(old_path):
            os.remove(old_path)
    return target


def save_extra(data, ext):
    """Store one extra photo; returns its path. Caller enforces caps."""
    ext = _check_ext(ext)
    os.makedirs(FACES_DIR, exist_ok=True)
    path = os.path.join(FACES_DIR,
                        "face-%s%s" % (uuid.uuid4().hex[:8], ext))
    with open(path, "wb") as fh:
        fh.write(data)
    return path


def delete_extra(name):
    """Remove an extra photo. The main photo can only be replaced or
    promoted over — deleting it would re-trigger the setup banner."""
    path = photo_path(name)
    if path is None:
        raise PhotoError("Unknown photo.", status=404)
    if path == main_photo():
        raise PhotoError(
            "The main photo can't be removed — promote another photo first.")
    os.remove(path)
```

- [ ] **Step 2.4: Run tests to verify they pass**

Run: `python3 -m unittest tests.test_photos -v` — all PASS.

- [ ] **Step 2.5: Commit**

```bash
git add app/photos.py tests/test_photos.py
git commit -m "feat: photos module — save main/extra, guarded delete"
```

---

### Task 3: `app/photos.py` — promote with mtime bump and rollback

**Files:**
- Modify: `app/photos.py`
- Test: `tests/test_photos.py`

- [ ] **Step 3.1: Write the failing tests** (append to `tests/test_photos.py`)

```python
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
```

Note: `flaky_replace` raises on the SECOND call, then the implementation rolls back with a THIRD call (which must succeed) — `len(calls) == 2` only triggers once.

- [ ] **Step 3.2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_photos -v`
Expected: FAIL with `AttributeError: ... no attribute 'promote'`.

- [ ] **Step 3.3: Write the implementation** (append to `app/photos.py`)

```python
def promote(name):
    """Make an extra photo the main one; the old main becomes an extra.

    Ends by bumping the new main's mtime: os.replace preserves mtime and
    the character-sheet cache is keyed on the main photo's mtime, so
    without the bump a stale sheet would survive the swap."""
    path = photo_path(name)
    if path is None:
        raise PhotoError("Unknown photo.", status=404)
    main = main_photo()
    if main is None:
        raise PhotoError("No main photo to swap with.")
    if path == main:
        raise PhotoError("That photo is already the main one.")
    os.makedirs(FACES_DIR, exist_ok=True)
    demoted = os.path.join(
        FACES_DIR, "face-%s%s" % (uuid.uuid4().hex[:8],
                                  os.path.splitext(main)[1].lower()))
    os.replace(main, demoted)
    new_main = os.path.join(ASSETS_DIR,
                            "me" + os.path.splitext(path)[1].lower())
    try:
        os.replace(path, new_main)
    except OSError:
        os.replace(demoted, main)  # restore the old main
        raise PhotoError("Couldn't promote that photo.")
    os.utime(new_main, None)
    return new_main
```

- [ ] **Step 3.4: Run tests to verify they pass**

Run: `python3 -m unittest tests.test_photos -v` — all PASS.

- [ ] **Step 3.5: Commit**

```bash
git add app/photos.py tests/test_photos.py
git commit -m "feat: photos module — promote with sheet-cache mtime bump and rollback"
```

---

### Task 4: route existing photo consumers through `app/photos.py`

`pipeline.user_photo` and `face_restore.extra_photos` currently duplicate
what photos.py now owns. Delegate them; point `server.py`'s legacy
handlers at the photos module (those handlers are replaced in Task 7).

**Files:**
- Modify: `app/pipeline.py:15-21` (`user_photo`)
- Modify: `app/face_restore.py` (imports, remove `extra_photos`/`FACES_DIR`/`MAX_EXTRA_PHOTOS`, fix `source_photos`)
- Modify: `app/server.py` (references to the removed face_restore names)
- Test: `tests/test_face_restore.py` (two tests patch the moved function)

- [ ] **Step 4.1: Update the existing tests first**

In `tests/test_face_restore.py`, class `TestSourcePhotos`: both tests patch
`face_restore.extra_photos`, which is moving. Replace the class with:

```python
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
```

and add the import at the top of the file:

```python
from app import face_restore, photos
```

(replacing the existing `from app import face_restore` line).

- [ ] **Step 4.2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_face_restore -v`
Expected: the two TestSourcePhotos tests FAIL (patching `photos.extra_photos`
has no effect while `source_photos` still calls its own copy).

- [ ] **Step 4.3: Delegate**

In `app/face_restore.py`:
- Add `from app import photos` below the stdlib imports.
- Delete the `extra_photos()` function, the `FACES_DIR` constant, and the
  `MAX_EXTRA_PHOTOS` constant.
- Change `source_photos` to:

```python
def source_photos(primary):
    """All face photos, primary first. FaceFusion averages the identity
    embeddings across sources, so extra photos improve likeness."""
    return [primary] + [p for p in photos.extra_photos() if p != primary]
```

In `app/pipeline.py`, replace the `user_photo` function body:

```python
def user_photo():
    """Path of the stored user photo (me.jpg/jpeg/png), or None."""
    from app import photos
    return photos.main_photo()
```

In `app/server.py`:
- Add `photos` to the app import line:
  `from app import face_restore, oauth, photos, pipeline`
- In `_status()`: `face_restore.extra_photos()` → `photos.extra_photos()`.
- In `_post_face()`: `face_restore.extra_photos()` → `photos.extra_photos()`
  (two call sites), `face_restore.MAX_EXTRA_PHOTOS` → `photos.MAX_EXTRAS`
  (two sites), `face_restore.FACES_DIR` → `photos.FACES_DIR` (two sites).
- In `_post_faces_clear()`: `face_restore.extra_photos()` →
  `photos.extra_photos()` (two sites).

- [ ] **Step 4.4: Run the full suite**

Run: `python3 -m unittest discover -s tests`
Expected: all PASS.

- [ ] **Step 4.5: Commit**

```bash
git add app/photos.py app/face_restore.py app/pipeline.py app/server.py tests/test_face_restore.py
git commit -m "refactor: photos module owns photo discovery; consumers delegate"
```

---

### Task 5: face-restore settings store

**Files:**
- Modify: `app/face_restore.py`
- Test: `tests/test_face_restore.py`

- [ ] **Step 5.1: Write the failing tests** (append to `tests/test_face_restore.py`)

```python
class SettingsCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._patch = mock.patch.object(
            face_restore, "SETTINGS_PATH",
            os.path.join(self._tmp.name, "settings.json"))
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self._tmp.cleanup()


class TestLoadSettings(SettingsCase):
    def test_missing_file_returns_defaults(self):
        self.assertEqual(face_restore.load_settings(),
                         face_restore.DEFAULT_SETTINGS)

    def test_corrupt_file_returns_defaults(self):
        with open(face_restore.SETTINGS_PATH, "w") as fh:
            fh.write("{nope")
        self.assertEqual(face_restore.load_settings(),
                         face_restore.DEFAULT_SETTINGS)

    def test_partial_file_merges_over_defaults(self):
        with open(face_restore.SETTINGS_PATH, "w") as fh:
            json.dump({"enhancer_blend": 40, "junk": 1}, fh)
        settings = face_restore.load_settings()
        self.assertEqual(settings["enhancer_blend"], 40)
        self.assertEqual(settings["pixel_boost"],
                         face_restore.DEFAULT_SETTINGS["pixel_boost"])
        self.assertNotIn("junk", settings)


class TestSaveSettings(SettingsCase):
    def test_round_trip(self):
        face_restore.save_settings({"pixel_boost": "768x768"})
        self.assertEqual(face_restore.load_settings()["pixel_boost"],
                         "768x768")

    def test_invalid_values_rejected(self):
        for bad in ({"enhancer_blend": 101}, {"enhancer_blend": "80"},
                    {"enhancer_blend": True}, {"pixel_boost": "640x640"},
                    {"swapper_model": "deepfacelab"},
                    {"enhancer_model": "instagram_filter"}, ["not", "a", "dict"]):
            with self.assertRaises(ValueError):
                face_restore.save_settings(bad)

    def test_unknown_keys_ignored(self):
        saved = face_restore.save_settings({"junk": 1})
        self.assertNotIn("junk", saved)
```

Also add `import json`, `import os`, and `import tempfile` to the test
file's imports if not already present.

- [ ] **Step 5.2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_face_restore -v`
Expected: FAIL with `AttributeError: ... no attribute 'SETTINGS_PATH'`.

- [ ] **Step 5.3: Write the implementation**

In `app/face_restore.py`, add `import json` to the imports, then add below
the existing constants:

```python
SETTINGS_PATH = os.path.join(ROOT, "assets", "face-restore-settings.json")

SWAPPER_MODELS = ("hyperswap_1a_256", "hyperswap_1b_256",
                  "hyperswap_1c_256", "inswapper_128_fp16",
                  "inswapper_128", "ghost_2_256", "simswap_256")
ENHANCER_MODELS = ("gfpgan_1.4", "codeformer", "restoreformer_plus_plus",
                   "gpen_bfr_512")
PIXEL_BOOSTS = ("256x256", "512x512", "768x768", "1024x1024")

DEFAULT_SETTINGS = {
    "enhancer_blend": 80,
    "pixel_boost": "512x512",
    "swapper_model": "hyperswap_1a_256",
    "enhancer_model": "gfpgan_1.4",
}

_SETTING_CHOICES = {
    "pixel_boost": PIXEL_BOOSTS,
    "swapper_model": SWAPPER_MODELS,
    "enhancer_model": ENHANCER_MODELS,
}


def validate_settings(data):
    """Known keys with valid values; raises ValueError naming the first
    bad one. Unknown keys are ignored (forward compatibility)."""
    if not isinstance(data, dict):
        raise ValueError("settings must be a JSON object")
    clean = {}
    for key, value in data.items():
        if key == "enhancer_blend":
            if isinstance(value, bool) or not isinstance(value, int) \
                    or not 0 <= value <= 100:
                raise ValueError("enhancer_blend must be an integer 0-100")
            clean[key] = value
        elif key in _SETTING_CHOICES:
            if value not in _SETTING_CHOICES[key]:
                raise ValueError("%s must be one of: %s"
                                 % (key, ", ".join(_SETTING_CHOICES[key])))
            clean[key] = value
    return clean


def load_settings():
    """Saved settings merged over defaults. Never raises — a corrupt or
    missing file silently yields the defaults."""
    settings = dict(DEFAULT_SETTINGS)
    try:
        with open(SETTINGS_PATH) as fh:
            settings.update(validate_settings(json.load(fh)))
    except (OSError, ValueError):
        pass
    return settings


def save_settings(data):
    """Validate, merge over current settings, persist; returns the result."""
    clean = validate_settings(data)
    settings = load_settings()
    settings.update(clean)
    with open(SETTINGS_PATH, "w") as fh:
        json.dump(settings, fh, indent=2)
    return settings
```

- [ ] **Step 5.4: Run tests to verify they pass**

Run: `python3 -m unittest tests.test_face_restore -v` — all PASS.

- [ ] **Step 5.5: Commit**

```bash
git add app/face_restore.py tests/test_face_restore.py
git commit -m "feat: persisted, validated face-restore settings"
```

---

### Task 6: `build_command` consumes settings

**Files:**
- Modify: `app/face_restore.py` (`build_command`, `restore`)
- Test: `tests/test_face_restore.py`

- [ ] **Step 6.1: Update tests first**

In `tests/test_face_restore.py`, class `TestBuildCommand`: the function
gains a `settings` parameter. Update the three existing tests to pass
`face_restore.DEFAULT_SETTINGS` as the new final argument, e.g.:

```python
        cmd = face_restore.build_command(
            ["a.jpg", "b.png"], "in.mp4", "out.mp4", "cpu",
            face_restore.DEFAULT_SETTINGS)
```

(same change in `test_swap_and_enhance_processors` and
`test_aac_audio_for_player_compatibility`), and append a new test:

```python
    def test_settings_reach_the_command(self):
        settings = {"enhancer_blend": 35, "pixel_boost": "768x768",
                    "swapper_model": "inswapper_128_fp16",
                    "enhancer_model": "codeformer"}
        cmd = face_restore.build_command(["a.jpg"], "t", "o", "cpu", settings)
        self.assertEqual(cmd[cmd.index("--face-swapper-model") + 1],
                         "inswapper_128_fp16")
        self.assertEqual(cmd[cmd.index("--face-swapper-pixel-boost") + 1],
                         "768x768")
        self.assertEqual(cmd[cmd.index("--face-enhancer-model") + 1],
                         "codeformer")
        self.assertEqual(cmd[cmd.index("--face-enhancer-blend") + 1], "35")
```

- [ ] **Step 6.2: Run tests to verify the new one fails**

Run: `python3 -m unittest tests.test_face_restore -v`
Expected: `test_settings_reach_the_command` FAILS (TypeError: too many args).

- [ ] **Step 6.3: Implement**

In `app/face_restore.py`, change `build_command`'s signature and the
hardcoded knob lines:

```python
def build_command(sources, target, output, provider, settings=None):
    settings = settings or load_settings()
    cmd = [FF_PYTHON, FF_SCRIPT, "headless-run", "-s"]
    cmd += list(sources)
    cmd += [
        "-t", target, "-o", output,
        "--processors", "face_swapper", "face_enhancer",
        "--face-swapper-model", settings["swapper_model"],
        "--face-swapper-pixel-boost", settings["pixel_boost"],
        "--face-enhancer-model", settings["enhancer_model"],
        "--face-enhancer-blend", str(settings["enhancer_blend"]),
        "--face-selector-mode", "one",
        "--face-selector-order", "large-small",
        "--output-audio-encoder", "aac",
        "--execution-providers", provider,
    ]
    return cmd
```

In `restore()`, load once before the provider loop (so both attempts use
identical settings) — above the `with _RUN_LOCK:` line add:

```python
    settings = load_settings()
```

and change the `build_command(...)` call inside the loop to:

```python
                build_command(photos, video_path, output_path, provider,
                              settings),
```

- [ ] **Step 6.4: Run the full suite**

Run: `python3 -m unittest discover -s tests` — all PASS.

- [ ] **Step 6.5: Commit**

```bash
git add app/face_restore.py tests/test_face_restore.py
git commit -m "feat: build_command honors persisted tuning settings"
```

---

### Task 7: unified server endpoints

**Files:**
- Modify: `app/server.py`
- Test: `tests/test_server.py`

- [ ] **Step 7.1: Write the failing tests** (append to `tests/test_server.py`)

```python
from app import server


class TestPhotoRoutes(unittest.TestCase):
    def test_action_route_parses_name_and_action(self):
        match = server._PHOTO_ACTION.match("/api/photos/face-ab.jpg/promote")
        self.assertEqual(match.group(1), "face-ab.jpg")
        self.assertEqual(match.group(2), "promote")
        match = server._PHOTO_ACTION.match("/api/photos/me.jpg/delete")
        self.assertEqual(match.group(2), "delete")

    def test_action_route_rejects_garbage(self):
        for bad in ("/api/photos//promote", "/api/photos/a/b/promote",
                    "/api/photos/a.jpg/rename", "/api/photos/promote"):
            self.assertIsNone(server._PHOTO_ACTION.match(bad), bad)

    def test_file_route(self):
        match = server._PHOTO_FILE.match("/api/photos/me.jpg")
        self.assertEqual(match.group(1), "me.jpg")
        self.assertIsNone(server._PHOTO_FILE.match("/api/photos/"))
        self.assertIsNone(server._PHOTO_FILE.match("/api/photos/a/b"))

    def test_upload_role_parsing(self):
        self.assertEqual(server._upload_role("/api/photos"), "extra")
        self.assertEqual(server._upload_role("/api/photos?role=main"), "main")
        self.assertEqual(server._upload_role("/api/photos?role=extra"),
                         "extra")
        self.assertIsNone(server._upload_role("/api/photos?role=banana"))
```

(`unittest` is already imported in this file.)

- [ ] **Step 7.2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_server -v`
Expected: FAIL with `AttributeError: module 'app.server' has no attribute '_PHOTO_ACTION'`.

- [ ] **Step 7.3: Implement the routes**

In `app/server.py`:

**a)** Below the existing `_WORK_PATH` regex add:

```python
_PHOTO_FILE = re.compile(r"^/api/photos/([^/?]+)$")
_PHOTO_ACTION = re.compile(r"^/api/photos/([^/?]+)/(promote|delete)$")


def _upload_role(path):
    """Role for POST /api/photos[?role=…]; None when the role is invalid."""
    query = urllib.parse.urlparse(path).query
    role = (urllib.parse.parse_qs(query).get("role") or ["extra"])[0]
    return role if role in ("main", "extra") else None
```

**b)** In `do_GET`, add two branches before the `work_match` branch
(and capture the match first):

```python
        photo_match = _PHOTO_FILE.match(self.path)
        ...
        elif self.path == "/api/photos":
            self._json(200, {"photos": photos.list_photos()})
        elif self.path == "/api/settings":
            self._json(200, face_restore.load_settings())
        elif photo_match:
            path = photos.photo_path(
                urllib.parse.unquote(photo_match.group(1)))
            if path:
                ctype = ("image/png" if path.lower().endswith(".png")
                         else "image/jpeg")
                self._file(path, ctype)
            else:
                self.send_error(404)
```

**c)** Replace the `do_POST` dispatch for the old photo endpoints. Remove
the `/api/photo`, `/api/faces`, `/api/faces/clear` branches and add:

```python
        if self.path.split("?")[0].startswith("/api/photos"):
            self._post_photos()
            return
```

and in the JSON section at the bottom of `do_POST` (after the
`/api/replicate` branch):

```python
        elif self.path == "/api/settings":
            self._post_settings(data)
```

**d)** Delete the `_post_photo`, `_post_face`, and `_post_faces_clear`
methods entirely. Add:

```python
    def _post_photos(self):
        action = _PHOTO_ACTION.match(self.path)
        if action:
            name = urllib.parse.unquote(action.group(1))
            try:
                if action.group(2) == "promote":
                    photos.promote(name)
                else:
                    photos.delete_extra(name)
            except photos.PhotoError as exc:
                self._json(exc.status, {"error": str(exc)})
                return
            self._json(200, {"ok": True, "photos": photos.list_photos()})
            return
        if self.path.split("?")[0] != "/api/photos":
            self.send_error(404)  # e.g. /api/photos/<name>/rename
            return
        role = _upload_role(self.path)
        if role is None:
            self._json(400, {"error": "Unknown photo role."})
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > 20 * 1024 * 1024:
            self._json(400, {"error": "Photo must be a file under 20 MB."})
            return
        data = self.rfile.read(length)
        ext = pipeline.detect_image_ext(data)
        if not ext:
            self._json(400, {"error": "Please upload a JPEG or PNG photo."})
            return
        if role == "extra" and len(photos.extra_photos()) >= photos.MAX_EXTRAS:
            self._json(400, {"error": "That's plenty — %d extra photos max."
                                      % photos.MAX_EXTRAS})
            return
        if role == "main":
            photos.save_main(data, ext)
        else:
            photos.save_extra(data, ext)
        self._json(200, {"ok": True, "photos": photos.list_photos()})

    def _post_settings(self, data):
        try:
            self._json(200, face_restore.save_settings(data))
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
```

- [ ] **Step 7.4: Run the full suite**

Run: `python3 -m unittest discover -s tests` — all PASS.

- [ ] **Step 7.5: Smoke-test the wiring** (no UI yet)

```bash
python3 - <<'EOF'
from http.server import ThreadingHTTPServer
import json, threading, urllib.request
from app import server
srv = ThreadingHTTPServer(("127.0.0.1", 8898), server.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
print(urllib.request.urlopen("http://127.0.0.1:8898/api/photos").read())
print(urllib.request.urlopen("http://127.0.0.1:8898/api/settings").read())
req = urllib.request.Request("http://127.0.0.1:8898/api/settings",
                             data=json.dumps({"enhancer_blend": 75}).encode(),
                             method="POST")
print(urllib.request.urlopen(req).read())
EOF
```

Expected: photo list JSON, defaults JSON, then settings JSON with
`"enhancer_blend": 75`. Afterwards restore the default:
`rm -f assets/face-restore-settings.json` (or POST 80 back).

- [ ] **Step 7.6: Commit**

```bash
git add app/server.py tests/test_server.py
git commit -m "feat: unified /api/photos + /api/settings endpoints"
```

---

### Task 8: the gallery card UI

**Files:**
- Modify: `public/index.html`

No JS test infra — server-backed behavior is covered by Tasks 1–7;
this task ends with a scripted smoke test plus a manual checklist.

- [ ] **Step 8.1: CSS** — replace the `#setupState`-adjacent styles block.
Inside `<style>`, after the `#restoreRow` rules, add:

```css
  #galleryToggle { margin:12px 0 0; font-size:13px; }
  #galleryToggle a { color:#a99cff; text-decoration:none; }
  #gallery { margin-top:10px; padding:14px 16px; border:1px solid #2c2a36;
             background:#17151e; border-radius:12px; text-align:left; }
  #gallery .lbl { display:flex; justify-content:space-between; font-size:13px;
                  color:#c9c5d8; margin-top:12px; }
  #gallery .lbl:first-child { margin-top:0; }
  #gallery .lbl .val { color:#9a96a8; }
  #gallery .hint { font-size:11px; color:#6f6a80; margin:4px 0 0; }
  #thumbs { display:flex; gap:10px; flex-wrap:wrap; margin-top:8px; }
  #thumbs .th { width:58px; height:74px; border-radius:9px; position:relative;
                border:1px solid #2c2a36; background:#0e0d12; flex-shrink:0; }
  #thumbs .th img { width:100%; height:100%; object-fit:cover;
                    border-radius:8px; display:block; }
  #thumbs .th.main { border:2px solid #7c6cf2; cursor:pointer; }
  #thumbs .th.main::after { content:"MAIN"; position:absolute; bottom:2px;
      left:0; right:0; font-size:8px; font-weight:700; color:#a99cff;
      text-align:center; text-shadow:0 1px 2px #000; }
  #thumbs .th .x, #thumbs .th .star { position:absolute; top:-7px;
      width:17px; height:17px; border-radius:50%; background:#2c2a36;
      font-size:10px; line-height:17px; text-align:center; cursor:pointer;
      border:0; color:#ff7b7b; padding:0; }
  #thumbs .th .x { right:-7px; }
  #thumbs .th .star { left:-7px; color:#ffd479; }
  #thumbs .th.add { border:1.5px dashed #4a4660; background:none;
      color:#9a96a8; font-size:22px; cursor:pointer; }
  #gallery input[type=range] { width:100%; accent-color:#7c6cf2; margin:8px 0 0; }
  #gallery .seg { display:flex; gap:6px; margin-top:8px; }
  #gallery .seg button { flex:1; padding:6px 0; font-size:11.5px;
      background:none; border:1px solid #2c2a36; border-radius:8px;
      color:#9a96a8; cursor:pointer; font-weight:400; }
  #gallery .seg button.on { border-color:#7c6cf2; color:#f3f1ec;
      background:rgba(124,108,242,.12); }
  #gallery select { width:100%; background:#0e0d12; border:1px solid #2c2a36;
      color:#c9c5d8; border-radius:8px; padding:7px 8px; font-size:12.5px;
      margin-top:6px; }
  #gallery .links { display:flex; justify-content:space-between; margin-top:12px;
      font-size:12px; }
  #gallery .links a { color:#a99cff; text-decoration:none; }
  #savedNote { font-size:11px; color:#5f9b6d; text-align:center;
      margin:10px 0 0; transition:opacity .4s; }
```

- [ ] **Step 8.2: Markup** — replace the `#setupState` paragraph and the
old `facesInput` element with the gallery. Delete these two lines:

```html
  <p id="setupState"><span id="setupStateText"></span><a id="changePhoto" href="#" hidden>Change photo</a><a id="addFaces" href="#" hidden></a><a id="clearFaces" href="#" hidden>clear extras</a></p>
  <input id="facesInput" type="file" accept="image/jpeg,image/png" multiple hidden>
```

and insert in their place:

```html
  <p id="setupState"><span id="setupStateText"></span></p>
  <p id="galleryToggle" hidden><a href="#" id="galleryLink">▸ Photos &amp; tuning</a></p>
  <div id="gallery" hidden>
    <div class="lbl">Your photos</div>
    <div id="thumbs"></div>
    <p class="hint">MAIN drives the Higgsfield character reference — click it to replace it, or ★ an extra to promote it (the reference regenerates on the next run, 1 credit). All photos feed face restore; varied angles &amp; lighting help most.</p>
    <div id="tuning" hidden>
      <div class="lbl">Face enhancement <span class="val" id="blendVal"></span></div>
      <input id="blend" type="range" min="0" max="100" step="5">
      <p class="hint">0 = natural skin texture from the swap · 100 = sharpest, can look airbrushed</p>
      <div class="lbl">Detail quality</div>
      <div class="seg" id="boostSeg"></div>
      <p class="hint">How finely your face is rendered — higher is slower</p>
      <div class="links"><a href="#" id="advLink">▸ Advanced</a><a href="#" id="resetLink" hidden>Reset to defaults</a></div>
      <div id="advanced" hidden>
        <div class="lbl">Swapper model</div>
        <select id="swapperSel"></select>
        <p class="hint">hyperswap_1a is the default — a new model downloads once on the next run (~250–700 MB)</p>
        <div class="lbl">Enhancer model</div>
        <select id="enhancerSel"></select>
      </div>
      <p id="savedNote" hidden>✓ saved — applies to your next swap</p>
    </div>
  </div>
  <input id="addInput" type="file" accept="image/jpeg,image/png" multiple hidden>
  <input id="mainInput" type="file" accept="image/jpeg,image/png" hidden>
```

- [ ] **Step 8.3: JavaScript** — remove the old photo JS, add the gallery JS.

Delete: the `addFaces`/`clearFaces`/`facesInput` const declarations and
their three event listeners; the `changePhoto` listener; in
`refreshStatus` the four lines touching `changePhoto`/`addFaces`/`clearFaces`.

Change the existing `photoInput` upload handler's fetch URL from
`"/api/photo"` to `"/api/photos?role=main"`, and its success branch to
also call `loadGallery()`.

Add new consts near the other element lookups:

```js
const galleryToggle = document.getElementById("galleryToggle"),
      galleryLink = document.getElementById("galleryLink"),
      gallery = document.getElementById("gallery"),
      thumbs = document.getElementById("thumbs"),
      tuning = document.getElementById("tuning"),
      blend = document.getElementById("blend"), blendVal = document.getElementById("blendVal"),
      boostSeg = document.getElementById("boostSeg"),
      advLink = document.getElementById("advLink"), advanced = document.getElementById("advanced"),
      resetLink = document.getElementById("resetLink"),
      swapperSel = document.getElementById("swapperSel"), enhancerSel = document.getElementById("enhancerSel"),
      savedNote = document.getElementById("savedNote"),
      addInput = document.getElementById("addInput"), mainInput = document.getElementById("mainInput");
const BOOSTS = ["256x256", "512x512", "768x768", "1024x1024"];
const BOOST_LABELS = { "256x256": "Fast 256", "512x512": "Standard 512",
                       "768x768": "High 768", "1024x1024": "Max 1024" };
const SWAPPERS = ["hyperswap_1a_256", "hyperswap_1b_256", "hyperswap_1c_256",
                  "inswapper_128_fp16", "inswapper_128", "ghost_2_256", "simswap_256"];
const ENHANCERS = ["gfpgan_1.4", "codeformer", "restoreformer_plus_plus", "gpen_bfr_512"];
const DEFAULTS = { enhancer_blend: 80, pixel_boost: "512x512",
                   swapper_model: "hyperswap_1a_256", enhancer_model: "gfpgan_1.4" };
let settings = { ...DEFAULTS };
```

Add the gallery functions (place after the `facesInput` removal point):

```js
async function api(path, opts) {
  const r = await fetch(path, opts);
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.error || "Request failed");
  return d;
}

function renderThumbs(list) {
  thumbs.innerHTML = "";
  for (const p of list) {
    const th = document.createElement("div");
    th.className = "th" + (p.role === "main" ? " main" : "");
    const img = document.createElement("img");
    img.src = `/api/photos/${encodeURIComponent(p.name)}?t=${Date.now()}`;
    th.appendChild(img);
    if (p.role === "main") {
      th.title = "Replace the main photo";
      th.onclick = () => mainInput.click();
    } else {
      const star = document.createElement("button");
      star.className = "star"; star.textContent = "★";
      star.title = "Make this the main photo";
      star.onclick = async () => {
        if (!confirm("Make this the main photo? The character reference regenerates on the next run (1 credit).")) return;
        try { renderThumbs((await api(`/api/photos/${encodeURIComponent(p.name)}/promote`, { method: "POST" })).photos); }
        catch (err) { setStatus(err.message, { error: true }); }
      };
      const x = document.createElement("button");
      x.className = "x"; x.textContent = "×"; x.title = "Remove";
      x.onclick = async () => {
        try { renderThumbs((await api(`/api/photos/${encodeURIComponent(p.name)}/delete`, { method: "POST" })).photos); }
        catch (err) { setStatus(err.message, { error: true }); }
      };
      th.appendChild(star); th.appendChild(x);
    }
    thumbs.appendChild(th);
  }
  const add = document.createElement("div");
  add.className = "th add"; add.textContent = "+";
  add.style.lineHeight = "72px"; add.style.textAlign = "center";
  add.title = "Add face photos";
  add.onclick = () => addInput.click();
  thumbs.appendChild(add);
  galleryLink.textContent =
    `${gallery.hidden ? "▸" : "▾"} Photos & tuning (${list.length} photo${list.length === 1 ? "" : "s"})`;
}

async function loadGallery() {
  try { renderThumbs((await api("/api/photos")).photos); } catch { /* retry next status tick */ }
}

function showSaved() {
  savedNote.hidden = false;
  clearTimeout(showSaved._t);
  showSaved._t = setTimeout(() => { savedNote.hidden = true; }, 2500);
}

function renderSettings() {
  blend.value = settings.enhancer_blend;
  blendVal.textContent = `${settings.enhancer_blend}%`;
  boostSeg.innerHTML = "";
  for (const b of BOOSTS) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = BOOST_LABELS[b];
    btn.className = b === settings.pixel_boost ? "on" : "";
    btn.onclick = () => pushSettings({ pixel_boost: b });
    boostSeg.appendChild(btn);
  }
  const fill = (sel, values, current) => {
    sel.innerHTML = "";
    for (const v of values) {
      const o = document.createElement("option");
      o.value = v; o.textContent = v; o.selected = v === current;
      sel.appendChild(o);
    }
  };
  fill(swapperSel, SWAPPERS, settings.swapper_model);
  fill(enhancerSel, ENHANCERS, settings.enhancer_model);
  resetLink.hidden = Object.keys(DEFAULTS).every(k => settings[k] === DEFAULTS[k]);
}

async function pushSettings(patch) {
  try {
    settings = await api("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    renderSettings(); showSaved();
  } catch (err) { setStatus(err.message, { error: true }); }
}

async function loadSettings() {
  try { settings = await api("/api/settings"); renderSettings(); } catch { /* defaults */ }
}

galleryLink.addEventListener("click", (e) => {
  e.preventDefault();
  gallery.hidden = !gallery.hidden;
  loadGallery();
});
blend.addEventListener("input", () => { blendVal.textContent = `${blend.value}%`; });
blend.addEventListener("change", () => pushSettings({ enhancer_blend: parseInt(blend.value, 10) }));
advLink.addEventListener("click", (e) => {
  e.preventDefault();
  advanced.hidden = !advanced.hidden;
  advLink.textContent = (advanced.hidden ? "▸" : "▾") + " Advanced";
});
resetLink.addEventListener("click", (e) => { e.preventDefault(); pushSettings({ ...DEFAULTS }); });
swapperSel.addEventListener("change", () => pushSettings({ swapper_model: swapperSel.value }));
enhancerSel.addEventListener("change", () => pushSettings({ enhancer_model: enhancerSel.value }));
addInput.addEventListener("change", async () => {
  const files = [...addInput.files];
  addInput.value = "";
  try {
    for (const file of files) {
      await api("/api/photos?role=extra", {
        method: "POST",
        headers: { "Content-Type": file.type || "application/octet-stream" },
        body: file,
      });
    }
  } catch (err) { setStatus(err.message, { error: true }); }
  loadGallery();
});
mainInput.addEventListener("change", async () => {
  const file = mainInput.files[0];
  mainInput.value = "";
  if (!file) return;
  try {
    await api("/api/photos?role=main", {
      method: "POST",
      headers: { "Content-Type": file.type || "application/octet-stream" },
      body: file,
    });
    setStatus("Main photo replaced ✓ — the character reference regenerates on the next run (1 credit).");
  } catch (err) { setStatus(err.message, { error: true }); }
  loadGallery();
});
loadGallery(); loadSettings();
```

In `refreshStatus`, after the `restoreRow.hidden` line add:

```js
    galleryToggle.hidden = !ready;
    tuning.hidden = !s.faceRestore;
```

- [ ] **Step 8.4: Scripted smoke test**

```bash
python3 - <<'EOF'
from http.server import ThreadingHTTPServer
import threading, urllib.request
from app import server
srv = ThreadingHTTPServer(("127.0.0.1", 8897), server.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
html = urllib.request.urlopen("http://127.0.0.1:8897/").read().decode()
for needle in ("galleryToggle", "boostSeg", "swapperSel", "mainInput",
               "api/photos"):
    assert needle in html, needle
print("UI markup OK")
EOF
```

Expected: `UI markup OK`.

- [ ] **Step 8.5: Manual checklist** (run `python3 -m app.server`, open http://localhost:8787)

- Gallery toggle appears once connected + photo present; expands/collapses.
- Thumbnails render; MAIN badge on the main photo.
- “+” adds 2 photos at once; × removes one; ★ promotes (confirm dialog,
  thumbnails swap, old main appears as an extra).
- Click MAIN thumbnail → replace flow works.
- Move a slider, pick a quality, change a model — “✓ saved” appears;
  reload the page — values persisted; restart the server — still persisted.
- Reset to defaults restores everything and hides itself.
- With `vendor/` absent (rename it temporarily) the tuning block hides but
  the photo strip still works.

- [ ] **Step 8.6: Commit**

```bash
git add public/index.html
git commit -m "feat: photos & tuning gallery card"
```

---

### Task 9: docs, gitignore, final verification

**Files:**
- Modify: `.gitignore`
- Modify: `README.md`

- [ ] **Step 9.1: gitignore** — add one line after `assets/faces/`:

```
assets/face-restore-settings.json
```

- [ ] **Step 9.2: README** — in the “Face restore” section, replace the
“Likeness improves further with extra face photos…” paragraph with:

```markdown
Likeness improves further with **extra face photos**: open **Photos &
tuning** under the engine picker and click **+** to add 2–8 more shots —
varied angles, expressions, and lighting help most. FaceFusion averages
the identity embedding across all photos, which cancels out single-photo
quirks. The same card shows which photo is **MAIN** (it drives the
Higgsfield character reference; promoting or replacing it regenerates the
reference on the next run, 1 credit) and exposes the tuning dials: face
enhancement strength, detail quality, and — under Advanced — the swapper
and enhancer models. Settings persist in
`assets/face-restore-settings.json` (gitignored) and apply to every
future swap.
```

- [ ] **Step 9.3: Full verification**

```bash
python3 -m unittest discover -s tests
bash -n setup.sh
python3 -m py_compile app/photos.py app/face_restore.py app/server.py app/pipeline.py
```

Expected: all tests pass (≈100), both checks silent.

- [ ] **Step 9.4: Commit**

```bash
git add .gitignore README.md
git commit -m "docs: photos & tuning card; gitignore settings file"
```

- [ ] **Step 9.5: Request code review** (superpowers:requesting-code-review)
against the range `main@{start of feature}..HEAD`, requirements = the spec.

---

## Self-Review Notes (already applied)

- Spec coverage: Task 1–3 (photos module incl. mtime bump + rollback),
  Task 4 (single source of truth), Task 5–6 (settings store + consumption),
  Task 7 (unified API), Task 8 (card UI incl. main-replace + promote
  confirm), Task 9 (docs/gitignore). Out-of-scope items from the spec have
  no tasks, as intended.
- Type consistency: `PhotoError.status` used by Task 7's handler;
  `photos.MAX_EXTRAS` (not the removed `face_restore.MAX_EXTRA_PHOTOS`)
  used in Tasks 4 and 7; `build_command(..., settings)` signature matches
  between Tasks 6 tests and implementation.
- The old `/api/photo` handler is referenced by `public/index.html` until
  Task 8 — but Task 7 removes it. That is fine for tests (nothing exercises
  the UI), and Task 8 lands in the same sitting; do not insert a release
  between Tasks 7 and 8.
