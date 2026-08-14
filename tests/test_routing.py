import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sentinel import Sentinel, package_tag


class RoutingTests(unittest.TestCase):
    def make_sentinel(self, subscriptions):
        state_dir = tempfile.TemporaryDirectory()
        self.addCleanup(state_dir.cleanup)
        return Sentinel(
            {"repo": "example/repo", "subscriptions": subscriptions},
            state_dir.name,
            dry_run=True,
        )

    def test_automatic_package_tag_accepts_unbounded_digits(self):
        self.assertEqual(package_tag("认领件 P10：下一批"), "P10")
        self.assertEqual(package_tag("P99 final"), "P99")
        self.assertEqual(package_tag("P1000 future"), "P1000")

    def test_package_subscription_does_not_leak_into_longer_number(self):
        sentinel = self.make_sentinel([{"match": "P1", "events": "*"}])

        p1 = {"event": "new_issue", "number": "1", "title": "认领件 P1：存储"}
        p10 = {"event": "new_issue", "number": "10", "title": "认领件 P10：新主线"}

        self.assertTrue(sentinel.subscribed(p1))
        self.assertFalse(sentinel.subscribed(p10))

    def test_custom_label_routes_a_non_package_mainline(self):
        sentinel = self.make_sentinel(
            [{"match": "memory-v2", "label": "M4-next", "events": "*"}]
        )

        event = sentinel.mk(
            "42",
            "memory-v2: durable store",
            "new_issue",
            "",
        )

        self.assertTrue(sentinel.subscribed(event))
        self.assertIn("[M4-next] new_issue", event["line"])
        self.assertTrue(event["line"].endswith("(#42)"))

    def test_unlabelled_non_package_title_falls_back_to_issue_number(self):
        sentinel = self.make_sentinel([{"match": "*", "events": "*"}])

        event = sentinel.mk("73", "new architecture line", "new_pr", "")

        self.assertEqual(event["line"].split()[1], "[#73]")

    def test_first_matching_subscription_owns_the_label(self):
        sentinel = self.make_sentinel(
            [
                {"match": "memory", "label": "specific", "events": "*"},
                {"match": "*", "label": "all", "events": "*"},
            ]
        )

        event = sentinel.mk("7", "memory roadmap", "pr_head", "new commit")

        self.assertIn("[specific] pr_head", event["line"])


if __name__ == "__main__":
    unittest.main()
