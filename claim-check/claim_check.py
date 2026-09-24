# -*- coding: utf-8 -*-
"""claim-check -- find the "I'd like to work on this" comments on open GitHub issues whose
author then went quiet.

    python claim_check.py OWNER/NAME [--days 30] [--label NAME ...] [--as-of YYYY-MM-DD] [--json]
    python claim_check.py --from-json issues.json [--days 30] [--as-of YYYY-MM-DD] [--json]

A comment that says "I'll take this" does two things. It tells the next volunteer to look
elsewhere, and -- once a maintainer assigns it -- it takes the issue off every
`no:assignee` list, which is where the next volunteer looks. Nothing expires either of them.
Stale bots count days since *any* activity, and every "is anyone working on this?" resets that
clock. Unassign actions count days since the *assignment*, and most claims are never assigned.

This reads each open issue's timeline and, for every person who claimed it, asks one question:
has that person done anything on it since? A later comment, a commit that references it, or a
pull request that mentions it counts. A comment in which they let it go ("I don't have time
anymore, feel free to take it") ends the claim. So does the project moving on: unassigning them,
assigning someone else, or a pull request from someone else -- including one the timeline does
not show, found by searching the repository's pull requests for the issue number. A claim made
while someone else holds the issue, who still does, is not theirs to be quiet about. What is
left, after `--days` of silence, is reported.

Findings (`error` makes the exit status 1; `warning` does not)
  GONE        error    the issue is still assigned to them, and nothing from them since --
                       it is off every `no:assignee` list until someone notices
  QUIET       warning  not assigned; a maintainer answered (or they are one), then nothing
                       from them -- often the answer was "not yet" or "not this one"
  UNANSWERED  warning  they offered and nobody from the project answered -- or their last word
                       was a question nobody answered; the silence may be the project's
  UNCHECKED   warning  an issue's timeline could not be read, so its claims were not judged

A claim is an English first-person sentence: "I'd like to work on this", "can I take this?",
"I'll submit a PR", "please assign it to me", "/assign", "take", "I'm working on it", "I'll look
into it". Quoted lines (`>`), code and HTML comments are not read. A negation just before the
claim ("I don't think I can take this"), or a turn after it ("... but I don't have the time"),
makes it not a claim. Bots are not read, nor accounts that relay other trackers ("-bot", "-ci").

Issues come from the REST API (`GITHUB_TOKEN` / `GH_TOKEN` are used if set; without one GitHub
allows 60 requests an hour, and every issue with comments costs one), or from `--from-json`, a
file in the shape `--dump` writes. `--as-of` judges the issues as they were on that day: later
events are ignored and an issue closed later counts as open.

Exit status: 0 = no errors, 1 = errors, 2 = something could not be read (a repository that
could not be listed, or an issue whose timeline could not be read -- a check that read nothing
must not print a pass). Standard library only. It reads; it never comments, assigns or labels.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

MEMBER = {"OWNER", "MEMBER", "COLLABORATOR"}
CLAIM_CODES = ("GONE", "QUIET", "UNANSWERED")

# ---------------------------------------------------------------------------------------------
# reading a comment

FENCE_RE = re.compile(r"(```|~~~).*?(\1|\Z)", re.S)
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
HTML_COMMENT_RE = re.compile(r"<!--.*?(-->|\Z)", re.S)
DETAILS_RE = re.compile(r"<details>.*?(</details>|\Z)", re.S | re.I)
MD_LINK_RE = re.compile(r"\[([^\]\n]*)\]\([^)\s]*\)")
URL_RE = re.compile(r"https?://\S+")
MENTION_RE = re.compile(r"(?<![\w/])@[A-Za-z0-9][A-Za-z0-9-]*(/[A-Za-z0-9._-]+)?")
ASSIGN_OTHER_RE = re.compile(r"(?im)^\s*/(?:assign|take|claim|cc)\s+@[A-Za-z0-9][\w-]*.*$")

I = r"\bi"
# what "I" says before the verb: "I'd like to", "can I", "let me", "I'm happy to" ...
MODAL = (r"(?:"
         r"\bi\s*(?:'|’)?\s*(?:ll|d)\b|\bi\s+(?:will|would|shall|can|could|may|might)\b|"
         r"\bi\s+(?:want|wish|plan|hope|intend|need)\s+to\b|\bi\s*(?:'|’)?\s*(?:m|am)\s+(?:going|planning|trying|able|about)\s+to\b|"
         r"\bi\s*(?:'|’)?\s*(?:m|am)\s+gonna\b|\bi\s*(?:'|’)?\s*(?:m|am)\s+(?:happy|glad|willing|keen|eager|ready|here)\s+to\b|"
         r"\b(?:can|could|may|shall)\s+i\b|\blet\s+me\b|\bi\s+(?:would|'d|’d)\s+(?:be\s+)?(?:happy|glad|love|like|willing)\s+to\b"
         r")")
FILLER = (r"(?:\s+(?:like|love|be\s+happy|be\s+glad|be\s+willing|also|please|still|really|now|first|then|try|to|start|"
          r"go\s+ahead\s+and|be\s+able|be|get|help|and|gladly|definitely|probably|happily|quickly|work\s+and|help\s+and|"
          r"try\s+and|investigate\s+and|make\s+the\s+changes?\s+and|begin|starting))*")
OBJ = (r"(?:this|it|that|this\s+(?:one|issue|bug|task|feature|ticket|item|problem|request|up)|"
       r"the\s+(?:issue|bug|task|fix|feature|ticket|change)|these|them)\b"
       # "take this opportunity", "take this into account", "look at it this way"
       r"(?!\s+(?:opportunity|chance|moment|occasion|into\s+account|for\s+granted|way|offline|further|to\s+the|with\s+a\s+grain|back\b))")
PR = r"(?:a|the|an|my)?\s*(?:pr|prs|pull\s+request|patch|fix|merge\s+request)\b"
VERB_OBJ = (r"(?:work(?:ing)?\s+on|take(?:\s+on)?|pick(?:ing)?\s+up|pick|grab|claim|tackle|fix|handle|implement|"
            r"address|resolve|solve|look\s+(?:into|at)|investigate|contribute\s+to|work\s+at|"
            r"take\s+a\s+(?:stab|crack|shot|look)\s+at|take\s+ownership\s+of|have\s+a\s+(?:try|go|stab|crack|shot|look)\s+(?:at|with))")
# the verb and what it is done to: "work on this", "take it", "give it a shot"
ACT = r"(?:" + VERB_OBJ + r"\s+(?:on\s+)?" + OBJ + r"|g[ai]ve\s+(?:it|this)\s+a\s+(?:try|shot|go)\b)"
VERB_PR = r"(?:submit|open|raise|create|send|make|put\s+up|file|push|prepare|do|work\s+on|propose)"
# the same with "I" left out: "Would love to take this up", "Happy to take this", ", will look into it"
BARE = (r"(?:^[^a-z]*(?:(?:hi|hello|hey|thanks|thank\s+you|ok|okay|sure|great|yes|cool|if\s+so|if\s+yes)\b[^a-z]*)?|,\s*|:\s*|\(\s*|\band\s+)"
        r"(?:(?:would|'d)\s+(?:(?:really|also|very)\s+)?(?:like|love|be\s+happy|be\s+glad|be\s+willing)\s+to|"
        r"(?:happy|glad|willing|keen|eager)\s+to|will|'ll)")
GREETING = r"(?:^(?:(?:hi|hello|hey|thanks|thank\s+you|ok|okay|sure|great|yes|cool)\b[^a-z]*)?)"

CLAIM_RES = [
    ("modal", re.compile(MODAL + FILLER + r"\s+" + ACT)),
    ("modal-pr", re.compile(MODAL + FILLER + r"\s+" + VERB_PR + r"\s+" + PR)),
    ("bare", re.compile(BARE + FILLER + r"\s+" + ACT)),
    ("bare-pr", re.compile(BARE + FILLER + r"\s+" + VERB_PR + r"\s+" + PR)),
    ("if-i", re.compile(r"\b(?:mind|okay|ok|alright|fine|possible|good)\s+if\s+i" + FILLER + r"\s+" + ACT)),
    ("started", re.compile(r"(?:" + GREETING + r"|\bi\s*(?:'ve|have)\s+|\bhave\s+)"
                           r"(?:already\s+)?(?:started\s+|begun\s+|been\s+)?working\s+on\s+(?:this|it)\b"
                           r"(?!\s+(?:would|will|is|requires?|needs?|might|may|could|should|means|seems|was))")),
    ("working", re.compile(I + r"\s*(?:'|’)?\s*(?:m|am|have\s+been|'ve\s+been|’ve\s+been)\s+(?:already\s+|currently\s+|now\s+|actively\s+)?"
                           r"(?:working\s+on|on|looking\s+into|taking\s+care\s+of)\s+" + OBJ)),
    ("on-it", re.compile(I + r"\s*(?:'|’)?\s*(?:m|am)\s+on\s+it\b")),
    ("assign-me", re.compile(r"\b(?:please\s+|pls\s+|kindly\s+|can\s+you\s+|could\s+you\s+|would\s+you\s+|you\s+can\s+)?"
                             r"assign\s+(?:(?:this|it|the)(?:\s+(?:issue|one|task|ticket|bug|feature|item))?)?\s*(?:to\s+)?me\b")),
    ("assigned-me", re.compile(r"\b(?:can|could|may)\s+i\s+(?:please\s+)?(?:get|be)\s+"
                               r"(?:this\s+|it\s+|this\s+issue\s+|this\s+one\s+|the\s+issue\s+)?assigned\b|"
                               r"\bhow\s+(?:can|could|do)\s+i\s+(?:get|be)\s+(?:this\s+|it\s+)?assigned\b|\bbe\s+assigned\s+to\s+me\b|"
                               r"\bi\s*(?:'d|would)\s+(?:like|love)\s+to\s+(?:get|be)\s+(?:this\s+|it\s+)?assigned\b|"
                               r"\b(?:get|have)\s+(?:this|it)\s+assigned\s+to\s+me\b|\bassign(?:ed)?\s+(?:this|it)\s+to\s+me\b")),
    ("command", re.compile(r"(?m)^\s*/(?:assign|take|claim|self-assign|work)(?:\s+me)?\s*$")),
    # pandas and others self-assign on a comment that says only "take"
    ("take", re.compile(r"^\s*take\s*[.!]?\s*$")),
    ("thinking", re.compile(I + r"\s*(?:'m|am)\s+(?:thinking\s+(?:of|about)|considering|planning\s+on|looking\s+at)\s+"
                            r"(?:taking(?:\s+on)?|working\s+on|picking\s+up|tackling|fixing|looking\s+into|implementing|"
                            r"taking\s+a\s+(?:look|stab|shot|crack)\s+at)\s+" + OBJ)),
    ("have-fix", re.compile(I + r"\s+(?:have|'ve\s+got|got)\s+(?:a\s+)?(?:possible\s+|potential\s+|local\s+|working\s+|draft\s+|quick\s+|simple\s+)?"
                            r"(?:fix|patch|pr|implementation)\b(?!\s+for\s+(?:a\s+|an\s+)?(?:different|another|similar|other))")),
    ("interested", re.compile(I + r"\s*(?:'|’)?\s*(?:m|am|would\s+be|'d\s+be|’d\s+be)\s+(?:very\s+|really\s+|also\s+)?"
                              r"interested\s+in\s+(?:working\s+on|taking|picking\s+up|tackling|contributing\s+to|fixing|implementing)\s+" + OBJ)),
]

# a negation just before the claim ("I don't think I can take this", "not sure I'd work on it")
NEGATION_RE = re.compile(
    r"\b(?:not|no\s+longer|never|unable|cannot|can't|cant|won't|wont|don't|dont|doesn't|"
    r"wouldn't|couldn't|haven't|busy|unfortunately|unlikely|doubt)\b")
# conditions that contain a negation but not a refusal: "if not, I'll take it"
CONDITION_RE = re.compile(r"\b(?:if|unless|when|otherwise)\s+(?:not|no\s*one|nobody|none|there(?:'s|\s+is)\s+no)\b[^,]*,?"
                          r"|\bnot\s+sure\b|\bif\s+(?:it(?:'s|\s+is)|this\s+is)\s+not\b[^,]*,?")
# "..., but I don't have the time" / "..., though feel free to take it" -- a claim taken back in the same sentence
TURN_RE = re.compile(r"\b(?:but|though|although|however|unfortunately|sadly)\b")
NEGATION_I_RE = re.compile(r"^\W*(?:i\s+(?:don't|do\s+not|can't|cannot|won't|will\s+not|am\s+not|'m\s+not|may\s+not)|"
                           r"i'm\s+not|(?:no|not\s+enough)\s+time)\b")
RELEASE_RE = re.compile(
    r"\b(?:no\s+longer|not\s+(?:able|going)\s+to|unable\s+to|can(?:'|’)?t\s+(?:work|continue|finish|get\s+to|find\s+the\s+time)|cannot\s+(?:work|continue|finish)|"
    r"won(?:'|’)?t\s+(?:be\s+able|have\s+(?:the\s+)?time)|(?:don(?:'|’)?t|do\s+not)\s+have\s+(?:the\s+|enough\s+)?(?:time|bandwidth|capacity)|"
    r"unassign\s+me|un-assign\s+me|remove\s+me|free\s+to\s+(?:take|pick|grab|work|assign)|feel\s+free|up\s+for\s+grabs|"
    r"(?:someone|somebody|anyone|anybody)\s+else|step(?:ping)?\s+(?:back|down|away|aside)|drop(?:ping)?\s+(?:this|it|out)|"
    r"giv(?:e|ing)\s+(?:up|this\s+up|it\s+up)|releas(?:e|ing)\s+(?:this|it|the\s+issue|my\s+claim)|"
    r"(?:got|been|was|am|i(?:'|’)m)\s+(?:re)?assigned\s+to\s+(?:a\s+)?(?:different|another|other))\b")


def clean(body):
    t = body or ""
    t = HTML_COMMENT_RE.sub(" ", t)
    t = DETAILS_RE.sub(" ", t)
    t = FENCE_RE.sub(" ", t)
    t = INLINE_CODE_RE.sub(" ", t)
    t = "\n".join(l for l in t.splitlines() if not l.lstrip().startswith(">"))
    t = MD_LINK_RE.sub(r"\1", t)
    t = URL_RE.sub(" ", t)
    # "/assign @someone" is a maintainer assigning someone else, not claiming it (milvus-io/milvus#27468)
    t = ASSIGN_OTHER_RE.sub(" ", t)
    t = MENTION_RE.sub(" ", t)
    t = t.replace("’", "'").replace("‘", "'")
    t = re.sub(r"[*~]+|(?<!\w)_+|_+(?!\w)", "", t)  # **bold**, _italic_, ~~struck~~
    return t.lower()


def sentences(text):
    # "/assign" on its own line is a sentence; so is every line and every ./!/? stop
    for part in re.split(r"(?<=[.!?;])\s+|\n+", text):
        if part.strip():
            yield part.strip()


def claim_in(body):
    """The first sentence of `body` that claims the issue, with the rule that matched, or None.
    A sentence is not a claim when a negation stands in the 40 characters before the match
    ("I don't think I can take this"), or when it lets the issue go after the match
    ("I'd like to work on this but I don't have the time")."""
    for s in sentences(clean(body)):
        for name, rx in CLAIM_RES:
            m = rx.search(s)
            if not m:
                continue
            before = CONDITION_RE.sub(" ", s[max(0, m.start() - 40):m.start()])
            after = s[m.end():]
            turn = TURN_RE.search(after)
            if NEGATION_RE.search(before) or (turn and (RELEASE_RE.search(after, turn.end()) or
                                                        NEGATION_I_RE.search(after[turn.end():]))):
                break
            return name, s[:160]
    return None


# accounts that relay other people's words: "jenkins-infra-bot" re-posts Jira comments, "swift-ci"
# re-posts bugs.swift.org -- the claim in them is somebody else's, years ago
RELAY_LOGIN_RE = re.compile(r"[-_](?:bot|ci|importer?|sync)$", re.I)
RELAYED_RE = re.compile(r"jira_(?:issue_key|comment_id)=|\bimported\s+from\s+(?:jira|bugzilla|trac|gitlab)|"
                        r"\*\*originally\s+posted\s+by\b", re.I)


def is_bot(e):
    who = e.get("who") or ""
    return bool(e.get("bot") or not who or who.endswith("[bot]") or RELAY_LOGIN_RE.search(who)
                or RELAYED_RE.search(e.get("body") or ""))


def release_in(body):
    s = clean(body)
    m = RELEASE_RE.search(s)
    return m.group(0) if m else None


# ---------------------------------------------------------------------------------------------
# judging an issue


def parse_time(s):
    return datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)


class Finding:
    def __init__(self, issue, severity, code, who, claim_at, said, last_at, days, message, extra):
        self.repo = issue.get("repo")
        self.number = issue.get("number")
        self.url = issue.get("url")
        self.title = issue.get("title")
        self.severity, self.code, self.who = severity, code, who
        self.claim_at, self.said, self.last_at, self.days = claim_at, said, last_at, days
        self.message, self.extra = message, extra

    def as_dict(self):
        d = {k: getattr(self, k) for k in ("repo", "number", "url", "title", "severity", "code", "who",
                                            "said", "days", "message")}
        d["claim_at"] = self.claim_at.strftime("%Y-%m-%d") if self.claim_at else None
        d["last_at"] = self.last_at.strftime("%Y-%m-%d") if self.last_at else None
        d.update(self.extra)
        return d

    def __str__(self):
        return "%s#%s: %s %s %s" % (self.repo, self.number, self.severity, self.code, self.message)


def state_at(issue, events, as_of):
    """Open or closed at `as_of` (None = now)."""
    if as_of is None:
        return issue.get("state", "open")
    st = "open"
    for e in events:
        if e["type"] == "closed":
            st = "closed"
        elif e["type"] == "reopened":
            st = "open"
    if st == "open" and issue.get("state") == "closed" and issue.get("closed_at") and \
            not any(e["type"] in ("closed", "reopened") for e in issue.get("events", [])):
        # no events were read at all: fall back to the issue's own closed_at
        st = "closed" if parse_time(issue["closed_at"]) <= as_of else "open"
    return st


def judge(issue, now, days=30, as_of=None):
    """Findings for one issue (normalised shape; see --dump). `now` is the day it is judged on."""
    created = issue.get("created_at")
    if as_of is not None and created and parse_time(created) > as_of:
        return []
    events = list(issue.get("events", []))
    # pull requests that say "fixes #N" -- GraphQL's closedByPullRequestsReferences. A token that
    # cannot see the timeline's cross-references can still see these (see `closing_prs`)
    for pr in issue.get("closed_by", []):
        events.append({"type": "xref", "at": pr.get("at"), "who": pr.get("who"), "is_pr": True, "same_repo": True,
                       "number": pr.get("number")})
    events = sorted((e for e in events if e.get("at")), key=lambda e: e["at"])
    if as_of is not None:
        events = [e for e in events if parse_time(e["at"]) <= as_of]
    if state_at(issue, events, as_of) != "open":
        return []

    # who is assigned, as the events have it (the current list is used only when judging today
    # and the events say nothing, e.g. an issue opened already assigned)
    assigned = set()
    for e in events:
        if e["type"] == "assigned" and e.get("who"):
            assigned.add(e["who"].lower())
        elif e["type"] == "unassigned" and e.get("who"):
            assigned.discard(e["who"].lower())
    if as_of is None and not any(e["type"] in ("assigned", "unassigned") for e in events):
        assigned = {a.lower() for a in issue.get("assignees", []) if a}

    # Walk the timeline once. A claim opens an "episode" for its author; the episode ends when
    # they deliver (a pull request), let it go (a release comment), or the project moves on
    # (they are unassigned, someone else is assigned, someone else's pull request mentions it).
    # A later claim by the same person opens a new episode. What is still open at the end, and
    # silent for `days`, is reported.
    open_eps = {}  # login -> episode
    holding = set()  # who is assigned at this point of the walk
    for e in events:
        who = (e.get("who") or "").lower()
        t = e["type"]
        if t == "comment" and not is_bot(e):
            ep = open_eps.get(who)
            if ep is not None:
                if release_in(e.get("body", "")) and not claim_in(e.get("body", "")):
                    del open_eps[who]
                else:
                    ep["last"] = e["at"]
                    ep["asked"] = "?" in clean(e.get("body", ""))
                    ep["members_after_last"] = 0
            else:
                c = claim_in(e.get("body", ""))
                if c:
                    open_eps[who] = {"who": e["who"], "start": e, "rule": c[0], "said": c[1],
                                     "assoc": e.get("assoc"), "last": e["at"], "members": 0, "assigned": False,
                                     "others": {}, "held_by": holding - {who},
                                     "asked": "?" in clean(e.get("body", "")), "members_after_last": 0}
            if t == "comment" and who:
                c2 = None
                for k, ep in open_eps.items():
                    if k == who or ep["start"] is e:
                        continue
                    if e.get("assoc") in MEMBER:
                        ep["members"] += 1
                        ep["members_after_last"] += 1
                    if e["at"] > ep["last"]:
                        if c2 is None:
                            c2 = bool(claim_in(e.get("body", "")))
                        if c2:
                            ep["others"][who] = e["at"]
        elif t == "xref" and e.get("is_pr"):
            if who in open_eps:
                del open_eps[who]  # delivered
            if e.get("same_repo", True) and who:
                for k in [k for k in open_eps if k != who]:
                    del open_eps[k]  # someone else's pull request
        elif t in ("commit", "xref"):
            if who in open_eps:
                open_eps[who]["last"] = e["at"]
        elif t == "assigned" and who:
            holding.add(who)
            for k in [k for k in open_eps if k != who]:
                del open_eps[k]
            if who in open_eps:
                open_eps[who]["assigned"] = True
                open_eps[who]["members_after_last"] += 1  # being assigned answers "can I take this?"
        elif t == "unassigned" and who:
            holding.discard(who)
            if who in open_eps:
                del open_eps[who]

    out = []
    for k, ep in open_eps.items():
        last_t = parse_time(ep["last"])
        silent = (now - last_t).days
        if silent < days:
            continue
        if ep["held_by"] and ep["held_by"] & assigned and k not in assigned:
            continue  # they asked for an issue someone else holds, and that person still does
        is_member = ep["assoc"] in MEMBER
        still_assigned = k in assigned
        # their last word was a question nobody from the project answered: the silence is not theirs
        waiting = ep["asked"] and not ep["members_after_last"]
        if still_assigned and not waiting:
            code, sev = "GONE", "error"
        elif (is_member or ep["members"]) and not waiting:
            code, sev = "QUIET", "warning"
        else:
            code, sev = "UNANSWERED", "warning"
        bits = []
        if still_assigned:
            bits.append("still assigned to them")
        elif is_member:
            bits.append("they are a %s" % ep["assoc"].lower())
        elif ep["members"] and not waiting:
            bits.append("a maintainer answered, nobody assigned it")
        if waiting:
            bits.append("their last comment asked something nobody from the project answered")
        elif not (still_assigned or is_member or ep["members"]):
            bits.append("nobody from the project answered")
        # those who asked after the claimant's last word (a claim before it was answered by it)
        n_others = sum(1 for at in ep["others"].values() if at > ep["last"])
        if n_others:
            bits.append("%d other%s asked to take it since" % (n_others, "" if n_others == 1 else "s"))
        start_at = ep["start"]["at"]
        msg = '@%s: "%s" (%s) -- nothing from them in %d days; %s' % (
            ep["who"], ep["said"], start_at[:10], silent, "; ".join(bits))
        out.append(Finding(issue, sev, code, ep["who"], parse_time(start_at), ep["said"], last_t, silent, msg,
                           {"rule": ep["rule"], "assoc": ep["assoc"], "still_assigned": still_assigned,
                            "others_since": n_others, "comment_url": ep["start"].get("url")}))
    return out


def run(issues, now, days=30, as_of=None):
    findings = []
    for it in issues:
        if it.get("unreadable"):
            findings.append(Finding(it, "warning", "UNCHECKED", None, None, None, None, None,
                                    "the timeline could not be read (%s); its claims were not judged" % it["unreadable"], {}))
            continue
        findings.extend(judge(it, now, days, as_of))
    findings.sort(key=lambda f: (f.severity != "error", -(f.days or 0), f.repo or "", f.number or 0))
    return findings


def mentions(text, number):
    return re.search(r"(?<![\w/])#%d\b|/issues/%d\b" % (number, number), text or "") is not None


def confirm(findings, search, search_mentions=None, log=None):
    """Check each finding against pull requests the timeline may not show.

    `search_mentions(repo, number, since)` returns the pull requests in the repository, opened on
    or after `since`, whose text contains the issue number; `search(repo, login, since)` those the
    claimant opened. Each returns a list of {"number", "title", "body", "who"}, or None when it could
    not search. A pull request that names the issue (`#N` or its URL) drops the finding: the
    claimant's own means they delivered, anyone else's means the work moved on -- the same two rules
    the timeline walk applies to cross-references, which a token can hide. Returns (kept, dropped).
    A finding whose searches failed is kept and says so."""
    kept, dropped = [], []
    by_issue = {}
    earliest = {}
    for f in findings:
        if f.code in CLAIM_CODES:
            k = (f.repo, f.number)
            earliest[k] = min(earliest.get(k, f.claim_at), f.claim_at)
    for n, f in enumerate(findings, 1):
        if f.code not in CLAIM_CODES:
            kept.append(f)
            continue
        since = f.claim_at.strftime("%Y-%m-%d")
        named = []
        failed = False
        if search_mentions is not None:
            key = (f.repo, f.number)
            if key not in by_issue:  # one search per issue, from its earliest claim
                by_issue[key] = search_mentions(f.repo, f.number, earliest[key].strftime("%Y-%m-%d"))
            got = by_issue[key]
            if got is None:
                failed = True
            else:
                named = [p for p in got if (p.get("at") or "9")[:10] >= since
                         and mentions((p.get("title") or "") + "\n" + (p.get("body") or ""), f.number)]
        prs = search(f.repo, f.who, since)
        if prs is None:
            failed = True
            prs = []
        named += [p for p in prs if mentions((p.get("title") or "") + "\n" + (p.get("body") or ""), f.number)]
        if named:
            mine = [p for p in named if (p.get("who") or f.who).lower() == f.who.lower()]
            f.extra["delivered_in" if mine else "moved_on_in"] = (mine or named)[0].get("number")
            dropped.append(f)
            continue
        f.extra["searched"] = not failed
        if failed:
            f.message += "; (pull requests could not be searched)"
        f.extra["prs_since"] = len(prs)
        if prs:
            f.message += "; %d other pull request%s from them here since" % (len(prs), "" if len(prs) == 1 else "s")
        kept.append(f)
        if log and n % 50 == 0:
            print("  searched %d of %d claimants" % (n, len(findings)), file=log)
    return kept, dropped


# ---------------------------------------------------------------------------------------------
# reading GitHub


class GitHub:
    API = "https://api.github.com"

    def __init__(self):
        self.token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
        self.calls = 0

    def get(self, path):
        """(json, next_url). Raises urllib.error.HTTPError / URLError."""
        url = path if path.startswith("http") else self.API + path
        req = urllib.request.Request(url)
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
        req.add_header("User-Agent", "claim-check")
        if self.token:
            req.add_header("Authorization", "Bearer " + self.token)
        self.calls += 1
        with urllib.request.urlopen(req, timeout=30) as r:
            nxt = None
            for part in (r.headers.get("Link") or "").split(","):
                m = re.search(r'<([^>]+)>;\s*rel="next"', part)
                if m:
                    nxt = m.group(1)
            return json.loads(r.read().decode("utf-8")), nxt

    def pages(self, path):
        url = path
        while url:
            data, url = self.get(url)
            yield data

    def graphql(self, query):
        req = urllib.request.Request(self.API + "/graphql", data=json.dumps({"query": query}).encode("utf-8"),
                                     method="POST")
        req.add_header("Authorization", "Bearer " + self.token)
        req.add_header("User-Agent", "claim-check")
        req.add_header("Content-Type", "application/json")
        self.calls += 1
        with urllib.request.urlopen(req, timeout=60) as r:
            j = json.loads(r.read().decode("utf-8"))
        if j.get("errors") and not j.get("data"):
            raise ValueError(str(j["errors"])[:200])
        return j["data"]

    def closing_prs(self, repo, numbers):
        """{issue number: [{"number", "who", "at", "state"}]} -- the pull requests that say they close
        it, open or not. GraphQL only, so a token is needed."""
        owner, name = repo.split("/", 1)
        out = {}
        for i in range(0, len(numbers), 40):
            chunk = numbers[i:i + 40]
            body = " ".join("i%d: issue(number: %d) { closedByPullRequestsReferences(first: 20, includeClosedPrs: true) "
                            "{ nodes { number createdAt state author { login } } } }" % (n, n) for n in chunk)
            d = self.graphql("query { repository(owner: %s, name: %s) { %s } }"
                             % (json.dumps(owner), json.dumps(name), body))["repository"] or {}
            for n in chunk:
                x = d.get("i%d" % n) or {}
                out[n] = [{"number": p["number"], "at": p["createdAt"], "state": p["state"],
                           "who": (p.get("author") or {}).get("login")}
                          for p in (x.get("closedByPullRequestsReferences") or {}).get("nodes", [])]
        return out

    def search_prs(self, repo, author, since):
        """The pull requests `author` opened in `repo` on or after `since`, or None if the search failed.
        Waits out the search rate limit (30 a minute with a token, 10 without) up to three times."""
        return self._search_prs("repo:%s is:pr author:%s created:>=%s" % (repo, author, since))

    def search_mentions(self, repo, number, since):
        """The pull requests in `repo`, opened on or after `since`, whose text contains `number`."""
        return self._search_prs("repo:%s is:pr %d created:>=%s" % (repo, number, since))

    def _search_prs(self, q):
        url = "/search/issues?" + urllib.parse.urlencode({"q": q, "per_page": "100"})
        for attempt in range(4):
            try:
                data, _ = self.get(url)
                return [{"number": i.get("number"), "title": i.get("title"), "body": i.get("body"),
                         "who": _login(i.get("user")), "at": i.get("created_at")} for i in data.get("items", [])]
            except urllib.error.HTTPError as e:
                if e.code == 422:  # the user is gone (deleted, renamed): nothing of theirs to find
                    return []
                if e.code in (403, 429) and attempt < 3:
                    reset = e.headers.get("X-RateLimit-Reset") if e.headers else None
                    wait = 61
                    if reset and reset.isdigit():
                        wait = max(1, min(61, int(reset) - int(time.time()) + 1))
                    time.sleep(wait)
                    continue
                return None
            except (urllib.error.URLError, ValueError):
                return None
        return None

    def issues(self, repo, labels=(), max_issues=None, progress=None):
        q = {"state": "open", "per_page": "100"}
        if labels:
            q["labels"] = ",".join(labels)
        out = []
        for page in self.pages("/repos/%s/issues?%s" % (repo, urllib.parse.urlencode(q))):
            for it in page:
                if "pull_request" in it:
                    continue
                out.append(it)
                if max_issues and len(out) >= max_issues:
                    return out
        return out

    def timeline(self, repo, number):
        ev = []
        for page in self.pages("/repos/%s/issues/%d/timeline?per_page=100" % (repo, number)):
            ev.extend(page)
        return ev


def _login(u):
    return (u or {}).get("login")


def _bot(u):
    return bool(u) and (u.get("type") == "Bot" or (u.get("login") or "").endswith("[bot]"))


def normalise_rest(repo, it, timeline):
    """The REST issue and its timeline in the shape `judge` reads."""
    ev = []
    for t in timeline:
        k = t.get("event")
        at = t.get("created_at")
        if k == "commented":
            u = t.get("user") or t.get("actor")
            ev.append({"type": "comment", "at": at, "who": _login(u), "bot": _bot(u),
                       "assoc": t.get("author_association"), "body": t.get("body") or "", "url": t.get("html_url")})
        elif k == "cross-referenced":
            s = (t.get("source") or {}).get("issue") or {}
            src_repo = ((s.get("repository") or {}).get("full_name") or "")
            ev.append({"type": "xref", "at": at, "who": _login(s.get("user")) or _login(t.get("actor")),
                       "is_pr": "pull_request" in s, "state": s.get("state"), "url": s.get("html_url"),
                       "same_repo": (src_repo.lower() == repo.lower()) if src_repo else True})
        elif k == "referenced":
            ev.append({"type": "commit", "at": at, "who": _login(t.get("actor"))})
        elif k in ("assigned", "unassigned"):
            ev.append({"type": k, "at": at, "who": _login(t.get("assignee")), "by": _login(t.get("actor"))})
        elif k == "closed":
            ev.append({"type": "closed", "at": at, "who": _login(t.get("actor"))})
        elif k == "reopened":
            ev.append({"type": "reopened", "at": at, "who": _login(t.get("actor"))})
    return {"repo": repo, "number": it["number"], "url": it.get("html_url"), "title": it.get("title"),
            "state": it.get("state", "open"), "created_at": it.get("created_at"), "closed_at": it.get("closed_at"),
            "author": _login(it.get("user")), "labels": [l.get("name") for l in it.get("labels", [])],
            "assignees": [_login(a) for a in it.get("assignees", []) if a], "events": ev}


def fetch(repo, labels=(), max_issues=None, gh=None, log=sys.stderr):
    gh = gh or GitHub()
    listed = gh.issues(repo, labels, max_issues)
    out = []
    for n, it in enumerate(listed, 1):
        if not it.get("comments"):
            out.append(normalise_rest(repo, it, []))
            continue
        try:
            out.append(normalise_rest(repo, it, gh.timeline(repo, it["number"])))
        except (urllib.error.URLError, ValueError) as e:
            d = normalise_rest(repo, it, [])
            d["unreadable"] = getattr(e, "code", None) and "HTTP %s" % e.code or str(e)[:80]
            out.append(d)
        if log and n % 100 == 0:
            print("  read %d of %d issues" % (n, len(listed)), file=log)
    want = [d["number"] for d in out if not d.get("unreadable") and d["events"]]
    if gh.token and want:
        # A fine-grained token that is not granted the repository reads its timelines without a
        # single cross-reference (measured 2026-09-24: apache/airflow#9186 shows two anonymously and
        # none with such a token). The pull requests that say "fixes #N" are still readable.
        try:
            refs = gh.closing_prs(repo, want)
            for d in out:
                if d["number"] in refs:
                    d["closed_by"] = refs[d["number"]]
            n_closing = sum(1 for d in out if d.get("closed_by"))
            n_xref = sum(1 for d in out for e in d["events"] if e["type"] == "xref")
            if log and n_closing and not n_xref:
                print("claim-check: %d issues have pull requests that close them, and their timelines show not one "
                      "cross-reference -- this token cannot see them. Pull requests are known only from those "
                      "closing links and from searches; run without a token, or with one granted this repository, "
                      "to read the timeline whole" % n_closing, file=log)
        except (urllib.error.URLError, ValueError, KeyError) as e:
            if log:
                print("claim-check: the closing pull requests could not be read (%s); pull requests are known "
                      "only from the timeline" % str(e)[:80], file=log)
    return out


# ---------------------------------------------------------------------------------------------


def main(argv=None):
    ap = argparse.ArgumentParser(description="Find claims on open GitHub issues whose author went quiet.")
    ap.add_argument("repo", nargs="?", help="OWNER/NAME")
    ap.add_argument("--days", type=int, default=30, help="days of silence before a claim is reported (default 30)")
    ap.add_argument("--label", action="append", default=[], help="only issues with this label (repeatable: all of them)")
    ap.add_argument("--as-of", help="judge the issues as they were on this day (YYYY-MM-DD)")
    ap.add_argument("--from-json", help="read issues from this file instead of GitHub")
    ap.add_argument("--dump", help="also write the issues read from GitHub to this file")
    ap.add_argument("--max-issues", type=int, help="read at most this many open issues")
    ap.add_argument("--json", action="store_true", help="print findings as JSON")
    ap.add_argument("--no-search", action="store_true",
                    help="do not search each claimant's pull requests (on by default when reading from GitHub)")
    ap.add_argument("--search", action="store_true", help="search them also with --from-json")
    a = ap.parse_args(argv)
    if not a.repo and not a.from_json:
        ap.error("give OWNER/NAME or --from-json FILE")
    as_of = None
    if a.as_of:
        as_of = datetime.strptime(a.as_of, "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(days=1) - timedelta(seconds=1)
    now = as_of or datetime.now(timezone.utc)
    if a.from_json:
        with open(a.from_json, encoding="utf-8") as f:
            data = json.load(f)
        issues = data["items"] if isinstance(data, dict) else data
        if a.label:
            want = {l.lower() for l in a.label}
            issues = [i for i in issues if want <= {l.lower() for l in i.get("labels", [])}]
    else:
        gh = GitHub()
        if not gh.token:
            print("claim-check: no GITHUB_TOKEN / GH_TOKEN -- GitHub allows 60 requests an hour without one, "
                  "one per issue with comments", file=sys.stderr)
        try:
            issues = fetch(a.repo, a.label, a.max_issues, gh)
        except (urllib.error.URLError, ValueError) as e:
            print("claim-check: could not list the open issues of %s (%s) -- nothing was checked"
                  % (a.repo, getattr(e, "code", e)), file=sys.stderr)
            return 2
        if a.dump:
            with open(a.dump, "w", encoding="utf-8") as f:
                json.dump({"repo": a.repo, "items": issues}, f, ensure_ascii=False)
    findings = run(issues, now, a.days, as_of)
    dropped = []
    if (not a.from_json or a.search) and not a.no_search:
        gh = GitHub()
        findings, dropped = confirm(findings, gh.search_prs, gh.search_mentions, sys.stderr)
    if a.json:
        print(json.dumps([f.as_dict() for f in findings], ensure_ascii=False, indent=1))
    else:
        for f in findings:
            print(f)
        n_err = sum(f.severity == "error" for f in findings)
        n_quiet = sum(f.code == "QUIET" for f in findings)
        n_warn = sum(f.code == "UNANSWERED" for f in findings)
        n_unc = sum(f.code == "UNCHECKED" for f in findings)
        print("%d open issues read; %d GONE, %d QUIET, %d UNANSWERED%s (silent %d+ days%s)%s" % (
            len(issues), n_err, n_quiet, n_warn, ", %d UNCHECKED" % n_unc if n_unc else "", a.days,
            ", as of %s" % a.as_of if a.as_of else "",
            "; %d more left out: a pull request names the issue" % len(dropped) if dropped else ""),
            file=sys.stderr)
    if any(f.code == "UNCHECKED" for f in findings):
        return 2
    return 1 if any(f.severity == "error" for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
