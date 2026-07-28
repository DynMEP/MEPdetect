"""
Shared test setup.

The API loads a YOLO model, and importing ultralytics replaces cv2.imread
with a version that always returns a channel axis: a grayscale read comes
back as (H, W, 1) rather than (H, W). Whether a test met that patched
imread used to depend on collection order, so image-handling bugs hid or
surfaced depending on which test ran first. Importing it here puts every
test in the same condition the running service is in.
"""

try:  # pragma: no cover - the patch is the point, not this import
    import ultralytics  # noqa: F401
except ImportError:
    pass
