import html
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from notifiers.telegram_expandable import TELEGRAM_TEXT_LIMIT, render_html, utf16_length


class TelegramNotifierTests(unittest.TestCase):
    def visible_text(self, rendered: str) -> str:
        without_tags = rendered.replace("<blockquote expandable>", "").replace(
            "</blockquote>", ""
        )
        return html.unescape(without_tags)

    def test_multiline_body_becomes_an_escaped_expandable_list(self):
        event = (
            "18:00 [P5] pr_comment +2 (#19)\n"
            "「first」\n<b>不是标签</b> & 正文\n——\n"
            "「second」\n下一条"
        )

        rendered = render_html(event)

        self.assertIn("<blockquote expandable>", rendered)
        self.assertIn("1. 「first」", rendered)
        self.assertIn("2. 「second」", rendered)
        self.assertIn("&lt;b&gt;不是标签&lt;/b&gt; &amp; 正文", rendered)
        self.assertNotIn("<b>不是标签</b>", rendered)

    def test_message_is_truncated_to_telegram_limit_in_utf16_units(self):
        rendered = render_html("18:00 [P5] pr_comment +1 (#19)\n「a」\n" + "🦊" * 5000)

        self.assertLessEqual(utf16_length(self.visible_text(rendered)), TELEGRAM_TEXT_LIMIT)
        self.assertIn("…", rendered)

    def test_event_without_body_stays_plain(self):
        rendered = render_html("18:00 [P4] pr_merged (#16)")

        self.assertNotIn("blockquote", rendered)


if __name__ == "__main__":
    unittest.main()
