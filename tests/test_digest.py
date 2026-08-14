import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sentinel import Sentinel


class DigestTests(unittest.TestCase):
    def make_sentinel(self, subscriptions, digest=None):
        state_dir = tempfile.TemporaryDirectory()
        self.addCleanup(state_dir.cleanup)
        config = {
            "repo": "example/repo",
            "subscriptions": subscriptions,
            "digest": digest or {"batch_window_runs": 5},
        }
        sentinel = Sentinel(config, state_dir.name, dry_run=True)
        sentinel.fetch_issues = lambda: []
        delivered = []
        sentinel.deliver = delivered.extend
        return sentinel, state_dir.name, delivered

    @staticmethod
    def pr(comment_count):
        return [{
            "number": 19,
            "title": "P5: migration",
            "state": "OPEN",
            "comments": [{}] * comment_count,
            "headRefOid": "a" * 40,
            "reviewDecision": "",
        }]

    def run_comment_change(self, sentinel):
        sentinel.fetch_prs = lambda: self.pr(0)
        sentinel.run()
        sentinel.fetch_prs = lambda: self.pr(1)
        sentinel.run()

    def test_comments_are_batched_by_default(self):
        sentinel, state_dir, delivered = self.make_sentinel(
            [{"match": "P5", "events": "*"}]
        )

        self.run_comment_change(sentinel)

        self.assertEqual(delivered, [])
        with open(os.path.join(state_dir, "pending-batch.json"), encoding="utf-8") as fh:
            pending = json.load(fh)
        self.assertEqual(len(pending["lines"]), 1)
        self.assertIn("pr_comment", pending["lines"][0])

    def test_subscription_can_make_its_comments_instant(self):
        sentinel, state_dir, delivered = self.make_sentinel(
            [{"match": "P5", "events": "*", "instant": True}]
        )

        self.run_comment_change(sentinel)

        self.assertEqual(len(delivered), 1)
        self.assertIn("pr_comment", delivered[0])
        with open(os.path.join(state_dir, "pending-batch.json"), encoding="utf-8") as fh:
            pending = json.load(fh)
        self.assertEqual(pending["lines"], [])

    def test_global_all_instant_option_is_preserved(self):
        sentinel, _state_dir, delivered = self.make_sentinel(
            [{"match": "*", "events": "*"}],
            {"instant_events": "*", "batch_window_runs": 5},
        )

        self.run_comment_change(sentinel)

        self.assertEqual(len(delivered), 1)
        self.assertIn("pr_comment", delivered[0])


if __name__ == "__main__":
    unittest.main()
