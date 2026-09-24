# -*- coding: utf-8 -*-
"""Tests for label_link_check.py.  python test_label_link_check.py"""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import label_link_check as L  # noqa: E402

OWN = ["bug", "enhancement", "good first issue", "help wanted", "type: bug", "Docs", "needs triage",
       "area/cli"]


class FakeSource:
    def __init__(self, repos=None, templates=None):
        self.repos = {k.lower(): v for k, v in (repos or {}).items()}
        self.tpl = {k.lower(): v for k, v in (templates or {}).items()}
        self.calls = []

    def labels(self, repo):
        self.calls.append(repo)
        return self.repos.get(repo.lower())

    def exists(self, repo):
        return repo.lower() in self.repos

    def templates(self, repo):
        return self.tpl.get(repo.lower())


def res(own=OWN, source=None, templates=None, repo="acme/app"):
    return L.Resolver(repo, own, templates, source or FakeSource())


def codes(text, r=None, rel="README.md", tpl=False, repo="acme/app"):
    out = []
    L.scan_text(rel, text, repo, r or res(), out, tpl)
    return [(f.code, f.subject) for f in out]


def one(text, **kw):
    out = []
    L.scan_text("README.md", text, "acme/app", res(**kw), out, False)
    return out


class Links(unittest.TestCase):
    def test_label_path_missing(self):
        self.assertEqual(codes("see https://github.com/acme/app/labels/good-first-issue"),
                         [("LABEL", "good-first-issue")])

    def test_label_path_present_encoded(self):
        self.assertEqual(codes("https://github.com/acme/app/labels/good%20first%20issue"), [])

    def test_label_path_suggestion(self):
        f = one("https://github.com/acme/app/labels/good-first-issue")[0]
        self.assertEqual(f.suggest, '"good first issue"')
        self.assertEqual(f.severity, "error")

    def test_label_path_case_is_warning(self):
        f = one("https://github.com/acme/app/labels/Good%20First%20Issue")
        self.assertEqual([(x.code, x.severity) for x in f], [("CASE", "warning")])

    def test_label_path_plus(self):
        f = one("[x](https://github.com/acme/app/labels/help+wanted)")
        self.assertEqual([(x.code, x.severity) for x in f], [("PLUS_PATH", "warning")])

    def test_label_path_colon_encoded(self):
        self.assertEqual(codes("https://github.com/acme/app/labels/type%3A%20bug"), [])

    def test_markdown_target_with_quotes(self):
        # starship/starship README before a675122f
        f = one('try a [good first issue](https://github.com/acme/app/labels/"good%20first%20issue").')
        self.assertEqual([(x.code, x.subject) for x in f], [("QUOTED_PATH", '"good first issue"')])
        self.assertEqual(f[0].suggest, "labels/good%20first%20issue")

    def test_quoted_path_encoded(self):
        # vercel/next.js 7dad4ac2 (#80478) turned a working link into this
        self.assertEqual(codes("**[good first issues](https://github.com/acme/app/labels/%22good%20first%20issue%22)**"),
                         [("QUOTED_PATH", '"good first issue"')])

    def test_markdown_target_title(self):
        self.assertEqual(codes('[x](https://github.com/acme/app/labels/nope "Nope issues")'), [("LABEL", "nope")])

    def test_or_list_one_missing_is_warning(self):
        f = one('https://github.com/search?q=repo%3Aacme%2Fapp+label%3A%22good-first-issue%22%2C%22good+first+issue%22&type=issues')
        self.assertEqual([(x.code, x.severity) for x in f], [("OR_LABEL", "warning")])

    def test_or_list_all_missing_is_error(self):
        self.assertEqual(codes("https://github.com/acme/app/issues?q=label%3Anope1%2Cnope2"),
                         [("LABEL", "nope1"), ("LABEL", "nope2")])

    def test_title_qualifier_known(self):
        self.assertEqual(codes('https://github.com/acme/app/pulls?q=is%3Apr+title%3A%22%5Bpip%5D%22'), [])

    def test_template_renamed_with_prefix(self):
        r = res(templates=["1-bug.yml", "2-found-a-bug.yml", "config.yml"])
        out = []
        L.scan_text("R.md", "https://github.com/acme/app/issues/new?template=found-a-bug.yml", "acme/app", r, out)
        self.assertEqual([(f.code, f.suggest) for f in out], [("TEMPLATE", "2-found-a-bug.yml")])

    def test_template_from_owner_dot_github(self):
        class S(FakeSource):
            def org_templates(self, owner):
                return ["bug_report.md"] if owner == "acme" else []
        r = L.Resolver("acme/app", OWN, [], S())
        out = []
        L.scan_text("R.md", "https://github.com/acme/app/issues/new?template=bug_report.md", "acme/app", r, out)
        self.assertEqual(out, [])
        L.scan_text("R.md", "https://github.com/acme/app/issues/new?template=nope.md", "acme/app", r, out)
        self.assertEqual([f.code for f in out], ["TEMPLATE"])

    def test_own_template_folder_wins_over_owner(self):
        class S(FakeSource):
            def org_templates(self, owner):
                return ["bug_report.md"]
        r = L.Resolver("acme/app", OWN, ["other.yml"], S())
        out = []
        L.scan_text("R.md", "https://github.com/acme/app/issues/new?template=bug_report.md", "acme/app", r, out)
        self.assertEqual([f.code for f in out], ["TEMPLATE"])

    def test_query_label_missing(self):
        self.assertEqual(codes("https://github.com/acme/app/issues?q=is%3Aopen+label%3Agood-first-issue"),
                         [("LABEL", "good-first-issue")])

    def test_query_quoted_ok(self):
        self.assertEqual(codes('https://github.com/acme/app/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22'), [])

    def test_query_unquoted_multiword(self):
        f = one("https://github.com/acme/app/issues?q=is:open+label:good+first+issue")
        self.assertEqual([(x.code, x.subject) for x in f], [("UNQUOTED", "good first issue")])
        self.assertEqual(f[0].suggest, 'label:"good first issue"')

    def test_query_unquoted_single_word_label_is_fine(self):
        # label:bug followed by text: bug exists, the text is a text search -- not ours to judge
        self.assertEqual(codes("https://github.com/acme/app/issues?q=label:bug+crash"), [])

    def test_query_or_values(self):
        self.assertEqual(codes('https://github.com/acme/app/issues?q=label%3Abug%2C%22help+wanted%22%2Cnope'),
                         [("OR_LABEL", "nope")])

    def test_query_negated_missing_is_warning(self):
        f = one("https://github.com/acme/app/issues?q=is:open+-label:wontfix")
        self.assertEqual([(x.code, x.severity) for x in f], [("NEG_LABEL", "warning")])

    def test_query_unknown_qualifier(self):
        f = one("https://github.com/acme/app/issues?q=lable%3Abug")
        self.assertEqual([(x.code, x.severity) for x in f], [("QUALIFIER", "warning")])

    def test_query_is_value(self):
        self.assertEqual(codes("https://github.com/acme/app/issues?q=is%3Aopened+label%3Abug"),
                         [("IS_VALUE", "is:opened")])

    def test_query_state_value(self):
        self.assertEqual(codes("https://github.com/acme/app/pulls?q=state%3Aall"), [("IS_VALUE", "state:all")])

    def test_query_parens(self):
        self.assertEqual(codes("https://github.com/acme/app/issues?q=(label%3Anope1+OR+label%3Anope2)"),
                         [("LABEL", "nope1"), ("LABEL", "nope2")])

    def test_query_colon_label_quoted(self):
        self.assertEqual(codes('https://github.com/acme/app/issues?q=label%3A%22type%3A+bug%22'), [])

    def test_labels_param(self):
        self.assertEqual(codes("https://github.com/acme/app/issues?labels=bug,nope"), [("LABEL", "nope")])

    def test_new_issue_labels_and_template(self):
        r = res(templates=["bug_report.yml", "feature.md"])
        self.assertEqual(codes("https://github.com/acme/app/issues/new?labels=bug&template=bug_report.md", r),
                         [("TEMPLATE", "bug_report.md")])

    def test_new_issue_template_present(self):
        r = res(templates=["bug_report.yml"])
        self.assertEqual(codes("https://github.com/acme/app/issues/new?template=bug_report.yml", r), [])

    def test_blank_issue_template(self):
        r = res(templates=["bug_report.yml"])
        self.assertEqual(codes("https://github.com/acme/app/issues/new?template=BLANK_ISSUE", r), [])

    def test_template_suggestion_by_stem(self):
        r = res(templates=["bug_report.yml"])
        out = []
        L.scan_text("R.md", "https://github.com/acme/app/issues/new?template=bug_report.md", "acme/app", r, out)
        self.assertEqual(out[0].suggest, "bug_report.yml")

    def test_html_entity(self):
        self.assertEqual(codes('<a href="https://github.com/acme/app/issues?q=is%3Aopen&amp;labels=nope">'),
                         [("LABEL", "nope")])

    def test_asciidoc_link(self):
        self.assertEqual(codes("https://github.com/acme/app/labels/help-wanted[help-wanted]"),
                         [("LABEL", "help-wanted")])

    def test_trailing_punctuation(self):
        self.assertEqual(codes("go to https://github.com/acme/app/labels/bug."), [])

    def test_other_repo(self):
        src = FakeSource({"other/lib": ["good first issue"]})
        self.assertEqual(codes("https://github.com/other/lib/labels/good%20first%20issues", res(source=src)),
                         [("LABEL", "good first issues")])

    def test_other_repo_missing(self):
        src = FakeSource({})
        self.assertEqual(codes("https://github.com/gone/repo/labels/bug", res(source=src)), [("NO_REPO", "gone/repo")])

    def test_other_repo_unreadable(self):
        class S(FakeSource):
            def exists(self, repo):
                return None
        self.assertEqual(codes("https://github.com/x/y/labels/bug", res(source=S())), [("UNCHECKED", "bug")])

    def test_global_search_with_repo(self):
        self.assertEqual(codes("https://github.com/issues?q=repo%3Aacme%2Fapp+label%3Anope"), [("LABEL", "nope")])

    def test_global_search_org_skipped(self):
        self.assertEqual(codes("https://github.com/issues?q=org%3Aacme+label%3Anope"), [])

    def test_search_page(self):
        self.assertEqual(codes("https://github.com/search?q=repo%3Aacme%2Fapp+label%3Anope&type=issues"),
                         [("LABEL", "nope")])

    def test_repo_qualifier_overrides_path(self):
        src = FakeSource({"other/lib": ["x"]})
        self.assertEqual(codes("https://github.com/acme/app/issues?q=repo%3Aother%2Flib+label%3Abug", res(source=src)),
                         [("LABEL", "bug")])

    def test_unrelated_urls(self):
        self.assertEqual(codes("https://github.com/acme/app/blob/main/labels/nope.md https://github.com/acme/app/issues/12"), [])

    def test_reserved_owner(self):
        self.assertEqual(codes("https://github.com/orgs/acme/labels/nope"), [])

    def test_dedupe_same_line(self):
        out, *_ = L.run([self._tree({"README.md": "[https://github.com/acme/app/labels/nope](https://github.com/acme/app/labels/nope)\n"})],
                        "acme/app", OWN, FakeSource())
        self.assertEqual(len(out), 1)

    def test_line_numbers(self):
        out = []
        L.scan_text("R.md", "a\nb\nhttps://github.com/acme/app/labels/nope\n", "acme/app", res(), out)
        self.assertEqual(out[0].line, 3)

    def _tree(self, files):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        for k, v in files.items():
            p = Path(d) / k
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(v, encoding="utf-8")
        return d


class Templates(unittest.TestCase):
    def tl(self, text, md=False):
        return [x[1] for x in L.template_labels(text, md)]

    def test_flow_list(self):
        self.assertEqual(self.tl('name: Bug\nlabels: ["bug", "needs triage"]\nbody: []\n'), ["bug", "needs triage"])

    def test_block_list(self):
        self.assertEqual(self.tl("name: Bug\nlabels:\n  - bug\n  - 'type: bug'  # the type\nbody:\n  - type: markdown\n"),
                         ["bug", "type: bug"])

    def test_comma_inside_list_item(self):
        self.assertEqual(self.tl("labels:\n  - area/datasource,type/new-plugin-request\n"),
                         ["area/datasource", "type/new-plugin-request"])

    def test_space_separated_is_one_name(self):
        # rust-lang/rust tracking_issue_future.md: only commas separate
        self.assertEqual(self.tl("---\nlabels: C-tracking-issue T-compiler\n---\n", True), ["C-tracking-issue T-compiler"])

    def test_comma_string(self):
        self.assertEqual(self.tl("labels: bug, needs triage\n"), ["bug", "needs triage"])

    def test_quoted_comma_string(self):
        self.assertEqual(self.tl("labels: 'bug, enhancement'\n"), ["bug", "enhancement"])

    def test_multiline_flow(self):
        self.assertEqual(self.tl('labels: [\n  "bug",\n  "docs"\n]\n'), ["bug", "docs"])

    def test_empty(self):
        self.assertEqual(self.tl("labels: ''\n"), [])
        self.assertEqual(self.tl("labels: []\n"), [])

    def test_nested_labels_key_ignored(self):
        self.assertEqual(self.tl("body:\n  - type: dropdown\n    attributes:\n      labels: nope\n"), [])

    def test_markdown_front_matter(self):
        self.assertEqual(self.tl("---\nname: Bug\nlabels: bug, nope\n---\n\nlabels: ignored\n", True), ["bug", "nope"])

    def test_markdown_without_front_matter(self):
        self.assertEqual(self.tl("labels: bug\n", True), [])

    def test_check_template_missing(self):
        out = []
        L.scan_text(".github/ISSUE_TEMPLATE/bug.yml", 'labels: ["Bug", "nope", "bug"]\n', "acme/app",
                    res(), out, True)
        self.assertEqual([(f.code, f.subject, f.severity) for f in out],
                         [("CASE", "Bug", "warning"), ("LABEL", "nope", "error")])

    def test_template_suggest_normalised(self):
        out = []
        L.scan_text(".github/ISSUE_TEMPLATE/bug.yml", "labels: [type-bug]\n", "acme/app", res(), out, True)
        self.assertEqual(out[0].suggest, '"type: bug"')

    def test_template_without_repo(self):
        out = []
        L.scan_text(".github/ISSUE_TEMPLATE/bug.yml", "labels: [bug]\n", None, L.Resolver(None, None, None, None), out, True)
        self.assertEqual([f.code for f in out], ["UNCHECKED"])


class Suggest(unittest.TestCase):
    def test_plural(self):
        self.assertEqual(L.LabelSet(["bug"]).suggest("bugs"), "bug")

    def test_prefix_added(self):
        self.assertEqual(L.LabelSet(["from: sanitizer", "bug"]).suggest("sanitizer"), "from: sanitizer")

    def test_prefix_ambiguous(self):
        self.assertEqual(L.LabelSet(["from: sanitizer", "area: sanitizer"]).suggest("sanitizer"), "")

    def test_none(self):
        self.assertEqual(L.LabelSet(["bug"]).suggest("security"), "")

    def test_emoji_prefix(self):
        self.assertEqual(L.LabelSet(["\U0001f41b bug"]).suggest("bug"), "\U0001f41b bug")


class LabelFile(unittest.TestCase):
    def test_json_objects(self):
        self.assertEqual(L.parse_label_file('[{"name":"bug"},{"name":"a b"}]'), ["bug", "a b"])

    def test_json_strings(self):
        self.assertEqual(L.parse_label_file('["bug"]'), ["bug"])

    def test_lines(self):
        self.assertEqual(L.parse_label_file("bug\n# c\n\nhelp wanted\n"), ["bug", "help wanted"])


class Api(unittest.TestCase):
    def test_pages_until_short_page(self):
        class A(L.ApiSource):
            def _get(self, path):
                page = int(path.rsplit("page=", 1)[1])
                return 200, [{"name": "l%d-%d" % (page, i)} for i in range(100 if page < 3 else 7)]
        self.assertEqual(len(A().labels("x/y")), 207)

    def test_partial_list_is_unreadable(self):
        # a list cut at the page limit would make every label on the unread pages a false error
        class A(L.ApiSource):
            def _get(self, path):
                return 200, [{"name": "x"}] * 100
        self.assertIsNone(A().labels("x/y"))

    def test_404_means_missing(self):
        class A(L.ApiSource):
            def _get(self, path):
                return 404, None
        a = A()
        self.assertIsNone(a.labels("x/y"))
        self.assertIs(a.exists("x/y"), False)


class Tokenize(unittest.TestCase):
    def test_quotes(self):
        self.assertEqual(L.tokenize('is:open label:"good first issue" x'), ["is:open", 'label:"good first issue"', "x"])

    def test_split_values(self):
        self.assertEqual(L.split_values('bug,"help wanted"'), [("bug", False), ("help wanted", True)])


class Cli(unittest.TestCase):
    def tree(self, files, git_url=None):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        for k, v in files.items():
            p = Path(d) / k
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(v, encoding="utf-8")
        if git_url:
            (Path(d) / ".git").mkdir()
            (Path(d) / ".git" / "config").write_text('[remote "origin"]\n\turl = %s\n' % git_url, encoding="utf-8")
        return d

    def labels_file(self, d, names):
        p = Path(d) / "labels.json"
        p.write_text(json.dumps([{"name": n} for n in names]), encoding="utf-8")
        return str(p)

    def call(self, argv):
        o, e = io.StringIO(), io.StringIO()
        with redirect_stdout(o), redirect_stderr(e):
            rc = L.main(argv)
        return rc, o.getvalue(), e.getvalue()

    def test_clean_exit_0(self):
        d = self.tree({"README.md": "https://github.com/acme/app/labels/bug\n"}, "https://github.com/acme/app.git")
        rc, out, _ = self.call([d, "--labels", self.labels_file(d, OWN), "--offline"])
        self.assertEqual(rc, 0, out)

    def test_error_exit_1(self):
        d = self.tree({"CONTRIBUTING.md": "https://github.com/acme/app/labels/nope\n"}, "git@github.com:acme/app.git")
        rc, out, _ = self.call([d, "--labels", self.labels_file(d, OWN), "--offline"])
        self.assertEqual(rc, 1)
        self.assertIn("CONTRIBUTING.md:1: error LABEL acme/app", out)

    def test_no_files_exit_2(self):
        d = self.tree({})
        rc, _, err = self.call([d, "--offline"])
        self.assertEqual(rc, 2)
        self.assertIn("nothing was checked", err)

    def test_unreadable_own_labels_exit_2(self):
        d = self.tree({"README.md": "https://github.com/acme/app/labels/bug\n"}, "https://github.com/acme/app")
        rc, _, err = self.call([d, "--offline"])
        self.assertEqual(rc, 2)
        self.assertIn("NOT checked", err)

    def test_repo_from_git_remote(self):
        d = self.tree({"README.md": "x"}, "https://github.com/Acme-Co/my.app.git")
        self.assertEqual(L.repo_from_git(d), "Acme-Co/my.app")

    def test_json_output(self):
        d = self.tree({".github/ISSUE_TEMPLATE/bug.yml": "labels: [nope]\n"}, "https://github.com/acme/app")
        rc, out, _ = self.call([d, "--labels", self.labels_file(d, OWN), "--offline", "--json"])
        self.assertEqual(rc, 1)
        j = json.loads(out)
        self.assertEqual(j["findings"][0]["path"], ".github/ISSUE_TEMPLATE/bug.yml")
        self.assertEqual(j["findings"][0]["code"], "LABEL")

    def test_config_yml_not_a_template(self):
        d = self.tree({".github/ISSUE_TEMPLATE/config.yml": "blank_issues_enabled: false\nlabels: [nope]\n"},
                      "https://github.com/acme/app")
        rc, out, _ = self.call([d, "--labels", self.labels_file(d, OWN), "--offline"])
        self.assertEqual(rc, 0, out)

    def test_template_link_checked_against_local_dir(self):
        d = self.tree({".github/ISSUE_TEMPLATE/bug.yml": "name: b\n",
                       "README.md": "https://github.com/acme/app/issues/new?template=bug.md\n"},
                      "https://github.com/acme/app")
        rc, out, _ = self.call([d, "--labels", self.labels_file(d, OWN), "--offline"])
        self.assertEqual(rc, 1)
        self.assertIn("TEMPLATE", out)

    def test_repo_root_without_template_dir(self):
        # no folder of its own: the owner's .github repository decides, and offline cannot read it
        d = self.tree({"README.md": "https://github.com/acme/app/issues/new?template=bug.md\n"},
                      "https://github.com/acme/app")
        rc, out, err = self.call([d, "--labels", self.labels_file(d, OWN), "--offline"])
        self.assertEqual(rc, 2)
        self.assertIn("UNCHECKED", out)
        self.assertIn("NOT checked", err)

    def test_local_tree_without_folder_beats_api(self):
        # the checkout has no template folder; the API (another branch, stale) must not be asked
        class S(FakeSource):
            def org_templates(self, owner):
                return []
        d = self.tree({"README.md": "https://github.com/acme/app/issues/new?template=bug.md\n"},
                      "https://github.com/acme/app")
        out, *_ = L.run([d], "acme/app", OWN, S(templates={"acme/app": ["bug.md"]}))
        self.assertEqual([f.code for f in out], ["TEMPLATE"])

    def test_skips_node_modules(self):
        d = self.tree({"node_modules/x/README.md": "https://github.com/acme/app/labels/nope\n",
                       "README.md": "ok"}, "https://github.com/acme/app")
        rc, out, _ = self.call([d, "--labels", self.labels_file(d, OWN), "--offline"])
        self.assertEqual(rc, 0, out)


if __name__ == "__main__":
    unittest.main(verbosity=1)
