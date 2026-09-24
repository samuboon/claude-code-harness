# -*- coding: utf-8 -*-
"""Replay public commits that fixed a migration collision: was it flagged before the fix?

    python replay_fixes.py                          # the 106 commits listed below (--half held out)
    python replay_fixes.py owner/name@SHA ...       # any other public commits
    python replay_fixes.py owner/name@SHA --against pr   # also merge its parent into its PR's base
    python replay_fixes.py --head owner/name ...    # the default branch today
    python replay_fixes.py --repos [--half held out]     # the 99 repositories listed below
    python replay_fixes.py --search "merge migrations"   # candidates from GitHub's commit search

For each commit it lists the repository's files at the commit and at its first parent from
codeload's tarballs (held in memory, never unpacked to disk), runs migration_check on both, and
prints:

  fixed   a finding at the parent, gone at the commit
  kept    a finding at both
  new     a finding only at the commit

When the commit is itself a merge, it also checks each parent alone and the union of the two
(what a merge gate would have seen before the merge was made):

  gate    parents alone: N and M errors; together: K errors brought in by the second parent

Nothing is written to disk and nothing is sent anywhere. Tarballs are not counted against
GitHub's anonymous API limit (60 calls an hour). A merge commit costs one call (the merge base),
--against one or two, --search one (the commit search allows 10 a minute without a key);
--head and plain commits cost none.
"""
import argparse
import json
import os
import re
import sys
import tarfile
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import migration_check as t  # noqa: E402

# (repository, commit, tool, half) -- the README's replay table. Found with GitHub's commit
# search ("multiple leaf nodes", "alembic merge heads", "flyway duplicate migration version",
# "rename flyway migration conflict", "duplicate migration version rails", "golang-migrate
# duplicate migration"), and split in two before any tuning: every other one held out.
FIXES = [
    ("ASEAN-Motor-Club/amc-backend", "0f959f3718ab", "django", "tune"),
    ("Ruan-Pablo-Oli/UfcaNewsLetter", "428e9f9ffaff", "django", "held out"),
    ("jdegreef/ochorus", "4cc7d9ad3a43", "django", "tune"),
    ("pythonkei/betweencoffee_delivery_enhance", "22aafbe0c54d", "django", "held out"),
    ("cranoraa-eng/cranoraa-knhs-website", "683f7ca5cf45", "django", "tune"),
    ("nirmitrathod74/rental-hub", "c9806ef21a18", "django", "held out"),
    ("lapomed/site-galeria", "9f23c9628088", "django", "tune"),
    ("specify/specify7", "85d7ac292045", "django", "held out"),
    ("druss16/time_capture_fullstack", "4e2fd25a5f96", "django", "tune"),
    ("andholemoksha/SSSLST_Website", "605b34b2c846", "django", "held out"),
    ("TencentBlueKing/bk-lite", "4f7b085caf84", "django", "tune"),
    ("vortex-tecnologia/rxtrack", "a89eb47f2099", "django", "held out"),
    ("unified-systems-com/tap-plugin-github-core", "f61c44a41af8", "django", "tune"),
    ("Shehank98/Ad-Monitoring", "8dfdba076d36", "django", "held out"),
    ("WaaLabs/nakavid", "599f19e3a66d", "django", "tune"),
    ("Intelleqt-AI/truckwys-backend", "df3a7a5e37be", "django", "held out"),
    ("yomeronepal/binance-bot", "7f8e622b80c7", "django", "tune"),
    ("future-agi/future-agi", "1c44a0e80612", "django", "held out"),
    ("sameer-sultan41/schoolhub", "5f331595731a", "django", "tune"),
    ("MIT-LCP/physionet-build", "99480ace231e", "django", "held out"),
    ("naumanmirza100/AIEmployee", "a6973d12c0d2", "django", "tune"),
    ("AnaharaYasuo/realestate_crawler", "a19dc74bd337", "django", "held out"),
    ("tzuri99/Cravr", "cd758663a269", "django", "tune"),
    ("aquarius-cc/asset_management_backend", "dba5dbdf658e", "django", "held out"),
    ("dimagi/open-chat-studio", "7949d92b9280", "django", "tune"),
    ("future-agi/future-agi", "15454b1d8f1d", "django", "held out"),
    ("SaifulHaqueNiloy/supremeai", "2fc98fe105ff", "alembic", "tune"),
    ("uselessherohn/Axis-Suite", "bce42ac9993f", "alembic", "held out"),
    ("Hardhat-Enterprises/AutoAudit", "cce021bc81fe", "alembic", "tune"),
    ("Flor771/Serviya.123456", "f1e9a79f54c1", "alembic", "held out"),
    ("aditya-zig/Revnue-Agent", "4a8116cdd5f3", "alembic", "tune"),
    ("qontinui/qontinui-web", "9d6d96d6913f", "alembic", "held out"),
    ("netcruxx-admin/netcare", "40e873a97467", "alembic", "tune"),
    ("NewLevelHub/Profy-Backend", "3ce22d41dd52", "alembic", "held out"),
    ("yash-1105/marine-time-motion-platform", "78236b653ea1", "alembic", "tune"),
    ("hassan-mohagheghian/job-flow", "47e1d1d7114f", "alembic", "held out"),
    ("Vasudev-2468/Journal_management_system", "dd8940c9f776", "alembic", "tune"),
    ("Givemeboga/Baitway", "edd5482c53b8", "alembic", "held out"),
    ("Wh1stle05/Aurora-blog-backend", "21227b425439", "alembic", "tune"),
    ("muditparashar2410/pos-food", "1a4e1d00c874", "alembic", "held out"),
    ("Glynac-Team1/Compliance-Document-Review-App", "19fe406fe1de", "alembic", "tune"),
    ("hussu97/mm-ecommerce", "c21cfd7c93d5", "alembic", "held out"),
    ("ProgrammingClub-DAU/website", "468314ce0e7c", "flyway", "tune"),
    ("SentenciaSQL/animalin", "647b959a3c92", "flyway", "held out"),
    ("suner-dev/discipolat_app", "e21661286b64", "flyway", "tune"),
    ("zelinsky-alexander/neta-coordinator", "f480a7305078", "flyway", "held out"),
    ("Farhad054/MC-School", "5abc4d2ffffb", "flyway", "tune"),
    ("JanakaUPerera/church-management-system", "40387989d736", "flyway", "held out"),
    ("anjanx44/Bazario", "b821d4a6d3a2", "flyway", "tune"),
    ("cscpratapnagar-ai/Universal-Master-Learning-Platform-Backend", "4f4543b19a19", "flyway", "held out"),
    ("srikanth-jeldi/ChessVerse-AI", "1fb0d45db2da", "flyway", "tune"),
    ("anandureghu/sunway-erp-be", "a7e84a9d615c", "flyway", "held out"),
    ("nachoechave/comercio-flex", "2caea5a28046", "flyway", "tune"),
    ("varun2varma/garageos-backend", "4101421fb03b", "flyway", "held out"),
    ("VigneshA23/NForce-RetailOps", "2a1f05974d3f", "flyway", "tune"),
    ("dang232/Ecomer", "59916b3f7145", "flyway", "held out"),
    ("nyankwoga/ecosystem_banking_backend", "e39d04c5befe", "flyway", "tune"),
    ("IamHDA/Englow3_BE", "84e6c7e06392", "flyway", "held out"),
    ("Siona-mm/DepotIQ", "2ccaf232f46b", "flyway", "tune"),
    ("thangnq090/evchargingplatform", "486e44a651fc", "flyway", "held out"),
    ("Mohammad-Adnan-Shakil/DeltaBox", "dab454ddfd77", "flyway", "tune"),
    ("EduA-system/EduA-system", "b92c4d4a45a4", "flyway", "held out"),
    ("Tayebbb/TurfChai", "edcafc58f232", "flyway", "tune"),
    ("ZenBonsai-Team/Bonsai_Shop", "7d22451f26e3", "flyway", "held out"),
    ("Arnel-rah/hei-graduates-api", "83e64562bf3a", "flyway", "tune"),
    ("bny8476/clinic-website", "31826bca0c16", "flyway", "held out"),
    ("Group-M-HMS/AgileGroupM-Hotel-Management-System", "614a7324e204", "flyway", "tune"),
    ("formalizese-hub/formalizesehub-infrastructure", "11b40067b356", "flyway", "held out"),
    ("xiaojunzhe32-ai/IT-Request", "aa5913da7f6a", "flyway", "tune"),
    ("zctiong-iss/crewsafe", "12b2424bb12d", "flyway", "held out"),
    ("beyzayucel/FinSight", "79a343eb9be3", "flyway", "tune"),
    ("HieuPT-04/Project_SkillSprint", "11d920b07d8d", "flyway", "held out"),
    ("naeemAbdul-Aziz/ubs-mgt-system", "cef9d90531fd", "flyway", "tune"),
    ("tenant-hub/tenant-hub-service", "952615b12d28", "flyway", "held out"),
    ("narindra20/projectAsync", "9dcf12b04e11", "flyway", "tune"),
    ("dogiaan611/kanban-task-management", "b98915a85916", "flyway", "held out"),
    ("kanglok256/MockProjectOJT", "7d702344d3e0", "flyway", "tune"),
    ("michalbzowski/windband-manager", "17fee1a54864", "flyway", "held out"),
    ("JTech-Forums/JtechTools", "8641306a7722", "rails", "tune"),
    ("calebl/text-adventure", "6ee28ec73579", "rails", "held out"),
    ("Kronkverse/kronk", "33031c77e3c3", "rails", "tune"),
    ("AixleHQ/flow", "c1a82ca645a0", "rails", "held out"),
    ("rubyforgood/awbw", "58588d63d5cd", "rails", "tune"),
    ("Low-Light-Games/ruby-leather-armor", "1c1cffa6b4da", "rails", "held out"),
    ("tadasant/zimmer", "26e77b751c60", "rails", "tune"),
    ("tobi-techy/RAIL-BACKEND-SERVICE", "19810b83bf6c", "golang-migrate", "held out"),
    ("hassanaalwaqedi/khair", "a685117a1c28", "golang-migrate", "tune"),
    ("pericles-luz/crm", "4df05584fe80", "golang-migrate", "held out"),
    ("NJUPT-SAST/sast-link-backend-v2", "7fdac5266c85", "golang-migrate", "tune"),
    ("ndzuki/release-manager", "7169b0998cac", "golang-migrate", "held out"),
    ("Emyrk/chronicle", "5fc6cc83cb28", "golang-migrate", "tune"),
    ("Autonex009/autonex-crm-api", "1e56c523ac04", "golang-migrate", "held out"),
    ("msdnna/tessera", "68367bbdf53a", "golang-migrate", "tune"),
    ("flomation-co/api", "3656b219545c", "golang-migrate", "held out"),
    ("alexskatell/toplineosv2", "a8dcc8e49b2f", "golang-migrate", "tune"),
    ("tobi-techy/RAIL-BACKEND-SERVICE", "9c072033774e", "golang-migrate", "held out"),
    ("neutree-ai/neutree", "9b9212e3907a", "golang-migrate", "tune"),
    ("weave-os/router", "410f165e73f1", "golang-migrate", "held out"),
    ("parkerscobey/hizal", "4c35d59e72c4", "golang-migrate", "tune"),
    ("Eleuterio258/nexora", "cbceed1e5aa7", "golang-migrate", "held out"),
    ("Tesseract-Nexus/marketplace-services", "bf2b2f1c096b", "golang-migrate", "tune"),
    ("mhdna/kashi", "46073aaf93ec", "golang-migrate", "held out"),
    ("Liquidity-Agent/Trezia", "44bd2c641cb2", "golang-migrate", "tune"),
    ("Locazar/mandi-backend", "b3d6866ac99b", "golang-migrate", "held out"),
    ("VOD-Studio/violet", "29112b797054", "golang-migrate", "tune"),
    ("lucia117/embolsadora4.0-cloud", "e9780fc57742", "golang-migrate", "held out"),
]

# (repository, tool, half) -- the README's table of default branches, split the same way
REPOS = [
    ("saleor/saleor", "django", "tune"),
    ("wagtail/wagtail", "django", "held out"),
    ("zulip/zulip", "django", "tune"),
    ("netbox-community/netbox", "django", "held out"),
    ("mozilla/kitsune", "django", "tune"),
    ("django-oscar/django-oscar", "django", "held out"),
    ("pretix/pretix", "django", "tune"),
    ("healthchecks/healthchecks", "django", "held out"),
    ("paperless-ngx/paperless-ngx", "django", "tune"),
    ("django-cms/django-cms", "django", "held out"),
    ("readthedocs/readthedocs.org", "django", "tune"),
    ("HumanSignal/label-studio", "django", "held out"),
    ("ansible/awx", "django", "tune"),
    ("taigaio/taiga-back", "django", "held out"),
    ("mathesar-foundation/mathesar", "django", "tune"),
    ("inventree/InvenTree", "django", "held out"),
    ("makeplane/plane", "django", "tune"),
    ("pennersr/django-allauth", "django", "held out"),
    ("wger-project/wger", "django", "tune"),
    ("DefectDojo/django-DefectDojo", "django", "held out"),
    ("cvat-ai/cvat", "django", "tune"),
    ("goauthentik/authentik", "django", "held out"),
    ("django-helpdesk/django-helpdesk", "django", "tune"),
    ("OpenDroneMap/WebODM", "django", "held out"),
    ("evennia/evennia", "django", "tune"),
    ("nyaruka/rapidpro", "django", "held out"),
    ("archesproject/arches", "django", "tune"),
    ("jazzband/django-oauth-toolkit", "django", "held out"),
    ("getsentry/sentry", "django", "tune"),
    ("PostHog/posthog", "django", "held out"),
    ("mlflow/mlflow", "alembic", "tune"),
    ("apache/superset", "alembic", "held out"),
    ("getredash/redash", "alembic", "tune"),
    ("CTFd/CTFd", "alembic", "held out"),
    ("lnbits/lnbits", "alembic", "tune"),
    ("fastapi/full-stack-fastapi-template", "alembic", "held out"),
    ("open-webui/open-webui", "alembic", "tune"),
    ("PrefectHQ/prefect", "alembic", "held out"),
    ("langflow-ai/langflow", "alembic", "tune"),
    ("mealie-recipes/mealie", "alembic", "held out"),
    ("jupyterhub/jupyterhub", "alembic", "tune"),
    ("polarsource/polar", "alembic", "held out"),
    ("Netflix/dispatch", "alembic", "tune"),
    ("zenml-io/zenml", "alembic", "held out"),
    ("pgadmin-org/pgadmin4", "alembic", "tune"),
    ("freedomofpress/securedrop", "alembic", "held out"),
    ("apache/airflow", "alembic", "tune"),
    ("kestra-io/kestra", "flyway", "held out"),
    ("eclipse-hawkbit/hawkbit", "flyway", "tune"),
    ("cloudfoundry/uaa", "flyway", "held out"),
    ("spring-cloud/spring-cloud-dataflow", "flyway", "tune"),
    ("dhis2/dhis2-core", "flyway", "held out"),
    ("openremote/openremote", "flyway", "tune"),
    ("kitodo/kitodo-production", "flyway", "held out"),
    ("conductor-oss/conductor", "flyway", "tune"),
    ("hmcts/opal-fines-service", "flyway", "held out"),
    ("gchq/stroom", "flyway", "tune"),
    ("apache/fineract", "flyway", "held out"),
    ("DependencyTrack/hyades", "flyway", "tune"),
    ("ministryofjustice/hmpps-manage-users-api", "flyway", "held out"),
    ("ministryofjustice/hmpps-auth", "flyway", "tune"),
    ("mastodon/mastodon", "rails", "held out"),
    ("discourse/discourse", "rails", "tune"),
    ("forem/forem", "rails", "held out"),
    ("chatwoot/chatwoot", "rails", "tune"),
    ("solidusio/solidus", "rails", "held out"),
    ("spree/spree", "rails", "tune"),
    ("opf/openproject", "rails", "held out"),
    ("diaspora/diaspora", "rails", "tune"),
    ("lobsters/lobsters", "rails", "held out"),
    ("huginn/huginn", "rails", "tune"),
    ("redmine/redmine", "rails", "held out"),
    ("rubygems/rubygems.org", "rails", "tune"),
    ("zammad/zammad", "rails", "held out"),
    ("loomio/loomio", "rails", "tune"),
    ("consul/consul", "rails", "held out"),
    ("decidim/decidim", "rails", "tune"),
    ("alphagov/whitehall", "rails", "held out"),
    ("rubyforgood/human-essentials", "rails", "tune"),
    ("rubyforgood/casa", "rails", "held out"),
    ("codetriage/CodeTriage", "rails", "tune"),
    ("exercism/website", "rails", "held out"),
    ("maybe-finance/maybe", "rails", "tune"),
    ("danbooru/danbooru", "rails", "held out"),
    ("publiclab/plots2", "rails", "tune"),
    ("mattermost/mattermost", "golang-migrate", "held out"),
    ("ory/kratos", "golang-migrate", "tune"),
    ("ory/hydra", "golang-migrate", "held out"),
    ("ory/keto", "golang-migrate", "tune"),
    ("supabase/auth", "golang-migrate", "held out"),
    ("flipt-io/flipt", "golang-migrate", "tune"),
    ("goharbor/harbor", "golang-migrate", "held out"),
    ("stashapp/stash", "golang-migrate", "tune"),
    ("harness/harness", "golang-migrate", "held out"),
    ("golang-migrate/migrate", "golang-migrate", "tune"),
    ("jmoiron/sqlx", "golang-migrate", "held out"),
    ("cortezaproject/corteza", "golang-migrate", "tune"),
    ("hatchet-dev/hatchet", "golang-migrate", "held out"),
    ("rudderlabs/rudder-server", "golang-migrate", "tune"),
]
UA = {"User-Agent": "migration-collision-check-replay", "Accept": "application/vnd.github+json"}
CALLS = [0]
MAX_TAR = 400 * 1024 * 1024

KEEP = re.compile(r"(^|/)(apps\.py|env\.py|schema\.rb|pom\.xml|build\.gradle(\.kts)?|go\.mod|alembic\.ini|"
                  r"flyway[\w.-]*\.(conf|toml|properties)|application[\w-]*\.(properties|ya?ml))$")
KEEP_PY = re.compile(r"(^|/)[^/]*(migration|versions|alembic)[^/]*/")


def get(url):
    if "api.github.com" in url:
        CALLS[0] += 1
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
        return r.read()


def api(path):
    return json.loads(get("https://api.github.com" + path))


class Missing(Exception):
    pass


def tarball(repo, ref):
    """(paths, texts) at a ref from codeload's tarball, keeping in memory only the files the
    checker reads. Raises Missing when the ref does not exist."""
    url = "https://codeload.github.com/%s/tar.gz/%s" % (repo, urllib.parse.quote(ref, safe=""))
    paths, texts, seen = [], {}, [0]

    class Capped:
        def __init__(self, r):
            self.r = r

        def read(self, n=-1):
            b = self.r.read(n)
            seen[0] += len(b)
            if seen[0] > MAX_TAR:
                raise OverflowError("tarball larger than %d MB" % (MAX_TAR >> 20))
            return b
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=600) as r:
            with tarfile.open(fileobj=Capped(r), mode="r|gz") as tf:
                for m in tf:
                    if not m.isfile():
                        continue
                    name = m.name.split("/", 1)[1] if "/" in m.name else ""
                    if not name or set(name.split("/")[:-1]) & t.SKIP_DIRS:
                        continue
                    paths.append(name)
                    keep = KEEP.search(name) or (name.endswith((".py", ".mako")) and KEEP_PY.search(name))
                    if keep and m.size <= 2 * 1024 * 1024:
                        f = tf.extractfile(m)
                        texts[name] = f.read().decode("utf-8", "replace") if f else None
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise Missing(ref)
        raise
    return paths, texts


def tree_at(repo, ref):
    paths, texts = tarball(repo, ref)
    return t.Tree(paths, texts.get), (paths, texts)


def errors(fs):
    return [f for f in fs if t.LEVEL[f.code] == "error"]


def replay(repo, sha):
    after, raw_after = tree_at(repo, sha)
    before, raw_before = tree_at(repo, sha + "~1")
    fa, sa = t.check_tree(after)
    fb, sb = t.check_tree(before)
    ka = {f.key() for f in fa}
    kb = {f.key() for f in fb}
    rows = [("kept" if f.key() in ka else "fixed", f) for f in fb] + \
           [("new", f) for f in fa if f.key() not in kb]
    gate = None
    try:
        p2, raw_p2 = tree_at(repo, sha + "^2")
    except Missing:
        p2 = None
    if p2 is not None:
        f1 = errors(fb)
        f2 = errors(t.check_tree(p2)[0])
        (pa, ta), (pb, tb) = raw_before, raw_p2
        # the merge base, so that a file the second parent renamed or deleted is not kept
        q = lambda r: urllib.parse.quote(r, safe="")
        cmp_ = api("/repos/%s/compare/%s...%s" % (repo, q(sha + "^1"), q(sha + "^2")))
        split = tarball(repo, cmp_["merge_base_commit"]["sha"])[0]
        changed = {f["filename"] for f in cmp_.get("files", []) if f.get("status") == "modified"}
        merged = t.merged_tree(pa, ta.get, pb, tb.get, split, changed)
        fm, _ = t.check_tree(merged, order=True)
        gate = (len(f1), len(f2), [f for f in errors(fm) if t.brought_in(merged, f)])
    return rows, gate, (sb, sa)


def against(repo, sha, base):
    """What --base would have said about the commit's parent (the branch before the fix)
    merged into `base`: the errors the branch brings in. base "pr" means the base branch just
    before the pull request that carried the commit was merged (its merge commit's first parent)."""
    q = lambda r: urllib.parse.quote(r, safe="")
    if base == "pr":
        prs = [p for p in api("/repos/%s/commits/%s/pulls" % (repo, sha)) if p.get("merge_commit_sha")]
        if not prs:
            return None, []
        base = prs[0]["merge_commit_sha"] + "^1"
    cmp_ = api("/repos/%s/compare/%s...%s" % (repo, q(base), q(sha + "~1")))
    split_sha = cmp_["merge_base_commit"]["sha"]
    bp, bt = tarball(repo, base)
    hp, ht = tarball(repo, sha + "~1")
    split = tarball(repo, split_sha)[0]
    changed = {f["filename"] for f in cmp_.get("files", []) if f.get("status") == "modified"}
    merged = t.merged_tree(bp, bt.get, hp, ht.get, split, changed)
    fm, _ = t.check_tree(merged, order=True)
    return split_sha, [f for f in errors(fm) if t.brought_in(merged, f)]


def search(q):
    d = api("/search/commits?q=%s&per_page=50" % urllib.parse.quote(q))
    for it in d.get("items", []):
        msg = it["commit"]["message"].splitlines()[0][:90]
        print("%s@%s  %s" % (it["repository"]["full_name"], it["sha"][:12], msg))
    print("%d of %d shown" % (len(d.get("items", [])), d.get("total_count", 0)), file=sys.stderr)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("commits", nargs="*", help="owner/name@SHA")
    ap.add_argument("--head", action="append", default=[], help="owner/name: check the default branch")
    ap.add_argument("--repos", action="store_true", help="check the default branch of the README's 99 repositories")
    ap.add_argument("--half", choices=("tune", "held out"), help="only the commits or repositories of one half")
    ap.add_argument("--search", help="list candidate commits from GitHub's commit search")
    ap.add_argument("--against", metavar="REF",
                    help="with commits: also merge each commit's parent into REF, as --base would")
    a = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
    try:
        if a.search:
            search(a.search)
            return 0
        if a.repos:
            a.head += [r for r, _, h in REPOS if a.half in (None, h)]
        for repo in a.head:
            ref = "HEAD"                  # codeload serves the default branch under HEAD
            try:
                tr, _ = tree_at(repo, ref)
            except (OverflowError, Missing) as e:
                print("## %s @ %s  skipped (%s)" % (repo, ref, e))
                continue
            fs, st = t.check_tree(tr)
            print("## %s @ %s  %s" % (repo, ref, t.summary(st, len(errors(fs)), len(fs) - len(errors(fs)))))
            for f in fs:
                print("    %r" % f)
            for p in st["unread_paths"]:
                print("    not read: %s" % p)
        todo = [c.split("@", 1) for c in a.commits] or ([] if a.head or a.repos else [(r, s) for r, s, _, h in FIXES if a.half in (None, h)])
        total = {"fixed": 0, "kept": 0, "new": 0, "commits caught": 0, "gates": 0, "gates caught": 0}
        for repo, sha in todo:
            try:
                rows, gate, stats = replay(repo, sha)
            except (OverflowError, Missing) as e:
                print("%s@%s  skipped (%s)" % (repo, sha[:10], e))
                continue
            counts = {k: sum(1 for r in rows if r[0] == k) for k in ("fixed", "kept", "new")}
            for k in counts:
                total[k] += counts[k]
            caught = any(r[0] == "fixed" and t.LEVEL[r[1].code] == "error" for r in rows)
            g = ""
            if gate is not None:
                g = "  gate: parents alone %d and %d errors, together %d brought in" % (
                    gate[0], gate[1], len(gate[2]))
                if gate[0] == 0 and gate[1] == 0:       # the merge itself made the collision?
                    total["gates"] += 1
                    if gate[2]:
                        total["gates caught"] += 1
                if gate[2]:
                    caught = True
            total["commits caught"] += caught
            print("%s@%s  fixed %d  kept %d  new %d%s" % (repo, sha[:10], counts["fixed"],
                                                          counts["kept"], counts["new"], g))
            for kind, f in rows:
                print("    %-6s %r" % (kind, f))
            for f in (gate[2] if gate else []):
                print("    gate   %r" % f)
            if a.against:
                split_sha, got = against(repo, sha, a.against)
                if split_sha is None:
                    print("    against %s: no merged pull request carries this commit" % a.against)
                    continue
                print("    against %s (split at %s): %d error(s) the branch brings in"
                      % (a.against, split_sha[:10], len(got)))
                total["against caught"] = total.get("against caught", 0) + bool(got)
                for f in got:
                    print("    base   %r" % f)
        if todo:
            print("total: %d commits, %d caught (fixed or gate); fixed %d  kept %d  new %d; "
                  "merge commits whose parents were both clean %d, the merge flagged in %d" % (
                      len(todo), total["commits caught"], total["fixed"], total["kept"], total["new"],
                      total["gates"], total["gates caught"]))
    except urllib.error.HTTPError as e:
        if e.code in (403, 422, 429):
            print("stopped: GitHub refused (%d %s) after %d API calls." % (e.code, e.reason, CALLS[0]))
            return 2
        raise
    print("%d API calls" % CALLS[0], file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
