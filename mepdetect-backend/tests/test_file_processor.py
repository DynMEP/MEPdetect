"""
Preprocessing tests.

The denoiser used to run on every page unconditionally. On a sheet plotted at
400 DPI that is ~200 megapixels and takes minutes, while removing nothing at
all from a page rendered out of a vector PDF. These pin the behaviour that
replaced it: denoise what is noisy, at a cost that stays bounded.
"""

import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from file_processor import FileProcessor


@pytest.fixture
def calls(monkeypatch):
    """Record which denoiser the preprocessor reaches for."""

    recorded = {"nlmeans": 0, "median": 0}
    real_median = cv2.medianBlur

    def fake_nlmeans(image, *args, **kwargs):
        recorded["nlmeans"] += 1
        return image

    def fake_median(image, size):
        recorded["median"] += 1
        return real_median(image, size)

    monkeypatch.setattr(cv2, "fastNlMeansDenoisingColored", fake_nlmeans)
    monkeypatch.setattr(cv2, "medianBlur", fake_median)

    return recorded


def _drawing(width=900, height=700):
    """A clean page of line work, as a vector PDF renders to."""

    image = np.full((height, width, 3), 255, np.uint8)
    for x in range(60, width - 60, 90):
        cv2.line(image, (x, 40), (x, height - 40), (0, 0, 0), 2)
    for y in range(60, height - 60, 80):
        cv2.line(image, (40, y), (width - 40, y), (0, 0, 0), 2)

    return image


def _with_noise(image, sigma=12):
    noisy = image.astype(np.int16) + np.random.normal(0, sigma, image.shape)
    return np.clip(noisy, 0, 255).astype(np.uint8)


def test_clean_render_measures_as_noise_free():
    processor = FileProcessor()
    gray = cv2.cvtColor(_drawing(), cv2.COLOR_BGR2GRAY)

    assert processor._estimate_noise(gray) < processor.noise_threshold


def test_scan_measures_as_noisy():
    processor = FileProcessor()
    gray = cv2.cvtColor(_with_noise(_drawing()), cv2.COLOR_BGR2GRAY)

    assert processor._estimate_noise(gray) > processor.noise_threshold


def test_clean_render_is_not_denoised(calls):
    """The whole point: no denoiser runs on a page that has no noise."""

    FileProcessor()._adaptive_preprocess(_drawing())

    assert calls == {"nlmeans": 0, "median": 0}


def test_noisy_page_is_denoised(calls):
    FileProcessor()._adaptive_preprocess(_with_noise(_drawing()))

    assert calls["nlmeans"] == 1


def test_large_noisy_page_uses_the_bounded_filter(calls):
    """
    Non-local means costs minutes on a plotted sheet, so past a size limit the
    bounded filter takes over rather than the job stalling.
    """

    processor = FileProcessor(max_denoise_megapixels=0.1)
    processor._adaptive_preprocess(_with_noise(_drawing()))

    assert calls["median"] == 1
    assert calls["nlmeans"] == 0


def test_noise_estimate_cost_does_not_grow_with_the_sheet():
    """It samples a window, so a huge sheet is not a huge measurement."""

    processor = FileProcessor()
    small = cv2.cvtColor(_drawing(900, 700), cv2.COLOR_BGR2GRAY)
    large = cv2.cvtColor(_drawing(4000, 3000), cv2.COLOR_BGR2GRAY)

    assert processor._estimate_noise(small) == pytest.approx(
        processor._estimate_noise(large), abs=1.0
    )
