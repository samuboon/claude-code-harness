**日本語版: [README.ja.md](README.ja.md)**

# forge-scope-check — two of our five Forge apps could not read a single board or group member, and every file looked fine

A Forge app declares its scopes in `manifest.yml`, and its code calls Jira with
`api.asApp().requestJira(route`...`)`. Nothing ties the two together until the app is
installed on a real site and a call comes back 403. We found that out on our own apps
before they ever reached a site, and only because we went through every call by hand
against Atlassian's API definitions:

- **A JQL function for sprint dates declared `read:jira-work` and nothing else.** All four of
  its board and sprint calls go to Jira Software (`/rest/agile/1.0/...`), and Jira Software
  has no classic scopes at all. The Forge docs put it in one line: *"Jira Software doesn't
  support classic scopes. Use granular scopes instead."*
  ([source](https://developer.atlassian.com/platform/forge/manifest-reference/scopes-product-jsw/))
  It would have returned nothing, on every query.
- **A JQL function for project-role members called `GET /rest/api/3/group/member` without the
  scope it needs.** The group members — the reason the app exists — would never have come back.
- **Both called `api.asUser()` from a JQL function.** The `requestJira` reference says:
  *"This context method is only available in modules that support the UI kit."*
  ([source](https://developer.atlassian.com/platform/forge/apis-reference/fetch-api-product.requestjira/),
  read 2026-09-23.) A JQL function is not one of them.

`forge_scope_check.py` does that hand check mechanically.

```bash
python forge_scope_check.py path/to/forge-app             # report
python forge_scope_check.py path/to/forge-app --tsv       # one row per call / finding
python forge_scope_check.py app --allow-deprecated        # deprecated calls warn instead of fail
```

Standard library only. No Node, no Forge CLI, no network at check time.

---

## What it checks

It reads `manifest.yml` and every `.js/.jsx/.ts/.tsx/.mjs/.cjs` under `src/`, finds each
`requestJira(route`...`)`, reads the HTTP method from the options object right after the
path (or from a constant defined in the same file, or through a small wrapper such as
`const get = (path) => api.asApp().requestJira(path, OPTS)`), and looks the call up in
`jira_scopes.json`: **724 operations** from Atlassian's published OpenAPI definitions for the
Jira platform and Jira Software, built 2026-09-23.

| Finding | Meaning |
|---|---|
| `MISSING` | The declared scopes contain neither the whole classic set nor the whole granular set the call needs. Half a granular set is not enough. For Jira Software calls the message says that `read:jira-work` does not open them. |
| `ASUSER` | `api.asUser()` with no account id, in the handler of a function that only a non-UI module (JQL function, trigger, scheduled trigger, web trigger...) reaches. If the same file also serves a UI resolver, it is a warning instead, because the tool cannot tell which export the call is in. |
| `DEPRECATED` | The definition marks the operation deprecated. It fails by default: we left two deprecated calls in as warnings for a day and nobody read the warnings. `--allow-deprecated` turns it back into a warning. |
| warning `UNUSED` | A declared scope no call needs. Only printed when every call was checked, and never for `storage:app` and other scopes REST calls cannot justify. Product events also need scopes and are not seen. |
| warning `REDUNDANT` | A classic scope that every call needing it already gets from declared granular scopes. |
| `unchecked` | A call it could not resolve: the path is a variable, the method is a variable, it is Confluence or Bitbucket, or the operation is not in the table. |

**Exit codes:** 0 = every call checked, no findings. 1 = findings. 2 = the app could not be
read (no manifest, YAML this reader does not handle — anchors, flow mappings — or no code).
**3 = no findings, but some calls were not checked. That is not a pass**, and it is kept
apart from 0 on purpose: a checker that reports "0 problems" after skipping half the calls
is worse than none.

---

## Measured, on apps whose answer we already knew

Our five Forge apps (JQL functions and a custom field), at two points on 2026-09-18:

| Version | Calls checked | Unchecked | Findings |
|---|---|---|---|
| Before we fixed them by hand | 26 | 0 | **3 of 5 apps**: `MISSING` 6 (4 Jira Software calls, 2 `group/member`), `ASUSER` 10 lines, `DEPRECATED` 2 (`/rest/api/3/search`, `/rest/agile/1.0/board/{}/issue`); plus 1 `UNUSED` warning |
| Now | 23 | 0 | **0** in all 5 |

Every line in the first row — the unused `read:jira-user` included — is something we had
already found by hand that day and fixed in two commits. The tool found all of them from
the table alone, and nothing else. For the 18 operations those apps call, the table built on 2026-09-23 agrees with the
one we copied out by hand on 2026-09-18 on all 18.

41 tests. `mutation_check.py` breaks the checker in 21 ways (half a granular set counted as
enough, every call read as GET, unchecked calls counted as a pass, the UI resolver not
recognised...) and checks the tests fail each time. **The first run caught 18 of 21.** The
three survivors were real gaps: a UI-only function flagged as a warning went unnoticed,
the "most literal segments wins" rule was never exercised because every test path matched
exactly, and a redundant-scope warning firing on half a granular set was never tried.
Each got a test; now 21 of 21.

**Every app it has seen is ours** — five apps, 23 calls, written by the same hands in the
same style. One run on someone else's Forge app, with a finding it got right or wrong,
would be worth more than this table. We have not compared it with `forge lint` (we could
not run it here: it needs Node and the Forge CLI).

---

## What it does not do

- Jira only. `requestConfluence` / `requestBitbucket` calls come back `unchecked`.
- Wrappers are followed one level, by name, across files; a constant holding the options is
  read only if it is defined in the same file. Anything more dynamic is `unchecked`.
- `asUser()` is judged per file, not per function body; imports between files are not followed.
- It does not know which scopes product events (`avi:jira:...` triggers) need.
- The table is only as fresh as its build date. `python build_table.py --diff` fetches the
  definitions again and prints the operations that changed; `python build_table.py`
  rewrites the table (one operation per line, so the diff is readable). Three platform
  operations (`/rest/api/3/uiModifications`) list `read:jira-work` under the granular tag;
  the table keeps the tag and records them under `meta.anomalies`.

```bash
python -m unittest test_forge_scope_check -v
python mutation_check.py
```

MIT, like the rest of this repository.
