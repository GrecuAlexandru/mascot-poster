from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from app.services.product_asset_normalizer import ProductAssetNormalizer


def test_normalizer_crops_opaque_white_padding_from_visible_color(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / "output.png"
    image = Image.new("RGBA", (100, 100), (255, 255, 255, 255))
    ImageDraw.Draw(image).rectangle((20, 10, 79, 89), fill=(30, 30, 30, 255))
    image.save(source)

    metrics = ProductAssetNormalizer().normalize(source, output)

    assert metrics.visible_bbox == (20, 10, 80, 90)
    assert metrics.width_occupancy == pytest.approx(0.6)
    assert metrics.height_occupancy == pytest.approx(0.8)
    assert metrics.major_axis_occupancy == pytest.approx(0.8)
    normalized = Image.open(output).convert("RGBA")
    assert normalized.size == (72, 92)
    assert normalized.getpixel((0, 0))[3] == 0
    assert metrics.normalized_width == 72
    assert metrics.normalized_height == 92


def test_normalizer_removes_edge_connected_off_white_background(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / "output.png"
    image = Image.new("RGBA", (100, 100), (247, 249, 246, 255))
    ImageDraw.Draw(image).rectangle((20, 10, 79, 89), fill=(40, 90, 150, 255))
    image.save(source)

    metrics = ProductAssetNormalizer().normalize(source, output)

    normalized = Image.open(output).convert("RGBA")
    assert metrics.visible_bbox == (20, 10, 80, 90)
    assert normalized.getpixel((0, 0))[3] == 0
    assert normalized.getpixel((36, 46)) == (40, 90, 150, 255)


def test_normalizer_preserves_enclosed_white_product_details(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / "output.png"
    image = Image.new("RGBA", (100, 100), (248, 248, 246, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 10, 79, 89), fill=(40, 90, 150, 255))
    draw.rectangle((40, 35, 59, 64), fill=(255, 255, 255, 255))
    image.save(source)

    ProductAssetNormalizer().normalize(source, output)

    normalized = Image.open(output).convert("RGBA")
    assert normalized.getpixel((36, 46)) == (255, 255, 255, 255)


def test_normalizer_removes_a_thin_gray_seam_connected_to_white_background(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / "output.png"
    image = Image.new("RGBA", (100, 100), (255, 255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 10, 79, 89), fill=(40, 90, 150, 255))
    draw.line((95, 10, 95, 89), fill=(205, 205, 205, 255), width=1)
    draw.line((5, 40, 5, 59), fill=(170, 170, 170, 255), width=1)
    image.save(source)

    metrics = ProductAssetNormalizer().normalize(source, output)

    assert metrics.visible_bbox == (20, 10, 80, 90)
    assert Image.open(output).convert("RGBA").getpixel((0, 0))[3] == 0


def test_normalizer_uses_alpha_for_a_transparent_white_subject(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / "output.png"
    image = Image.new("RGBA", (100, 100), (255, 255, 255, 0))
    ImageDraw.Draw(image).rectangle((15, 20, 84, 79), fill=(255, 255, 255, 255))
    image.save(source)

    metrics = ProductAssetNormalizer().normalize(source, output)

    assert metrics.detection_mode == "alpha"
    assert metrics.visible_bbox == (15, 20, 85, 80)
    assert Image.open(output).size == (82, 72)
    assert Image.open(output).convert("RGBA").getpixel((6, 6)) == (255, 255, 255, 255)


def test_normalizer_preserves_an_opaque_white_appliance_on_white_background(
    tmp_path: Path,
) -> None:
    source = tmp_path / "freezer.png"
    output = tmp_path / "normalized.png"
    image = Image.new("RGBA", (120, 140), (255, 255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((24, 14, 95, 125), fill=(247, 249, 250, 255))
    draw.line((24, 14, 24, 125), fill=(185, 192, 198, 255), width=2)
    draw.line((95, 14, 95, 125), fill=(185, 192, 198, 255), width=2)
    draw.line((24, 125, 95, 125), fill=(185, 192, 198, 255), width=2)
    for y in (38, 61, 84, 107):
        draw.line((32, y, 87, y), fill=(130, 160, 185, 255), width=3)
    image.save(source)

    metrics = ProductAssetNormalizer().normalize(source, output)

    normalized = Image.open(output).convert("RGBA")
    assert metrics.detection_mode == "opaque_white"
    assert normalized.getchannel("A").getextrema() == (255, 255)
    assert normalized.getpixel((normalized.width // 2, normalized.height // 2))[3] == 255
    assert normalized.getpixel((42, 62)) == (247, 249, 250, 255)


def test_normalizer_rejects_a_subject_below_minimum_occupancy(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / "output.png"
    image = Image.new("RGBA", (100, 100), (255, 255, 255, 255))
    ImageDraw.Draw(image).rectangle((40, 40, 59, 59), fill=(0, 0, 0, 255))
    image.save(source)

    with pytest.raises(ValueError, match="55%"):
        ProductAssetNormalizer().normalize(source, output)

    assert not output.exists()
