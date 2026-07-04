import numpy as np

from services.image_limits import downscale_if_needed, max_image_side_px


def test_downscale_if_needed_shrinks_large_image(monkeypatch) -> None:
    monkeypatch.setenv("DMEF_MAX_IMAGE_SIDE_PX", "1000")
    image = np.zeros((4000, 3000, 3), dtype=np.uint8)
    resized = downscale_if_needed(image)
    assert max(resized.shape[0], resized.shape[1]) == 1000


def test_downscale_if_needed_keeps_small_image() -> None:
    image = np.zeros((800, 600, 3), dtype=np.uint8)
    resized = downscale_if_needed(image, max_side=max_image_side_px())
    assert resized.shape == image.shape
