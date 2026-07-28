"""
DXF input tests.

A DXF upload has to come out the other end as a preprocessed image the
detector can read: black line work on a white sheet, at a size set by the
requested DPI. DWG stays a clear refusal, not a crash.
"""

import asyncio
import sys
from pathlib import Path

import cv2
import ezdxf
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from file_processor import FileProcessor


@pytest.fixture(scope="module")
def dxf_path(tmp_path_factory):
    """A small plan: a room outline, a run, and a panel tag."""

    directory = tmp_path_factory.mktemp("cad")
    path = directory / "plan.dxf"

    doc = ezdxf.new("R2018")
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (200, 0), (200, 100), (0, 100)], close=True)
    msp.add_line((20, 50), (180, 50))
    msp.add_text("LP-1", height=6).set_placement((90, 55))
    doc.saveas(path)

    return path


def test_dxf_becomes_detectable_image(dxf_path):
    images = asyncio.run(FileProcessor().process_file(dxf_path, dpi=100))

    assert len(images) == 1
    image = cv2.imread(str(images[0]))
    assert image is not None

    # Drawing office colours: overwhelmingly white sheet, some dark line work.
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    assert float(gray.mean()) > 200
    assert int((gray < 100).sum()) > 0

    # 2:1 drawing on a 24" sheet at 100 DPI: long side 2400 px.
    height, width = gray.shape
    assert width == pytest.approx(2400, rel=0.05)
    assert width / height == pytest.approx(2.0, rel=0.1)


def test_dwg_is_refused_with_guidance(tmp_path):
    dwg = tmp_path / "plan.dwg"
    dwg.write_bytes(b"AC1027 not a real drawing")

    with pytest.raises(ValueError, match="DXF"):
        asyncio.run(FileProcessor().process_file(dwg, dpi=100))


def test_empty_dxf_is_an_error(tmp_path):
    path = tmp_path / "empty.dxf"
    ezdxf.new("R2018").saveas(path)

    with pytest.raises(ValueError, match="empty"):
        asyncio.run(FileProcessor().process_file(path, dpi=100))
