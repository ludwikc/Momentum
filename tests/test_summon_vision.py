"""Tests for the vision (image-attachment) pure helpers in summon.py.

The cog gates images to administrators and passes the summoning message's
attachments through these helpers; here we cover the pure logic only:
URL extraction (image filtering + cap) and the multimodal content builder
(exact Chat Completions structure, plain-string passthrough without images).
"""
import unittest
from types import SimpleNamespace

from summon import MAX_SUMMON_IMAGES, build_multimodal_content, extract_image_urls


def _att(content_type, url):
    return SimpleNamespace(content_type=content_type, url=url)


class ExtractImageUrlsTest(unittest.TestCase):
    def test_keeps_only_images_in_order(self):
        atts = [
            _att("image/png", "https://cdn/a.png"),
            _att("video/mp4", "https://cdn/b.mp4"),
            _att("application/pdf", "https://cdn/c.pdf"),
            _att("image/jpeg", "https://cdn/d.jpg"),
        ]
        self.assertEqual(
            extract_image_urls(atts), ["https://cdn/a.png", "https://cdn/d.jpg"]
        )

    def test_caps_at_four_by_default(self):
        atts = [_att("image/png", f"https://cdn/{i}.png") for i in range(7)]
        got = extract_image_urls(atts)
        self.assertEqual(len(got), 4)
        self.assertEqual(MAX_SUMMON_IMAGES, 4)
        self.assertEqual(got, [f"https://cdn/{i}.png" for i in range(4)])

    def test_custom_limit(self):
        atts = [_att("image/png", f"https://cdn/{i}.png") for i in range(3)]
        self.assertEqual(extract_image_urls(atts, limit=1), ["https://cdn/0.png"])

    def test_none_content_type_or_missing_url_skipped(self):
        atts = [
            _att(None, "https://cdn/a.png"),       # Discord may leave type unset
            _att("", "https://cdn/b.png"),
            _att("image/png", None),
            _att("image/png", ""),
            SimpleNamespace(),                      # neither attribute present
        ]
        self.assertEqual(extract_image_urls(atts), [])

    def test_empty_and_none_input(self):
        self.assertEqual(extract_image_urls([]), [])
        self.assertEqual(extract_image_urls(None), [])


class BuildMultimodalContentTest(unittest.TestCase):
    def test_no_images_returns_plain_string_unchanged(self):
        text = "Momentum, co o tym sądzisz?"
        self.assertIs(build_multimodal_content(text, None), text)
        self.assertIs(build_multimodal_content(text, []), text)

    def test_with_images_builds_exact_parts_structure(self):
        got = build_multimodal_content(
            "opisz to", ["https://cdn/a.png", "https://cdn/b.jpg"]
        )
        self.assertEqual(
            got,
            [
                {"type": "text", "text": "opisz to"},
                {"type": "image_url", "image_url": {"url": "https://cdn/a.png"}},
                {"type": "image_url", "image_url": {"url": "https://cdn/b.jpg"}},
            ],
        )

    def test_single_image(self):
        got = build_multimodal_content("x", ["u"])
        self.assertEqual(
            got,
            [
                {"type": "text", "text": "x"},
                {"type": "image_url", "image_url": {"url": "u"}},
            ],
        )


if __name__ == "__main__":
    unittest.main()
