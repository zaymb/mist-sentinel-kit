import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sentinel import Sentinel


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.state_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.state_dir.cleanup)
        self.sentinel = Sentinel(
            {"repo": "example/repo", "subscriptions": [{"match": "*", "events": "*"}]},
            self.state_dir.name,
            dry_run=True,
        )

    def test_closed_issue_reopening_is_visible(self):
        old = {"14": {"title": "P2: tree", "state": "CLOSED", "comments": 1}}
        new = {"14": {"title": "P2: tree", "state": "OPEN", "comments": 1}}

        events = self.sentinel.diff_issues(old, new)

        self.assertEqual([event["event"] for event in events], ["issue_reopened"])

    def test_closed_pr_reopening_is_visible_without_a_new_commit(self):
        old = {
            "20": {
                "title": "P2: tree",
                "state": "CLOSED",
                "comments": 1,
                "head": "same-head",
                "review": "",
            }
        }
        new = {
            "20": {
                "title": "P2: tree",
                "state": "OPEN",
                "comments": 1,
                "head": "same-head",
                "review": "",
            }
        }

        events = self.sentinel.diff_prs(old, new)

        self.assertEqual([event["event"] for event in events], ["pr_reopened"])

    def test_reopened_pr_with_new_head_reports_both_facts(self):
        old = {
            "20": {
                "title": "P2: tree",
                "state": "CLOSED",
                "comments": 1,
                "head": "old-head",
                "review": "",
            }
        }
        new = {
            "20": {
                "title": "P2: tree",
                "state": "OPEN",
                "comments": 1,
                "head": "new-head",
                "review": "",
            }
        }

        events = self.sentinel.diff_prs(old, new)

        self.assertEqual(
            [event["event"] for event in events],
            ["pr_head", "pr_reopened"],
        )


if __name__ == "__main__":
    unittest.main()
