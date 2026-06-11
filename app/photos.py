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


def save_main(data, ext):
    """Replace the main photo (ext includes the dot); returns its path."""
    os.makedirs(ASSETS_DIR, exist_ok=True)
    for old in MAIN_EXTS:
        old_path = os.path.join(ASSETS_DIR, "me." + old)
        if os.path.exists(old_path):
            os.remove(old_path)
    path = os.path.join(ASSETS_DIR, "me" + ext)
    with open(path, "wb") as fh:
        fh.write(data)
    return path


def save_extra(data, ext):
    """Store one extra photo; returns its path. Caller enforces caps."""
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
