#!/usr/bin/env python3
"""sentinel.py — a small, self-hosted watcher for one GitHub repo.

Polls issues and pull requests with the `gh` CLI, diffs against a local state
directory, and emits one line per change. Delivery is pluggable: whatever you
put in `notify_cmd` gets the line. No bot tokens, no network calls of its own.

Single run, then exit. Scheduling belongs to cron / launchd / systemd timers.

Usage:
    python3 sentinel.py [--config config.json] [--state-dir state] [--dry-run]

Standard library only. External dependency: an authenticated `gh` CLI.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shlex
import subprocess
import sys

# ---------------------------------------------------------------- constants

TITLE_MAX = 40
GH_TIMEOUT = 60

ALL_EVENTS = [
    "new_issue",
    "issue_reopened",
    "issue_comment",
    "issue_closed",
    "new_pr",
    "pr_reopened",
    "pr_head",
    "pr_review",
    "pr_comment",
    "pr_merged",
    "pr_closed",
]

DEFAULT_INSTANT = [
    "new_issue",
    "issue_reopened",
    "new_pr",
    "pr_reopened",
    "pr_merged",
    "pr_closed",
    "pr_review",
]

PKG_RE = re.compile(r"(?<![0-9A-Za-z])P([1-9][0-9]*)(?![0-9])", re.IGNORECASE)
PKG_MATCH_RE = re.compile(r"P[1-9][0-9]*", re.IGNORECASE)


# ------------------------------------------------------------------ helpers

def now_hm() -> str:
    return datetime.datetime.now().strftime("%H:%M")


def stamp() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def truncate(text: str, limit: int = TITLE_MAX) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def package_tag(title: str) -> str | None:
    """Return 'P4' if the title carries a positive package marker, else None."""
    m = PKG_RE.search(title or "")
    return "P" + m.group(1) if m else None


def read_json(path: str, fallback):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return fallback


def write_json(path: str, data) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, path)


# -------------------------------------------------------------------- state

class Sentinel:
    def __init__(self, config: dict, state_dir: str, dry_run: bool = False):
        self.cfg = config
        self.state_dir = state_dir
        self.dry_run = dry_run
        self.repo = config.get("repo", "")
        self.error_log = os.path.join(state_dir, "errors.log")
        os.makedirs(state_dir, exist_ok=True)

    # ---- logging -------------------------------------------------------

    def log_error(self, message: str) -> None:
        """One line, no retry storm. Callers exit right after."""
        try:
            with open(self.error_log, "a", encoding="utf-8") as fh:
                fh.write(f"{stamp()} {' '.join(str(message).split())}\n")
        except OSError:
            pass

    # ---- gh ------------------------------------------------------------

    def gh_json(self, args: list[str]):
        """Run gh and parse JSON. Returns None on any failure (logged once)."""
        try:
            proc = subprocess.run(
                ["gh"] + args,
                capture_output=True,
                text=True,
                timeout=GH_TIMEOUT,
            )
        except FileNotFoundError:
            self.log_error("gh not found on PATH")
            return None
        except subprocess.TimeoutExpired:
            self.log_error(f"gh timeout: {' '.join(args[:3])}")
            return None
        if proc.returncode != 0:
            self.log_error(f"gh failed rc={proc.returncode}: {proc.stderr[:300]}")
            return None
        try:
            return json.loads(proc.stdout or "[]")
        except ValueError:
            self.log_error("gh returned non-JSON output")
            return None

    def fetch_issues(self):
        limit = str(self.cfg.get("issue_limit", 100))
        return self.gh_json([
            "issue", "list", "-R", self.repo,
            "--state", "all", "--limit", limit,
            "--json", "number,title,state,comments",
        ])

    def fetch_prs(self):
        limit = str(self.cfg.get("pr_limit", 60))
        return self.gh_json([
            "pr", "list", "-R", self.repo,
            "--state", "all", "--limit", limit,
            "--json", "number,title,state,comments,headRefOid,reviewDecision",
        ])

    # ---- diffing -------------------------------------------------------

    @staticmethod
    def snapshot_issues(rows) -> dict:
        return {
            str(r["number"]): {
                "title": r.get("title", ""),
                "state": r.get("state", ""),
                "comments": len(r.get("comments") or []),
            }
            for r in rows
        }

    @staticmethod
    def snapshot_prs(rows) -> dict:
        return {
            str(r["number"]): {
                "title": r.get("title", ""),
                "state": r.get("state", ""),
                "comments": len(r.get("comments") or []),
                "head": (r.get("headRefOid") or "")[:10],
                "review": r.get("reviewDecision") or "",
            }
            for r in rows
        }

    def diff_issues(self, old: dict, new: dict) -> list[dict]:
        events = []
        for num, cur in new.items():
            prev = old.get(num)
            if prev is None:
                if cur.get("state", "OPEN") == "OPEN":
                    events.append(self.mk(num, cur["title"], "new_issue", ""))
                continue
            delta = cur["comments"] - prev.get("comments", 0)
            if delta > 0:
                events.append(self.mk(
                    num, cur["title"], "issue_comment",
                    f"+{delta} (共{cur['comments']})",
                ))
            if cur.get("state") == "CLOSED" and prev.get("state") != "CLOSED":
                events.append(self.mk(num, cur["title"], "issue_closed", ""))
            elif cur.get("state") == "OPEN" and prev.get("state") == "CLOSED":
                events.append(self.mk(num, cur["title"], "issue_reopened", ""))
        return events

    def diff_prs(self, old: dict, new: dict) -> list[dict]:
        events = []
        for num, cur in new.items():
            prev = old.get(num)
            if prev is None:
                if cur.get("state") == "OPEN":
                    events.append(self.mk(num, cur["title"], "new_pr", ""))
                continue
            if cur.get("head") and prev.get("head") and cur["head"] != prev["head"]:
                events.append(self.mk(num, cur["title"], "pr_head", "新 commit"))
            if cur.get("review", "") != prev.get("review", ""):
                events.append(self.mk(
                    num, cur["title"], "pr_review",
                    cur.get("review") or "CLEARED",
                ))
            delta = cur["comments"] - prev.get("comments", 0)
            if delta > 0:
                events.append(self.mk(
                    num, cur["title"], "pr_comment",
                    f"+{delta} (共{cur['comments']})",
                ))
            if cur.get("state") != prev.get("state"):
                if cur.get("state") == "MERGED":
                    events.append(self.mk(num, cur["title"], "pr_merged", ""))
                elif cur.get("state") == "CLOSED":
                    events.append(self.mk(num, cur["title"], "pr_closed", ""))
                elif cur.get("state") == "OPEN":
                    events.append(self.mk(num, cur["title"], "pr_reopened", ""))
        return events

    # ---- event shaping -------------------------------------------------

    def mk(self, number: str, title: str, event: str, detail: str) -> dict:
        tag = package_tag(title) or f"#{number}"
        # 订阅可带自定义 label：命中的第一条订阅若配了 label，覆盖默认标签
        sub = self.matching_sub({"event": event, "number": str(number), "title": title})
        if isinstance(sub, dict) and isinstance(sub.get("label"), str) and sub["label"]:
            tag = sub["label"]
        parts = [f"[{tag}]", event]
        if detail:
            parts.append(detail)
        parts.append(truncate(title))
        if not tag.startswith("#"):
            parts.append(f"(#{number})")
        return {
            "number": number,
            "title": title,
            "event": event,
            "line": f"{now_hm()} " + " ".join(parts),
        }

    # ---- subscriptions -------------------------------------------------

    def subscribed(self, ev: dict) -> bool:
        return self.matching_sub(ev) is not None

    def matching_sub(self, ev: dict):
        """返回第一条命中的订阅（供自定义 label 用），没有则 None。"""
        subs = self.cfg.get("subscriptions") or []
        for sub in subs:
            if not isinstance(sub, dict):
                continue
            if not self.match_item(sub.get("match", "*"), ev):
                continue
            wanted = sub.get("events", "*")
            if wanted == "*" or wanted == ["*"]:
                return sub
            if isinstance(wanted, list) and ev["event"] in wanted:
                return sub
        return None

    @staticmethod
    def match_item(match, ev: dict) -> bool:
        if not isinstance(match, str) or match == "*":
            return True
        match = match.strip()
        if match.startswith("#"):
            return match[1:] == ev["number"]
        if match.isdigit():
            return match == ev["number"]
        # 包号必须完整匹配：订 P1 不得把 P10 的事件也收进来。
        if PKG_MATCH_RE.fullmatch(match):
            return package_tag(ev["title"] or "") == match.upper()
        return match.lower() in (ev["title"] or "").lower()

    # ---- delivery ------------------------------------------------------

    def deliver(self, lines: list[str]) -> None:
        cmd_tpl = self.cfg.get("notify_cmd") or ""
        for line in lines:
            if self.dry_run or not cmd_tpl:
                print(line, flush=True)
                continue
            cmd = cmd_tpl.replace("{line}", shlex.quote(line))
            try:
                proc = subprocess.run(
                    cmd, shell=True, capture_output=True, text=True, timeout=30
                )
                if proc.returncode != 0:
                    self.log_error(
                        f"notify_cmd rc={proc.returncode}: {proc.stderr[:200]}"
                    )
                elif proc.stdout.strip():
                    print(proc.stdout.rstrip(), flush=True)
            except subprocess.TimeoutExpired:
                self.log_error("notify_cmd timeout")
            except OSError as exc:
                self.log_error(f"notify_cmd error: {exc}")

    # ---- main pass -----------------------------------------------------

    def run(self) -> int:
        if not self.repo:
            self.log_error("config has no 'repo'")
            return 1

        issues_path = os.path.join(self.state_dir, "issues.json")
        prs_path = os.path.join(self.state_dir, "prs.json")
        batch_path = os.path.join(self.state_dir, "pending-batch.json")

        rows_i = self.fetch_issues()
        if rows_i is None:
            return 0  # quiet failure; the one line is already in errors.log
        rows_p = self.fetch_prs()
        if rows_p is None:
            return 0

        old_i = read_json(issues_path, None)
        old_p = read_json(prs_path, None)
        new_i = self.snapshot_issues(rows_i)
        new_p = self.snapshot_prs(rows_p)

        # First run for either source only writes a baseline — no backlog dump.
        events = []
        if old_i is not None:
            events += self.diff_issues(old_i, new_i)
        if old_p is not None:
            events += self.diff_prs(old_p, new_p)

        write_json(issues_path, new_i)
        write_json(prs_path, new_p)

        if old_i is None and old_p is None:
            return 0

        events = [e for e in events if self.subscribed(e)]

        digest = self.cfg.get("digest") or {}
        instant = digest.get("instant_events", DEFAULT_INSTANT)
        try:
            window = int(digest.get("batch_window_runs", 1))
        except (TypeError, ValueError):
            window = 1
        window = max(1, window)

        pending_state = read_json(batch_path, {}) or {}
        pending = list(pending_state.get("lines") or [])
        runs = int(pending_state.get("runs") or 0)

        out = []
        for ev in events:
            sub = self.matching_sub(ev)
            sub_instant = isinstance(sub, dict) and sub.get("instant") is True
            if instant == "*" or ev["event"] in instant or sub_instant:
                out.append(ev["line"])
            else:
                pending.append(ev["line"])

        runs += 1
        if pending and runs >= window:
            out.extend(pending)
            pending, runs = [], 0
        elif not pending:
            runs = 0

        write_json(batch_path, {"runs": runs, "lines": pending})

        if out:
            self.deliver(out)
        return 0


# --------------------------------------------------------------------- cli

def main(argv=None) -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description="One-shot GitHub repo sentinel.")
    ap.add_argument("--config", default=os.path.join(here, "config.json"))
    ap.add_argument("--state-dir", default=None,
                    help="default: state/ next to the config file")
    ap.add_argument("--dry-run", action="store_true",
                    help="print event lines instead of running notify_cmd")
    args = ap.parse_args(argv)

    cfg = read_json(args.config, None)
    if cfg is None:
        sys.stderr.write(f"cannot read config: {args.config}\n")
        return 1

    state_dir = args.state_dir or cfg.get("state_dir") or os.path.join(
        os.path.dirname(os.path.abspath(args.config)), "state"
    )
    return Sentinel(cfg, state_dir, dry_run=args.dry_run).run()


if __name__ == "__main__":
    sys.exit(main())
