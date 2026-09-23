# -*- coding: utf-8 -*-
"""Tests for forge_scope_check.py.   python -m unittest test_forge_scope_check -v"""
import shutil
import tempfile
import unittest
from pathlib import Path

import forge_scope_check as fsc

# A small table so the tests do not move when Atlassian changes the definition.
OPS = {
    "GET /rest/api/3/issue/createmeta/{}/issuetypes": {"path": "/rest/api/3/issue/createmeta/{projectIdOrKey}/issuetypes",
                                                       "classic": ["write:jira-work"], "granular": ["read:issue-meta:jira"],
                                                       "deprecated": False, "stated": True},
    "GET /rest/api/3/issue/{}/{}/issuetypes": {"path": "/rest/api/3/issue/{a}/{b}/issuetypes (made up)",
                                               "classic": ["read:jira-work"], "granular": ["read:x:jira"],
                                               "deprecated": False, "stated": True},
    "GET /rest/api/3/issue/{}": {"path": "/rest/api/3/issue/{issueIdOrKey}", "classic": ["read:jira-work"],
                                 "granular": ["read:issue:jira", "read:user:jira"], "deprecated": False, "stated": True},
    "GET /rest/api/3/issue/createmeta": {"path": "/rest/api/3/issue/createmeta", "classic": ["write:jira-work"],
                                         "granular": ["read:issue-meta:jira"], "deprecated": True, "stated": True},
    "PUT /rest/api/3/issue/{}": {"path": "/rest/api/3/issue/{issueIdOrKey}", "classic": ["write:jira-work"],
                                 "granular": ["write:issue:jira"], "deprecated": False, "stated": True},
    "GET /rest/api/3/group/member": {"path": "/rest/api/3/group/member", "classic": ["manage:jira-configuration"],
                                     "granular": ["read:group:jira", "read:user:jira"], "deprecated": False, "stated": True},
    "GET /rest/api/3/serverInfo": {"path": "/rest/api/3/serverInfo", "classic": [], "granular": [],
                                   "deprecated": False, "stated": False},
    "GET /rest/agile/1.0/board": {"path": "/rest/agile/1.0/board", "classic": [],
                                  "granular": ["read:board-scope:jira-software", "read:project:jira"],
                                  "deprecated": False, "stated": True},
    "GET /rest/agile/1.0/board/{}/sprint": {"path": "/rest/agile/1.0/board/{boardId}/sprint", "classic": [],
                                            "granular": ["read:sprint:jira-software"], "deprecated": False, "stated": True},
}


def make_index(ops):
    index = {}
    for key in ops:
        meth, p = key.split(" ", 1)
        index.setdefault((meth, len(p.split("/"))), []).append(key)
    return index


INDEX = make_index(OPS)

MANIFEST_FN = """\
modules:
  jira:jqlFunction:
    - key: my-fn
      name: myFn
      function: fn   # a comment
  function:
    - key: fn
      handler: index.run
permissions:
  scopes:
%s
app:
  id: ari:cloud:ecosystem::app/x
"""


class AppCase(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="fsc-test-"))
        self.addCleanup(shutil.rmtree, self.dir, True)

    def app(self, manifest, files):
        (self.dir / "manifest.yml").write_text(manifest, encoding="utf-8")
        for name, body in files.items():
            p = self.dir / "src" / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body, encoding="utf-8")
        return self.dir

    def scopes(self, *names):
        return MANIFEST_FN % "\n".join("    - " + n for n in names)

    def run_check(self, app, **kw):
        res = fsc.check(app, OPS, INDEX, **kw)
        return res, fsc.exit_code(res)

    def kinds(self, res):
        return sorted(k for k, _w, _m in res["findings"])


class TestYaml(unittest.TestCase):
    def test_module_key_with_colon_and_scope_list(self):
        doc = fsc.load_yaml(MANIFEST_FN % "    - read:jira-work\n    - storage:app")
        self.assertIn("jira:jqlFunction", doc["modules"])
        self.assertEqual(doc["permissions"]["scopes"], ["read:jira-work", "storage:app"])
        self.assertEqual(doc["modules"]["function"][0]["handler"], "index.run")

    def test_flow_list_and_block_string(self):
        doc = fsc.load_yaml("permissions:\n  scopes: [read:jira-work, 'write:jira-work']\n"
                            "app:\n  description: >\n    two\n    lines\n  id: x\n")
        self.assertEqual(doc["permissions"]["scopes"], ["read:jira-work", "write:jira-work"])
        self.assertEqual(doc["app"]["id"], "x")

    def test_sequence_at_same_indent_as_key(self):
        doc = fsc.load_yaml("permissions:\n  scopes:\n  - read:jira-work\n  - storage:app\n")
        self.assertEqual(doc["permissions"]["scopes"], ["read:jira-work", "storage:app"])

    def test_anchor_is_refused_not_guessed(self):
        with self.assertRaises(fsc.YamlError):
            fsc.load_yaml("a: &x 1\nb: *x\n")

    def test_bad_indent_is_refused(self):
        with self.assertRaises(fsc.YamlError):
            fsc.load_yaml("a:\n    b: 1\n  c: 2\n")


class TestCodeReading(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(fsc.normalize_path("/rest/api/3/issue/${key}?fields=${f}"), "/rest/api/3/issue/{}")
        self.assertEqual(fsc.normalize_path("/rest/agile/1.0/board/${id}/sprint/"), "/rest/agile/1.0/board/{}/sprint")

    def test_comments_blanked_strings_kept(self):
        src = "a(); // asUser()\n/* asUser() */ b('http://x//y'); c(`p // q`);\n"
        out = fsc.strip_js_comments(src)
        self.assertEqual(len(out), len(src))
        self.assertNotIn("asUser", out)
        self.assertIn("http://x//y", out)
        self.assertIn("`p // q`", out)

    def method(self, text):
        m = fsc.ROUTE_RE.search(text)
        return fsc.method_of(text, m.end())

    def test_method_literal_default_and_unknown(self):
        self.assertEqual(self.method("x.requestJira(route`/a`, { method: 'PUT', body })"), "PUT")
        self.assertEqual(self.method("x.requestJira(route`/a`)"), "GET")
        self.assertEqual(self.method("x.requestJira(route`/a`, { headers: {} })"), "GET")
        self.assertIsNone(self.method("x.requestJira(route`/a`, { method: verb })"))
        self.assertIsNone(self.method("x.requestJira(route`/a`, opts)"))

    def test_method_from_constant_in_same_file(self):
        text = "const H = { method: 'POST', headers: {} };\nx.requestJira(route`/a`, H);"
        self.assertEqual(self.method(text), "POST")

    def test_method_does_not_read_the_next_call(self):
        text = ("x.requestJira(route`/a`, { headers: {} });\n"
                "x.requestJira(route`/b`, { method: 'DELETE' });\n")
        got = [fsc.method_of(text, m.end()) for m in fsc.ROUTE_RE.finditer(text)]
        self.assertEqual(got, ["GET", "DELETE"])


class TestResolve(unittest.TestCase):
    def test_exact(self):
        self.assertEqual(fsc.resolve("GET", "/rest/api/3/issue/{}", OPS, INDEX)[0], "GET /rest/api/3/issue/{}")

    def test_literal_beats_parameter(self):
        self.assertEqual(fsc.resolve("GET", "/rest/api/3/issue/createmeta", OPS, INDEX)[0],
                         "GET /rest/api/3/issue/createmeta")

    def test_literal_id_matches_parameter(self):
        key, note = fsc.resolve("GET", "/rest/api/3/issue/ABC-1", OPS, INDEX)
        self.assertEqual(key, "GET /rest/api/3/issue/{}")
        self.assertIn("literal", note)

    def test_more_literal_segments_win(self):
        key, _note = fsc.resolve("GET", "/rest/api/3/issue/createmeta/PROJ/issuetypes", OPS, INDEX)
        self.assertEqual(key, "GET /rest/api/3/issue/createmeta/{}/issuetypes")

    def test_v2_is_checked_against_v3(self):
        key, note = fsc.resolve("GET", "/rest/api/2/issue/{}", OPS, INDEX)
        self.assertEqual(key, "GET /rest/api/3/issue/{}")
        self.assertIn("v2", note)

    def test_unknown(self):
        self.assertIsNone(fsc.resolve("GET", "/rest/api/3/nothing", OPS, INDEX)[0])
        self.assertIsNone(fsc.resolve("POST", "/rest/api/3/issue/{}", OPS, INDEX)[0])


class TestCheck(AppCase):
    def test_clean_app_passes(self):
        app = self.app(self.scopes("read:jira-work"),
                       {"index.js": "export const run = () => api.asApp().requestJira(route`/rest/api/3/issue/${k}`);"})
        res, code = self.run_check(app)
        self.assertEqual((code, res["findings"], res["unchecked"]), (0, [], []))
        self.assertEqual(len(res["calls"]), 1)

    def test_missing_classic_scope(self):
        app = self.app(self.scopes("read:jira-work"),
                       {"index.js": "api.asApp().requestJira(route`/rest/api/3/group/member?groupId=${g}`);"})
        res, code = self.run_check(app)
        self.assertEqual(code, 1)
        self.assertEqual(self.kinds(res), ["MISSING"])
        self.assertIn("manage:jira-configuration", res["findings"][0][2])

    def test_granular_set_satisfies(self):
        app = self.app(self.scopes("read:group:jira", "read:user:jira"),
                       {"index.js": "api.asApp().requestJira(route`/rest/api/3/group/member`);"})
        self.assertEqual(self.run_check(app)[1], 0)

    def test_half_a_granular_set_does_not_satisfy(self):
        app = self.app(self.scopes("read:group:jira"),
                       {"index.js": "api.asApp().requestJira(route`/rest/api/3/group/member`);"})
        res, code = self.run_check(app)
        self.assertEqual(code, 1)
        self.assertIn("read:user:jira", res["findings"][0][2])

    def test_jira_software_is_not_opened_by_classic(self):
        app = self.app(self.scopes("read:jira-work"),
                       {"index.js": "api.asApp().requestJira(route`/rest/agile/1.0/board?startAt=${s}`);"})
        res, code = self.run_check(app)
        self.assertEqual(code, 1)
        self.assertIn("read:board-scope:jira-software", res["findings"][0][2])
        self.assertIn("no classic scopes", res["findings"][0][2])

    def test_method_matters(self):
        app = self.app(self.scopes("read:jira-work"),
                       {"index.js": "api.asApp().requestJira(route`/rest/api/3/issue/${k}`, { method: 'PUT', body });"})
        res, code = self.run_check(app)
        self.assertEqual(code, 1)
        self.assertIn("PUT /rest/api/3/issue/{}", res["findings"][0][2])

    def test_no_scope_needed(self):
        app = self.app(self.scopes("storage:app"),
                       {"index.js": "api.asApp().requestJira(route`/rest/api/3/serverInfo`);"})
        self.assertEqual(self.run_check(app)[1], 0)

    def test_deprecated_fails_unless_allowed(self):
        app = self.app(self.scopes("write:jira-work"),
                       {"index.js": "api.asApp().requestJira(route`/rest/api/3/issue/createmeta`);"})
        res, code = self.run_check(app)
        self.assertEqual((code, self.kinds(res)), (1, ["DEPRECATED"]))
        res, code = self.run_check(app, allow_deprecated=True)
        self.assertEqual(code, 0)
        self.assertEqual([k for k, _w, _m in res["warnings"]], ["DEPRECATED"])

    def test_asuser_in_non_ui_handler(self):
        app = self.app(self.scopes("read:jira-work"),
                       {"index.js": "export const run = () => api.asUser().requestJira(route`/rest/api/3/issue/${k}`);"})
        res, code = self.run_check(app)
        self.assertEqual((code, self.kinds(res)), (1, ["ASUSER"]))
        self.assertIn("jira:jqlFunction", res["findings"][0][2])

    def test_asuser_with_account_id_is_fine(self):
        app = self.app(self.scopes("read:jira-work"),
                       {"index.js": "export const run = () => api.asUser(id).requestJira(route`/rest/api/3/issue/${k}`);"})
        self.assertEqual(self.run_check(app)[1], 0)

    def test_asuser_behind_ui_resolver_is_fine(self):
        manifest = """\
modules:
  jira:issuePanel:
    - key: panel
      resource: main
      resolver:
        function: res
      title: Panel
  function:
    - key: res
      handler: index.handler
resources:
  - key: main
    path: static/build
permissions:
  scopes:
    - read:jira-work
"""
        app = self.app(manifest, {"index.js": "api.asUser().requestJira(route`/rest/api/3/issue/${k}`);"})
        res, code = self.run_check(app)
        self.assertEqual((code, res["findings"], res["warnings"]), (0, [], []))

    def test_asuser_in_file_shared_with_ui_is_a_warning(self):
        manifest = """\
modules:
  jira:issuePanel:
    - key: panel
      resource: main
      resolver:
        function: res
  trigger:
    - key: t
      function: job
      events:
        - avi:jira:created:issue
  function:
    - key: res
      handler: index.handler
    - key: job
      handler: index.job
permissions:
  scopes:
    - read:jira-work
"""
        app = self.app(manifest, {"index.js": "api.asUser().requestJira(route`/rest/api/3/issue/${k}`);"})
        res, code = self.run_check(app)
        self.assertEqual((code, res["findings"]), (0, []))
        self.assertEqual([k for k, _w, _m in res["warnings"]], ["ASUSER"])

    def test_detached_route_is_unchecked_not_green(self):
        app = self.app(self.scopes("read:jira-work"),
                       {"index.js": "const r = route`/rest/api/3/issue/${k}`;\napi.asApp().requestJira(r);"})
        res, code = self.run_check(app)
        self.assertEqual(code, 3)
        self.assertEqual(len(res["unchecked"]), 2)
        self.assertEqual(res["warnings"], [])   # no "unused" claims while calls are unchecked

    def test_wrapper_is_followed(self):
        code_text = ("const H = { headers: { Accept: 'application/json' } };\n"
                     "const get = (path) => api.asApp().requestJira(path, H);\n"
                     "export async function run() { return get(route`/rest/agile/1.0/board/${b}/sprint`); }\n")
        app = self.app(self.scopes("read:jira-work"), {"index.js": code_text})
        res, code = self.run_check(app)
        self.assertEqual(res["unchecked"], [])
        self.assertEqual((code, self.kinds(res)), (1, ["MISSING"]))
        self.assertIn("read:sprint:jira-software", res["findings"][0][2])

    def test_wrapper_across_files_and_function_form(self):
        app = self.app(self.scopes("read:sprint:jira-software"), {
            "http.js": "export function jget(p) { return api.asApp().requestJira(p); }\n",
            "index.js": "import { jget } from './http';\nexport const run = () => jget(route`/rest/agile/1.0/board/1/sprint`);\n",
        })
        res, code = self.run_check(app)
        self.assertEqual((code, res["unchecked"], res["findings"]), (0, [], []))

    def test_confluence_is_unchecked(self):
        app = self.app(self.scopes("read:jira-work"),
                       {"index.js": "api.asApp().requestConfluence(route`/wiki/api/v2/pages`);"})
        res, code = self.run_check(app)
        self.assertEqual(code, 3)
        self.assertIn("requestConfluence", res["unchecked"][0][2])

    def test_unused_and_redundant_warnings(self):
        app = self.app(self.scopes("read:jira-work", "read:issue:jira", "read:user:jira",
                                   "manage:jira-project", "storage:app"),
                       {"index.js": "api.asApp().requestJira(route`/rest/api/3/issue/${k}`);"})
        res, code = self.run_check(app)
        self.assertEqual(code, 0)
        warns = sorted((k, m.split(" ", 1)[0]) for k, _w, m in res["warnings"])
        self.assertEqual(warns, [("REDUNDANT", "read:jira-work"), ("UNUSED", "manage:jira-project")])

    def test_no_redundant_warning_when_granular_only_half_covers(self):
        app = self.app(self.scopes("read:jira-work", "read:issue:jira"),
                       {"index.js": "api.asApp().requestJira(route`/rest/api/3/issue/${k}`);"})
        res, code = self.run_check(app)
        self.assertEqual(code, 0)
        self.assertNotIn("REDUNDANT", [k for k, _w, _m in res["warnings"]])

    def test_comment_is_not_a_call(self):
        app = self.app(self.scopes("read:jira-work"),
                       {"index.js": "// api.asApp().requestJira(route`/rest/api/3/group/member`)\n"
                                    "api.asApp().requestJira(route`/rest/api/3/issue/${k}`);"})
        res, code = self.run_check(app)
        self.assertEqual((code, len(res["calls"])), (0, 1))

    def test_node_modules_is_skipped(self):
        app = self.app(self.scopes("read:jira-work"),
                       {"index.js": "api.asApp().requestJira(route`/rest/api/3/issue/${k}`);",
                        "node_modules/x/index.js": "api.asApp().requestJira(route`/rest/api/3/group/member`);"})
        self.assertEqual(self.run_check(app)[1], 0)

    def test_unreadable_app_is_exit_2(self):
        res, code = self.run_check(self.dir)
        self.assertEqual(code, 2)
        self.app("a: &x 1\n", {"index.js": ""})
        res, code = self.run_check(self.dir)
        self.assertEqual(code, 2)

    def test_no_code_is_exit_2_not_green(self):
        (self.dir / "manifest.yml").write_text(self.scopes("read:jira-work"), encoding="utf-8")
        self.assertEqual(self.run_check(self.dir)[1], 2)


class TestShippedTable(unittest.TestCase):
    """The real table: large, from both definitions, and right on calls we have checked by hand."""

    @classmethod
    def setUpClass(cls):
        cls.data, cls.ops, cls.index = fsc.load_table()

    def test_size_and_sources(self):
        self.assertGreater(len(self.ops), 600)
        self.assertTrue(any(k.split(" ", 1)[1].startswith("/rest/agile/") for k in self.ops))
        self.assertEqual(sorted(self.data["meta"]["source"]), ["platform", "software"])

    def test_known_rows(self):
        gm = self.ops["GET /rest/api/3/group/member"]
        self.assertEqual(gm["classic"], ["manage:jira-configuration"])
        self.assertEqual(sorted(gm["granular"]), ["read:avatar:jira", "read:group:jira", "read:user:jira"])
        board = self.ops["GET /rest/agile/1.0/board"]
        self.assertEqual((board["classic"], sorted(board["granular"])),
                         ([], ["read:board-scope:jira-software", "read:project:jira"]))
        self.assertTrue(self.ops["GET /rest/api/3/search"]["deprecated"])
        self.assertFalse(self.ops["GET /rest/api/3/search/jql"]["deprecated"])

    def test_every_key_has_a_known_method_and_rest_path(self):
        for key in self.ops:
            meth, path = key.split(" ", 1)
            self.assertIn(meth, ("GET", "POST", "PUT", "DELETE", "PATCH"), key)
            self.assertTrue(path.startswith("/rest/"), key)


if __name__ == "__main__":
    unittest.main()
