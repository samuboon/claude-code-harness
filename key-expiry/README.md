**日本語版: [README.ja.md](README.ja.md)**

# key-expiry — ten of the forty-eight root certificates this machine trusts had already expired

Run this first. It reads the trust store your operating system already has, and nothing else:

```bash
python key-expiry/trust_store_demo.py
```

On the machine this repository is built on, 2026-09-16:

```
48 certificates in the Windows ROOT store, read on 2026-09-16
  already expired : 10  (oldest by 9757 days)
  expiring in 90  : 0
  unreadable here : 0
  soonest still valid: 119 days
```

**An expired root is not a hole in your machine** — a certificate past `notAfter` simply cannot validate anything, and stores keep old roots around on purpose. The finding is narrower and worse than a security problem: **those dates were sitting in plain text the whole time, on your disk, and nobody had read them.** That is the only thing this tool does.

---

## What it reads

Exactly two kinds of credential carry their own death date inside them:

| Kind | Where the date is | Read offline? |
|---|---|---|
| **JSON Web Token** | the `exp` claim in the payload | yes |
| **X.509 certificate** (PEM) | `notAfter` in the Validity field | yes |
| an opaque token — a GitHub personal access token, an AWS access key | **nowhere. It is not in the token.** | **no. Nothing offline can date it** |

The third row is the honest part, and it is why this page does not claim to tell you when your credentials expire. It tells you when *two* kinds of them expire, and says nothing about the rest — because there is nothing to say without asking the issuer over the network, which this tool does not do.

```bash
python key-expiry/key_expiry.py .                      # the whole tree
python key-expiry/key_expiry.py ~/.kube --within 60     # a wider window
python key-expiry/key_expiry.py . --format paste        # day counts only
```

```
path                     line  kind   expires               days_left  note
config/agent.token       1     jwt    2026-02-01T00:00:00Z  31         219 bytes
certs/internal.pem       1     x509   2026-04-01T00:00:00Z  90         1436 bytes
```

**Exit codes**: `0` nothing expires inside the window · `1` something does, or already has · `2` **the scan did not happen** — no path, or zero files read. A mistyped path must not print a green check over an unscanned tree; that rule is inherited from [`leak-scan/`](../leak-scan/), which is in this repository for the same reason.

## `--format paste` — why the output has a mode with no file names in it

The reason people do not compare these numbers is not that they do not care. It is that the natural output of any expiry scanner is **a list of paths on your machine**, and nobody pastes their directory layout into a public issue.

```
# key-expiry 0.1.0: 48 credential(s) carry a date, 29 expire within 3650 days
x509	-9757
x509	-524
x509	119
```

Kinds and day counts. No paths, no file names, no host names, and — in every format — **never the credential itself**. One of the fifty tests asserts that the token does not appear in stdout or stderr in any of the three formats, because a scanner that echoes the secret into a CI log has moved the leak rather than found it.

**If you run it, paste that block into [the issue template for it](https://github.com/samuboon/claude-code-harness/issues/new?template=expiry-report.yml).** (Until 2026-09-17 this sentence only said a template existed; nothing in the tree linked to it.) What we want to know is the shape of the distribution — how many people are carrying something already expired without knowing — and one machine's trust store is not a distribution.

## What it will not catch, including the thing that actually stopped us

**This tool would not have caught our own incident.** On 2026-09-15 a push from this repository failed:

```
refusing to allow a Personal Access Token to create or update workflow
.github/workflows/leak-scan.yml without workflow scope
```

That token was not expired. It was **missing a permission** — and a permission is not a date, is not stored in the token, and cannot be read offline at all. We found out the way everyone finds out: the job stopped. The workflow definition in this repository still lives at [`leak-scan/example-workflow.yml`](../leak-scan/example-workflow.yml) rather than under `.github/`, as the scar.

So: a scanner for *dates* covers the subset of credential failures that announce themselves in advance. Scope, revocation, rotation, a key the provider disabled — none of them are in here. If you want the whole class, you need the issuing API, an account, and a network call, which is a different tool with a different threat model.

Also not covered: DER certificates that are not wrapped in PEM · PKCS#12 / JKS keystores · SSH certificates · Kerberos tickets · anything inside an encrypted file · the certificate a remote host is currently serving (that needs a connection). Files over 8 MB are skipped and counted as skipped rather than silently passed.

## Checks

| What | Number |
|---|---:|
| Tests (`python key-expiry/test_key_expiry.py`) | **50** |
| Deliberate breakages the tests must catch (`python key-expiry/mutation_check.py`) | **16 of 16** |
| Real certificates parsed and cross-checked against OpenSSL's own `notAfter` | **48 of 48 agreed** |
| Time to scan a 74 KB bundle of 48 real certificates | **2.2 ms** |
| Dependencies | **0** |

The cross-check matters more than the test count. The test fixtures are certificates assembled tag by tag in `test_key_expiry.py`, and a hand-built fixture shares whatever misconception the parser has. So the parser was also run against every certificate in this machine's trust store, with `ssl`'s own decoder as the oracle: **48 of 48 matched to the second.**

**And run on this repository, it reports nothing at all** (`0 dated credential(s)`, 69 files). That is correct — there are no credentials here — and it is the least useful demonstration possible, which is why this page opens with the trust store instead.

The mutation list is worth reading before you trust the number: it includes reporting `notBefore` instead of `notAfter`, reading every two-digit year as `20xx` (RFC 5280 says `50`–`99` is `19xx`, so a 1998 certificate would report as due in 2098), accepting BER's indefinite length form, and letting `"exp": true` date to 1970. One of the sixteen, M5, only changes an error *message*; the list says so rather than counting it as a catch it is not.

## Use it in CI

[`example-workflow.yml`](example-workflow.yml) fails a build when anything in the tree expires within 30 days. Copy it to `.github/workflows/`. It lives here rather than there for the reason in the scar above.

## License

MIT, with the rest of this repository. **No warranty.** It has one machine's worth of real-world corpus.
