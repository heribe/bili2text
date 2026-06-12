import pytest

from downloader import extract_bvid


@pytest.mark.parametrize(
    ("input_value", "expected"),
    [
        ("BV1xx411c7mD", "BV1xx411c7mD"),
        ("  BV1xx411c7mD  ", "BV1xx411c7mD"),
        ("https://www.bilibili.com/video/BV1xx411c7mD/", "BV1xx411c7mD"),
        ("https://m.bilibili.com/video/BV1xx411c7mD?p=1", "BV1xx411c7mD"),
    ],
)
def test_extract_bvid_accepts_bvid_or_url(input_value, expected):
    assert extract_bvid(input_value) == expected


@pytest.mark.parametrize(
    "input_value",
    [
        "",
        "https://example.com/video/123",
        "AV170001",
        "BV123",
    ],
)
def test_extract_bvid_rejects_invalid_values(input_value):
    with pytest.raises(ValueError):
        extract_bvid(input_value)
