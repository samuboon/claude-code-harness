# -*- coding: utf-8 -*-
"""Tests for claim_check.py. Standard library only: python test_claim_check.py"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import claim_check as cc  # noqa: E402

NOW = datetime(2026, 9, 24, tzinfo=timezone.utc)


def day(d, h=12):
    return "2026-%s-%sT%02d:00:00Z" % (d[:2], d[3:], h)


def comment(who, at, body, assoc="NONE", bot=False):
    return {"type": "comment", "at": at, "who": who, "bot": bot, "assoc": assoc, "body": body, "url": "u"}


def issue(events, state="open", number=1, assignees=(), created="2026-01-01T00:00:00Z", closed_at=None):
    return {"repo": "o/r", "number": number, "url": "https://github.com/o/r/issues/%d" % number, "title": "t",
            "state": state, "created_at": created, "closed_at": closed_at, "labels": [],
            "assignees": list(assignees), "events": events}


def codes(it, days=30, as_of=None, now=NOW):
    return [(f.code, f.who) for f in cc.judge(it, now, days, as_of)]


class ClaimSentences(unittest.TestCase):
    YES = [
        "I'd like to work on this",
        "Hi! I would like to work on this issue.",
        "Can I work on this?",
        "can i pick this up?",
        "I'll take this",
        "I will take it from here.",
        "I'd love to take this up!",
        "I'll submit a PR",
        "I will open a pull request and do some experiments.",
        "Could you please assign it to me?",
        "please assign this to me",
        "Can I be assigned to it?",
        "/assign",
        "  /take  ",
        "I'm working on this",
        "I am currently working on it",
        "I'm on it",
        "I'll look into it",
        "Let me look into this",
        "I'd be interested in working on this.",
        "I'm happy to take this on",
        "If not, I'd be happy to take it up.",
        "Not sure where to start, but I'd like to work on this",
        "Hey @someone, I would like to work on this",
        "I’ll take this",  # typographic apostrophe
        "I can help work on this.",
        "Shall I work on this?",
        # "I" left out, and asking leave
        "Hello, Is this pr open? This is my first time contributing and would like to take this up.",
        "If yes, would like to take this one.",
        "Happy to take this.",
        "Unsure what is causing this, will look into it",
        "Mind if I take this on?",
        "Would it be okay if I start working on this ?",
        "Is it okay if I take it up?",
        "Thank you, working on it",
        "Thanks !! have started working on this !!",
        "I'll be working on it!",
        "Hi all, can I get this issue assigned to me?",
        "How can I be assigned this task?",
        "If this is approved, it can be assigned to me and I can make the changes and open a PR.",
        "I would be happy to work and propose a PR for this.",
        "i would like to work on this issue if previous assignees are no longer working on it.",
        "Would it be okay if I gave it a shot?",
        "I will try this one if no one have done it before... (Will open PR later this day)",
        "can you assign this task to me?",
        "take",
        "I'd like to **take ownership of this fix**.",
        "I'm thinking of taking a look at this",
        "I want to have a try with this, but I think I will need guidance",
        "I have a possible fix:",
    ]
    NO = [
        "Is anyone working on this?",
        "Thanks, I'll try that workaround",
        "I can't work on this right now",
        "I would like to work on this but I don't have the time",
        "> I'd like to work on this",
        "```\nI'll take this\n```",
        "`I'll fix this`",
        "<!-- I'd like to work on this -->",
        "You can work on this issue without asking for it to be assigned to you.",
        "@user can you work on this?",
        "I don't think I can take this on",
        "Same problem here.",
        "I'll look into the docs",
        "Anyone is welcome to work on this",
        "Would you like to work on this?",
        "I'm not working on this anymore",
        "I'd like to work on this, but feel free to take it if you get there first",
        "I'd love to fix this, but I don't have the bandwidth",
        "@brennanb2025 is working on this",
        "This change will fix it",
        "Working on this would need a new API.",
        "Assigning to CSS then.",
        "Let me know if you want to work on this",
        "As for the working plane, I would like to take this opportunity to remind you",
        "I'll take this into account",
        "I have a fix for a different issue",
        "I don’t think I can take this on",  # typographic apostrophe
        "I have very limited time so it is highly unlikely I will be able to pick this up",
        "I'll take that back as.",
        "/assign @iamvbenz49 \nplease help on it",  # a maintainer assigning someone else
        "Take care",
        "take a look at the docs",
    ]

    def test_claims(self):
        for s in self.YES:
            with self.subTest(s=s):
                self.assertIsNotNone(cc.claim_in(s), s)

    def test_not_claims(self):
        for s in self.NO:
            with self.subTest(s=s):
                self.assertIsNone(cc.claim_in(s), s)

    def test_rule_names(self):
        self.assertEqual(cc.claim_in("/assign")[0], "command")
        self.assertEqual(cc.claim_in("please assign it to me")[0], "assign-me")
        self.assertEqual(cc.claim_in("I'll submit a PR")[0], "modal-pr")

    def test_releases(self):
        for s in ["I don't have time to work on this anymore", "Feel free to take it", "please unassign me",
                  "I'm no longer working on this", "someone else can pick this up", "I have to step back from this",
                  "I've been reassigned to a different task"]:
            with self.subTest(s=s):
                self.assertTrue(cc.release_in(s), s)
        for s in ["I'll push the fix tomorrow", "Still working on it, almost done", "Any update?"]:
            with self.subTest(s=s):
                self.assertFalse(cc.release_in(s), s)


class Judge(unittest.TestCase):
    def test_assigned_and_silent_is_gone(self):
        it = issue([comment("alice", day("07-01"), "I'd like to work on this"),
                    {"type": "assigned", "at": day("07-02"), "who": "alice", "by": "m"}])
        f = cc.judge(it, NOW, 30)
        self.assertEqual([(x.code, x.who) for x in f], [("GONE", "alice")])
        self.assertTrue(f[0].extra["still_assigned"])
        self.assertEqual(f[0].days, (NOW - cc.parse_time(day("07-01"))).days)
        self.assertIn("still assigned to them", f[0].message)

    def test_not_silent_long_enough(self):
        it = issue([comment("alice", day("09-10"), "I'd like to work on this")])
        self.assertEqual(codes(it), [])
        self.assertEqual(codes(it, days=10), [("UNANSWERED", "alice")])

    def test_boundary_days(self):
        it = issue([comment("alice", "2026-08-25T00:00:00Z", "I'll take this")])
        self.assertEqual(codes(it, days=30), [("UNANSWERED", "alice")])
        self.assertEqual(codes(it, days=31), [])

    def test_no_answer_is_unanswered(self):
        it = issue([comment("alice", day("05-01"), "Can I work on this?"),
                    comment("bob", day("05-03"), "+1 same here", assoc="CONTRIBUTOR")])
        self.assertEqual(codes(it), [("UNANSWERED", "alice")])

    def test_member_answer_is_quiet(self):
        it = issue([comment("alice", day("05-01"), "Can I work on this?"),
                    comment("maint", day("05-02"), "Sure, go ahead!", assoc="MEMBER")])
        f = cc.judge(it, NOW, 30)
        self.assertEqual([(x.code, x.who) for x in f], [("QUIET", "alice")])
        self.assertEqual(f[0].severity, "warning")
        self.assertIn("a maintainer answered, nobody assigned it", f[0].message)

    def test_member_claimant_is_quiet(self):
        it = issue([comment("maint", day("03-01"), "I'll look into it", assoc="COLLABORATOR")])
        f = cc.judge(it, NOW, 30)
        self.assertEqual([(x.code, x.who) for x in f], [("QUIET", "maint")])
        self.assertIn("collaborator", f[0].message)

    def test_unanswered_question_is_the_projects_silence(self):
        it = issue([comment("alice", day("05-01"), "I'd like to work on this"),
                    {"type": "assigned", "at": day("05-02"), "who": "alice", "by": "m"},
                    comment("maint", day("05-03"), "Thanks!", assoc="MEMBER"),
                    comment("alice", day("05-10"), "Should the option go in the config file or the CLI?")])
        f = cc.judge(it, NOW, 30)
        self.assertEqual([(x.code, x.who) for x in f], [("UNANSWERED", "alice")])
        self.assertIn("asked something nobody from the project answered", f[0].message)
        self.assertIn("still assigned to them", f[0].message)
        it["events"].append(comment("maint", day("05-12"), "The config file, please.", assoc="MEMBER"))
        self.assertEqual(codes(it), [("GONE", "alice")])

    def test_being_assigned_answers_the_question(self):
        it = issue([comment("vt", day("05-01"), "Can you assign it to me?"),
                    {"type": "assigned", "at": day("05-03"), "who": "vt", "by": "m"}])
        f = cc.judge(it, NOW, 30)
        self.assertEqual([(x.code, x.who) for x in f], [("GONE", "vt")])
        self.assertNotIn("asked something", f[0].message)

    def test_claim_on_an_issue_someone_else_holds(self):
        it = issue([{"type": "assigned", "at": day("02-01"), "who": "bob", "by": "m"},
                    comment("alice", day("05-01"), "Can I take this?")])
        self.assertEqual(codes(it), [])
        it["events"].append({"type": "unassigned", "at": day("06-01"), "who": "bob", "by": "m"})
        self.assertEqual(codes(it), [("UNANSWERED", "alice")])

    def test_relay_accounts_are_not_read(self):
        it = issue([comment("jenkins-infra-bot", day("03-01"), "I am happy to take it and do the typing."),
                    comment("swift-ci", day("03-01"), "I would like to give it a go"),
                    comment("carol", day("03-02"), "<!-- [jira_comment_id=1] --> I'll take this")])
        self.assertEqual(codes(it), [])
        it["events"].append(comment("talbot", day("03-03"), "I'll take this"))
        self.assertEqual(codes(it), [("UNANSWERED", "talbot")])

    def test_release_ends_claim(self):
        it = issue([comment("alice", day("05-01"), "I'll take this"),
                    comment("alice", day("05-20"), "Sorry, I don't have time for this anymore")])
        self.assertEqual(codes(it), [])

    def test_pull_request_delivers(self):
        it = issue([comment("alice", day("05-01"), "I'll take this"),
                    {"type": "xref", "at": day("05-05"), "who": "alice", "is_pr": True, "same_repo": True}])
        self.assertEqual(codes(it), [])

    def test_issue_mention_does_not_deliver_but_counts(self):
        it = issue([comment("alice", day("05-01"), "I'll take this"),
                    {"type": "xref", "at": day("06-01"), "who": "alice", "is_pr": False, "same_repo": True}])
        f = cc.judge(it, NOW, 30)
        self.assertEqual([x.code for x in f], ["UNANSWERED"])
        self.assertEqual(f[0].last_at, cc.parse_time(day("06-01")))

    def test_commit_resets_clock(self):
        it = issue([comment("alice", day("05-01"), "I'll take this"),
                    {"type": "commit", "at": day("09-10"), "who": "alice"}])
        self.assertEqual(codes(it), [])

    def test_later_comment_resets_clock(self):
        it = issue([comment("alice", day("05-01"), "I'll take this"),
                    comment("alice", day("09-15"), "Still on it, almost done")])
        self.assertEqual(codes(it), [])

    def test_someone_else_assigned(self):
        it = issue([comment("alice", day("05-01"), "I'll take this"),
                    {"type": "assigned", "at": day("05-10"), "who": "bob", "by": "m"}])
        self.assertEqual(codes(it), [])

    def test_unassigned(self):
        it = issue([comment("alice", day("05-01"), "I'll take this"),
                    {"type": "assigned", "at": day("05-02"), "who": "alice", "by": "m"},
                    {"type": "unassigned", "at": day("06-10"), "who": "alice", "by": "m"}])
        self.assertEqual(codes(it), [])

    def test_other_pull_request(self):
        it = issue([comment("alice", day("05-01"), "I'll take this"),
                    {"type": "xref", "at": day("05-10"), "who": "bob", "is_pr": True, "same_repo": True}])
        self.assertEqual(codes(it), [])

    def test_other_repo_pull_request_does_not_end_claim(self):
        it = issue([comment("alice", day("05-01"), "I'll take this"),
                    {"type": "xref", "at": day("05-10"), "who": "bob", "is_pr": True, "same_repo": False}])
        self.assertEqual(codes(it), [("UNANSWERED", "alice")])

    def test_closed_issue(self):
        it = issue([comment("alice", day("05-01"), "I'll take this")], state="closed", closed_at=day("06-01"))
        self.assertEqual(codes(it), [])

    def test_bot_ignored(self):
        it = issue([comment("helper[bot]", day("05-01"), "/assign"),
                    comment("welcome", day("05-01"), "I'll take this", bot=True)])
        self.assertEqual(codes(it), [])

    def test_reclaim_after_unassign(self):
        it = issue([comment("alice", day("03-01"), "I'll take this"),
                    {"type": "assigned", "at": day("03-02"), "who": "alice", "by": "m"},
                    {"type": "unassigned", "at": day("04-10"), "who": "alice", "by": "m"},
                    comment("alice", day("05-01"), "Can I take this again?")])
        f = cc.judge(it, NOW, 30)
        self.assertEqual([(x.code, x.who) for x in f], [("UNANSWERED", "alice")])
        self.assertEqual(f[0].claim_at, cc.parse_time(day("05-01")))

    def test_two_claimants_and_others_since(self):
        it = issue([comment("alice", day("03-01"), "I'll take this"),
                    {"type": "assigned", "at": day("03-02"), "who": "alice", "by": "m"},
                    comment("bob", day("05-01"), "Can I work on this?"),
                    comment("carol", day("06-01"), "I'd like to work on this")])
        f = {x.who: x for x in cc.judge(it, NOW, 30)}
        self.assertEqual(f["alice"].code, "GONE")
        self.assertEqual(f["alice"].extra["others_since"], 2)
        self.assertIn("2 others asked to take it since", f["alice"].message)
        self.assertNotIn("bob", f)  # they asked for an issue alice holds, and she still does
        self.assertNotIn("carol", f)

    def test_others_since_counts_only_after_the_silence_began(self):
        it = issue([comment("alice", day("03-01"), "I'll take this"),
                    comment("bob", day("03-05"), "Can I work on this?"),
                    comment("alice", day("03-10"), "Still on it"),
                    comment("carol", day("04-01"), "Great issue")])
        f = {x.who: x for x in cc.judge(it, NOW, 30)}
        self.assertEqual(f["alice"].extra["others_since"], 0)
        self.assertEqual(f["alice"].last_at, cc.parse_time(day("03-10")))

    def test_as_of_ignores_later_events(self):
        it = issue([comment("alice", day("01-10"), "I'll take this"),
                    {"type": "assigned", "at": day("01-11"), "who": "alice", "by": "m"},
                    comment("alice", day("06-01"), "Done soon"),
                    {"type": "closed", "at": day("07-01"), "who": "m"}],
                   state="closed", closed_at=day("07-01"))
        as_of = datetime(2026, 3, 24, 23, 59, 59, tzinfo=timezone.utc)
        self.assertEqual(codes(it, as_of=as_of, now=as_of), [("GONE", "alice")])
        self.assertEqual(codes(it), [])

    def test_as_of_before_created(self):
        it = issue([comment("alice", day("05-01"), "I'll take this")], created=day("05-01"))
        as_of = datetime(2026, 3, 1, tzinfo=timezone.utc)
        self.assertEqual(codes(it, as_of=as_of, now=as_of), [])

    def test_as_of_reopened(self):
        it = issue([comment("alice", day("01-10"), "I'll take this"),
                    {"type": "closed", "at": day("02-01"), "who": "m"},
                    {"type": "reopened", "at": day("02-05"), "who": "m"}])
        as_of = datetime(2026, 3, 24, tzinfo=timezone.utc)
        self.assertEqual(codes(it, as_of=as_of, now=as_of), [("UNANSWERED", "alice")])
        as_of2 = datetime(2026, 2, 3, tzinfo=timezone.utc)
        self.assertEqual(codes(it, days=5, as_of=as_of2, now=as_of2), [])

    def test_current_assignees_used_when_no_events(self):
        it = issue([comment("alice", day("05-01"), "I'll take this")], assignees=["alice"])
        f = cc.judge(it, NOW, 30)
        self.assertEqual([x.code for x in f], ["GONE"])
        self.assertTrue(f[0].extra["still_assigned"])

    def test_run_orders_errors_first_and_unchecked(self):
        a = issue([comment("alice", day("08-01"), "I'll take this"),
                   {"type": "assigned", "at": day("08-02"), "who": "alice", "by": "m"}], number=1)
        b = issue([comment("m", day("05-01"), "I'll look into it", assoc="MEMBER")], number=2)
        c = issue([], number=3)
        c["unreadable"] = "HTTP 502"
        d = issue([comment("dan", day("03-01"), "Can I work on this?")], number=4)
        f = cc.run([a, b, c, d], NOW, 30)
        self.assertEqual([x.code for x in f], ["GONE", "UNANSWERED", "QUIET", "UNCHECKED"])


class Rest(unittest.TestCase):
    def test_normalise(self):
        it = {"number": 7, "html_url": "h", "title": "t", "state": "open", "created_at": "2026-01-01T00:00:00Z",
              "user": {"login": "x"}, "labels": [{"name": "good first issue"}], "assignees": [{"login": "alice"}]}
        tl = [
            {"event": "commented", "created_at": day("05-01"), "user": {"login": "alice", "type": "User"},
             "author_association": "NONE", "body": "I'll take this", "html_url": "c"},
            {"event": "commented", "created_at": day("05-01"), "user": {"login": "ci[bot]", "type": "Bot"},
             "author_association": "NONE", "body": "/assign"},
            {"event": "assigned", "created_at": day("05-02"), "assignee": {"login": "alice"}, "actor": {"login": "m"}},
            {"event": "cross-referenced", "created_at": day("05-03"), "actor": {"login": "bob"},
             "source": {"issue": {"user": {"login": "bob"}, "pull_request": {}, "state": "open", "html_url": "p",
                                  "repository": {"full_name": "other/repo"}}}},
            {"event": "referenced", "created_at": day("05-04"), "actor": {"login": "alice"}, "commit_id": "abc"},
            {"event": "labeled", "created_at": day("05-04")},
        ]
        n = cc.normalise_rest("o/r", it, tl)
        self.assertEqual([e["type"] for e in n["events"]], ["comment", "comment", "assigned", "xref", "commit"])
        self.assertTrue(n["events"][1]["bot"])
        self.assertTrue(n["events"][3]["is_pr"])
        self.assertFalse(n["events"][3]["same_repo"])
        self.assertEqual(n["labels"], ["good first issue"])
        f = cc.judge(n, NOW, 30)
        self.assertEqual([(x.code, x.who) for x in f], [("GONE", "alice")])

    def test_fetch_marks_unreadable(self):
        class Fake:
            token = "x"

            def issues(self, repo, labels, mx):
                return [{"number": 1, "comments": 2, "state": "open"}, {"number": 2, "comments": 0, "state": "open"}]

            def timeline(self, repo, n):
                raise cc.urllib.error.URLError("boom")

            def closing_prs(self, repo, numbers):
                raise AssertionError("an unread issue must not be asked about")
        out = cc.fetch("o/r", gh=Fake(), log=None)
        self.assertIn("unreadable", out[0])
        self.assertNotIn("unreadable", out[1])

    def test_fetch_adds_closing_prs(self):
        class Fake:
            token = "x"
            asked = None

            def issues(self, repo, labels, mx):
                return [{"number": 5, "comments": 1, "state": "open"}]

            def timeline(self, repo, n):
                return [{"event": "commented", "created_at": day("05-01"), "user": {"login": "alice"},
                         "author_association": "NONE", "body": "I'll take this"}]

            def closing_prs(self, repo, numbers):
                Fake.asked = numbers
                return {5: [{"number": 9, "at": day("05-03"), "state": "OPEN", "who": "alice"}]}
        log = io.StringIO()
        out = cc.fetch("o/r", gh=Fake(), log=log)
        self.assertEqual(Fake.asked, [5])
        self.assertEqual(out[0]["closed_by"][0]["number"], 9)
        self.assertEqual(cc.judge(out[0], NOW, 30), [])  # her "fixes #5" pull request delivered it
        self.assertIn("this token cannot see them", log.getvalue())  # 1 closing pull request, 0 cross-references

    def test_closing_pr_of_someone_else_ends_claim(self):
        it = issue([comment("alice", day("05-01"), "I'll take this")])
        it["closed_by"] = [{"number": 9, "at": day("05-03"), "state": "OPEN", "who": "bob"}]
        self.assertEqual(codes(it), [])
        it["closed_by"] = [{"number": 9, "at": day("04-03"), "state": "CLOSED", "who": "bob"}]
        self.assertEqual(codes(it), [("UNANSWERED", "alice")])  # before her claim: hers is still open


class Confirm(unittest.TestCase):
    def test_mentions(self):
        self.assertTrue(cc.mentions("Fixes #12", 12))
        self.assertTrue(cc.mentions("see https://github.com/o/r/issues/12.", 12))
        self.assertFalse(cc.mentions("Fixes #123", 12))
        self.assertFalse(cc.mentions("Fixes o/r#12x", 12))
        self.assertFalse(cc.mentions("version 1#12", 12))

    def test_confirm(self):
        a = cc.judge(issue([comment("m", day("05-01"), "I'll look into it", assoc="MEMBER")], number=12), NOW, 30)[0]
        b = cc.judge(issue([comment("n", day("05-01"), "I'll look into it", assoc="MEMBER")], number=13), NOW, 30)[0]
        c = cc.judge(issue([comment("o", day("05-01"), "I'll look into it", assoc="MEMBER")], number=14), NOW, 30)[0]
        asked = []

        def search(repo, who, since):
            asked.append((repo, who, since))
            return {"m": [{"number": 1, "title": "Fix the thing", "body": "Closes #12"}],
                    "n": [{"number": 2, "title": "Unrelated", "body": "fixes #130"}]}.get(who)
        kept, dropped = cc.confirm([a, b, c], search)
        self.assertEqual([f.who for f in dropped], ["m"])
        self.assertEqual(dropped[0].extra["delivered_in"], 1)
        self.assertEqual([f.who for f in kept], ["n", "o"])
        self.assertIn("1 other pull request from them here since", kept[0].message)
        self.assertEqual(kept[0].extra["prs_since"], 1)
        self.assertFalse(kept[1].extra["searched"])
        self.assertIn("could not be searched", kept[1].message)
        self.assertEqual(asked[0], ("o/r", "m", "2026-05-01"))

    def test_confirm_with_mention_search(self):
        it = issue([comment("alice", day("05-01"), "I'll take this"), comment("bob", day("05-02"), "Can I take this?")],
                   number=7)
        two = cc.judge(it, NOW, 30)
        calls = []

        def mention(repo, number, since):
            calls.append((repo, number, since))
            return [{"number": 50, "title": "Speed up", "body": "Refs #7", "who": "carol", "at": day("05-02")}]
        kept, dropped = cc.confirm(two, lambda r, w, s: [], mention)
        self.assertEqual(sorted(f.who for f in dropped), ["alice", "bob"])
        self.assertEqual(dropped[0].extra["moved_on_in"], 50)
        self.assertEqual(calls, [("o/r", 7, "2026-05-01")])  # one search per issue, from its earliest claim

        def mention_early(repo, number, since):
            return [{"number": 49, "title": "x", "body": "Refs #7", "who": "carol", "at": day("05-01", 20)}]
        kept, dropped = cc.confirm(cc.judge(it, NOW, 30), lambda r, w, s: [], mention_early)
        self.assertEqual([f.who for f in kept], ["bob"])  # carol's came before bob's claim
        own = cc.judge(it, NOW, 30)
        kept, dropped = cc.confirm(own[:1], lambda r, w, s: [],
                                   lambda r, n, s: [{"number": 51, "title": "x", "body": "fixes #7", "who": "Alice"}])
        self.assertEqual(dropped[0].extra["delivered_in"], 51)
        kept, dropped = cc.confirm(own[:1], lambda r, w, s: [], lambda r, n, s: None)
        self.assertEqual(len(kept), 1)
        self.assertFalse(kept[0].extra["searched"])
        kept, dropped = cc.confirm(own[:1], lambda r, w, s: [],
                                   lambda r, n, s: [{"number": 52, "title": "x", "body": "fixes #70", "who": "carol"}])
        self.assertEqual(len(kept), 1)
        self.assertTrue(kept[0].extra["searched"])


class Main(unittest.TestCase):
    def _run(self, items, *args):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "i.json")
            with open(p, "w", encoding="utf-8") as f:
                json.dump({"items": items}, f)
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = cc.main(["--from-json", p, "--as-of", "2026-09-24"] + list(args))
            return code, out.getvalue(), err.getvalue()

    def test_exit_codes(self):
        gone = issue([comment("m", day("05-01"), "I'll look into it", assoc="MEMBER"),
                      {"type": "assigned", "at": day("05-01"), "who": "m", "by": "m"}])
        quiet = issue([comment("q", day("05-01"), "I'll look into it", assoc="MEMBER")], number=4)
        ans = issue([comment("alice", day("05-01"), "Can I work on this?")], number=2)
        bad = issue([], number=3)
        bad["unreadable"] = "HTTP 500"
        self.assertEqual(self._run([gone])[0], 1)
        self.assertEqual(self._run([ans, quiet])[0], 0)
        self.assertEqual(self._run([ans, bad])[0], 2)
        self.assertEqual(self._run([])[0], 0)

    def test_json_and_label_filter(self):
        a = issue([comment("m", day("05-01"), "I'll look into it", assoc="MEMBER")])
        a["labels"] = ["Good First Issue"]
        b = issue([comment("m", day("05-01"), "I'll look into it", assoc="MEMBER")], number=2)
        code, out, _ = self._run([a, b], "--json", "--label", "good first issue")
        rows = json.loads(out)
        self.assertEqual([r["number"] for r in rows], [1])
        self.assertEqual(rows[0]["claim_at"], "2026-05-01")

    def test_search_is_wired_to_both_searches(self):
        class FakeGitHub:
            def __init__(self):
                pass

            def search_prs(self, repo, who, since):
                return []

            def search_mentions(self, repo, number, since):
                return [{"number": 9, "title": "t", "body": "closes #%d" % number, "who": "zed", "at": day("06-01")}]
        real = cc.GitHub
        cc.GitHub = FakeGitHub
        try:
            a = issue([comment("m", day("05-01"), "I'll look into it", assoc="MEMBER"),
                       {"type": "assigned", "at": day("05-01"), "who": "m", "by": "m"}])
            code, out, err = self._run([a], "--search")
            self.assertEqual(code, 0)
            self.assertIn("1 more left out: a pull request names the issue", err)
            code, out, err = self._run([a])  # --from-json without --search does not search
            self.assertEqual(code, 1)
        finally:
            cc.GitHub = real

    def test_summary_line(self):
        a = issue([comment("m", day("05-01"), "I'll look into it", assoc="MEMBER"),
                   {"type": "assigned", "at": day("05-01"), "who": "m", "by": "m"}])
        b = issue([comment("q", day("05-01"), "I'll look into it", assoc="MEMBER")], number=2)
        code, out, err = self._run([a, b], "--days", "60")
        self.assertIn("1 GONE, 1 QUIET, 0 UNANSWERED", err)
        self.assertIn("60+ days", err)
        self.assertIn("o/r#1: error GONE @m", out)
        self.assertIn("o/r#2: warning QUIET @q", out)


if __name__ == "__main__":
    unittest.main(verbosity=1)
