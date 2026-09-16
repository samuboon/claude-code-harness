# -*- coding: utf-8 -*-
"""Tests for key_expiry.py. Standard library only: `python test_key_expiry.py`.

Every test here was watched failing once, by breaking the line it guards, before it was
kept. The breakages are listed in mutation_check.py, which re-runs them on demand.

The fixtures are built rather than pasted. A certificate is assembled tag by tag so the
DER walk is exercised against the real shape - optional version tag, an issuer SEQUENCE
that must not be mistaken for Validity - and the tokens are encoded at run time so that
a substring scanner pointed at this repository does not report its own test corpus.
"""
import base64
import contextlib
import io
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import key_expiry as ke  # noqa: E402

NOW = "2026-01-01T00:00:00+00:00"


# ------------------------------------------------------------------- fixtures
def tlv(tag, body):
    if len(body) < 0x80:
        return bytes([tag, len(body)]) + body
    n = len(body).to_bytes((len(body).bit_length() + 7) // 8, "big")
    return bytes([tag, 0x80 | len(n)]) + n + body


OID_SHA256_RSA = tlv(0x30, tlv(0x06, b"\x2a\x86\x48\x86\xf7\x0d\x01\x01\x0b"))
NAME = tlv(0x30, tlv(0x31, tlv(0x30, tlv(0x06, b"\x55\x04\x03") + tlv(0x0c, b"example"))))


def make_cert(not_before=b"250101000000Z", not_after=b"260401000000Z",
              tag=ke.UTC_TIME, with_version=True, padding=0):
    """A structurally faithful certificate: the fields Validity sits behind are real."""
    tbs = b""
    if with_version:
        tbs += tlv(0xA0, tlv(0x02, b"\x02"))               # [0] EXPLICIT version v3
    tbs += tlv(0x02, b"\x01\x23")                          # serialNumber
    tbs += OID_SHA256_RSA                                  # signature (SEQUENCE of OID)
    tbs += NAME                                            # issuer   (SEQUENCE of SETs)
    tbs += tlv(0x30, tlv(tag, not_before) + tlv(tag, not_after))
    tbs += NAME                                            # subject
    if padding:
        tbs += tlv(0x04, b"\x00" * padding)                # make the body long enough
    return tlv(0x30, tlv(0x30, tbs) + OID_SHA256_RSA + tlv(0x03, b"\x00\xde\xad"))


def pem(der):
    b = base64.b64encode(der).decode("ascii")
    lines = "\n".join(b[i:i + 64] for i in range(0, len(b), 64))
    return "-----BEGIN CERTIFICATE-----\n" + lines + "\n-----END CERTIFICATE-----\n"


def make_jwt(claims, header=None):
    def seg(obj):
        raw = json.dumps(obj, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).rstrip(b"=")
    head = seg(header if header is not None else {"alg": "HS256", "typ": "JWT"})
    return head + b"." + seg(claims) + b"." + base64.urlsafe_b64encode(b"nosignature").rstrip(b"=")


EXP_2026_02_01 = 1769904000     # 2026-02-01T00:00:00Z


class Der(unittest.TestCase):
    def test_short_form_length(self):
        tag, body, nxt = ke.der_read(tlv(0x04, b"abc"), 0)
        self.assertEqual((0x04, b"abc", 5), (tag, body, nxt))

    def test_long_form_one_byte_length(self):
        _, body, _ = ke.der_read(tlv(0x04, b"x" * 200), 0)
        self.assertEqual(200, len(body))

    def test_long_form_two_byte_length(self):
        _, body, _ = ke.der_read(tlv(0x04, b"x" * 400), 0)
        self.assertEqual(400, len(body))

    def test_indefinite_length_is_refused(self):
        # 0x80 is "indefinite": legal in BER, forbidden in DER, and read as length 0
        # by a parser that only masks off the high bit.
        with self.assertRaises(ValueError):
            ke.der_read(b"\x30\x80\x00\x00", 0)

    def test_truncated_value_is_refused(self):
        with self.assertRaises(ValueError):
            ke.der_read(b"\x04\x10ab", 0)

    def test_truncated_header_is_refused(self):
        with self.assertRaises(ValueError):
            ke.der_read(b"\x04", 0)


class Times(unittest.TestCase):
    def test_utctime_two_digit_year_below_fifty_is_twenty_first_century(self):
        self.assertEqual(2026, ke.der_time(ke.UTC_TIME, b"260401000000Z").year)

    def test_utctime_two_digit_year_from_fifty_is_twentieth_century(self):
        # RFC 5280 5.1.2.4. A certificate with notAfter 1950 is expired, not due in 2050.
        self.assertEqual(1950, ke.der_time(ke.UTC_TIME, b"500401000000Z").year)

    def test_utctime_without_seconds(self):
        self.assertEqual(datetime(2026, 4, 1, 12, 30, tzinfo=timezone.utc),
                         ke.der_time(ke.UTC_TIME, b"2604011230Z"))

    def test_generalized_time_four_digit_year(self):
        self.assertEqual(2126, ke.der_time(ke.GEN_TIME, b"21260401000000Z").year)

    def test_non_utc_time_is_refused_and_named_as_such(self):
        # This asserts the wording, unusually, because the wording is the only thing the
        # UTC check changes: every non-Z time we could construct is the wrong *length*
        # too, so the digit test below refuses it either way. The check earns its place
        # by saying which of your certificates could not be read, and why.
        with self.assertRaisesRegex(ValueError, "not UTC"):
            ke.der_time(ke.UTC_TIME, b"260401000000+0900")

    def test_non_numeric_time_is_refused(self):
        with self.assertRaises(ValueError):
            ke.der_time(ke.UTC_TIME, b"26April0000Z")


class Certificates(unittest.TestCase):
    def test_not_after_of_a_v3_certificate(self):
        self.assertEqual(datetime(2026, 4, 1, tzinfo=timezone.utc),
                         ke.cert_not_after(make_cert()))

    def test_it_takes_not_after_and_not_not_before(self):
        when = ke.cert_not_after(make_cert(b"200101000000Z", b"270601000000Z"))
        self.assertEqual(2027, when.year)

    def test_v1_certificate_without_the_optional_version_tag(self):
        self.assertEqual(2026, ke.cert_not_after(make_cert(with_version=False)).year)

    def test_generalized_time_certificate(self):
        der = make_cert(b"20250101000000Z", b"21260401000000Z", tag=ke.GEN_TIME)
        self.assertEqual(2126, ke.cert_not_after(der).year)

    def test_long_form_lengths_inside_the_certificate(self):
        self.assertEqual(2026, ke.cert_not_after(make_cert(padding=500)).year)

    def test_a_certificate_without_validity_is_refused(self):
        tbs = tlv(0x02, b"\x01") + OID_SHA256_RSA + NAME
        der = tlv(0x30, tlv(0x30, tbs) + OID_SHA256_RSA)
        with self.assertRaises(ValueError):
            ke.cert_not_after(der)

    def test_not_a_certificate_is_refused(self):
        with self.assertRaises(ValueError):
            ke.cert_not_after(tlv(0x04, b"hello"))


class Jwts(unittest.TestCase):
    def test_exp_claim(self):
        self.assertEqual(datetime(2026, 2, 1, tzinfo=timezone.utc),
                         ke.jwt_expiry(make_jwt({"exp": EXP_2026_02_01})))

    def test_float_exp_is_accepted(self):
        self.assertEqual(2026, ke.jwt_expiry(make_jwt({"exp": EXP_2026_02_01 + 0.5})).year)

    def test_without_exp_is_refused(self):
        with self.assertRaises(ValueError):
            ke.jwt_expiry(make_jwt({"sub": "someone"}))

    def test_string_exp_is_refused(self):
        with self.assertRaises(ValueError):
            ke.jwt_expiry(make_jwt({"exp": "2026-02-01"}))

    def test_boolean_exp_is_refused(self):
        # bool is a subclass of int in Python; `"exp": true` must not become 1970.
        with self.assertRaises(ValueError):
            ke.jwt_expiry(make_jwt({"exp": True}))

    def test_header_without_alg_is_refused(self):
        # `eyJ` is only base64 for `{"`. Any JSON object encoded that way looks like one.
        with self.assertRaises(ValueError):
            ke.jwt_expiry(make_jwt({"exp": EXP_2026_02_01}, header={"note": "not jose"}))

    def test_two_segments_is_refused(self):
        with self.assertRaises(ValueError):
            ke.jwt_expiry(make_jwt({"exp": EXP_2026_02_01}).rsplit(b".", 1)[0])

    def test_base64url_padding(self):
        for n in range(1, 6):
            raw = b"x" * n
            self.assertEqual(raw, ke.b64url(base64.urlsafe_b64encode(raw).rstrip(b"=")))


class Scanning(unittest.TestCase):
    def test_finds_both_kinds_in_one_blob(self):
        data = b"header\n" + pem(make_cert()).encode() + b"\n" + make_jwt({"exp": EXP_2026_02_01})
        kinds = sorted(k for _l, k, _w, _n in ke.scan_bytes(data))
        self.assertEqual(["jwt", "x509"], kinds)

    def test_line_number_is_the_line_the_credential_starts_on(self):
        data = b"a\nb\nc\n" + make_jwt({"exp": EXP_2026_02_01})
        self.assertEqual(4, ke.scan_bytes(data)[0][0])

    def test_utf16le_token_is_found(self):
        data = make_jwt({"exp": EXP_2026_02_01}).decode("ascii").encode("utf-16-le")
        found = ke.scan_bytes(data)
        self.assertEqual(1, len(found))
        self.assertIn("utf-16le", found[0][3])

    def test_the_same_credential_is_not_counted_twice_across_views(self):
        # A file that is part ASCII and part UTF-16LE yields the ASCII match in both views.
        data = make_jwt({"exp": EXP_2026_02_01}) + b"\x00\x00tail"
        self.assertEqual(1, len(ke.scan_bytes(data)))

    def test_ordinary_base64_is_not_reported(self):
        data = base64.urlsafe_b64encode(b'{"note":"plain text, no header"}') + b".AAAAAAAA.BBBB"
        self.assertEqual([], ke.scan_bytes(data))

    def test_two_certificates_in_one_file_are_two_findings(self):
        # Against a bundle, a greedy PEM pattern matches from the first BEGIN to the
        # last END and decodes to nothing, so a full trust store reports as clean.
        data = (pem(make_cert(not_after=b"260401000000Z"))
                + pem(make_cert(not_after=b"270401000000Z"))).encode()
        found = ke.scan_bytes(data)
        self.assertEqual(2, len(found))
        self.assertEqual([2026, 2027], sorted(w.year for _l, _k, w, _n in found))

    def test_a_corrupt_certificate_block_is_skipped_not_crashed(self):
        self.assertEqual([], ke.scan_bytes(b"-----BEGIN CERTIFICATE-----\nAAAA\n-----END CERTIFICATE-----"))


class Days(unittest.TestCase):
    def test_expired_is_negative(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.assertEqual(-31, ke.days_left(datetime(2025, 12, 1, tzinfo=timezone.utc), now))

    def test_future_is_positive(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.assertEqual(90, ke.days_left(datetime(2026, 4, 1, tzinfo=timezone.utc), now))


class Cli(unittest.TestCase):
    def _run(self, args):
        buf = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
            code = ke.main(args)
        return code, buf.getvalue(), err.getvalue()

    def _tree(self, d, exp=EXP_2026_02_01):
        (Path(d) / "token.env").write_bytes(b"TOKEN=" + make_jwt({"exp": exp}))
        (Path(d) / "server.pem").write_text(pem(make_cert()), encoding="utf-8")
        return d

    def test_due_inside_the_window_exits_one(self):
        with tempfile.TemporaryDirectory() as d:
            code, out, _ = self._run([self._tree(d), "--now", NOW, "--within", "60"])
        self.assertEqual(1, code)
        self.assertIn("token.env", out)

    def test_the_window_is_inclusive_at_its_edge(self):
        # The JWT in the fixture has exactly 31 days left. "--within 31" must catch it;
        # off-by-one here is a credential that expires on the morning nobody was warned.
        with tempfile.TemporaryDirectory() as d:
            self._tree(d)
            self.assertEqual(1, self._run([d, "--now", NOW, "--within", "31"])[0])
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(0, self._run([self._tree(d), "--now", NOW, "--within", "30"])[0])

    def test_nothing_due_exits_zero(self):
        with tempfile.TemporaryDirectory() as d:
            code, _out, _ = self._run([self._tree(d), "--now", NOW, "--within", "5"])
        self.assertEqual(0, code)

    def test_already_expired_counts_as_due(self):
        with tempfile.TemporaryDirectory() as d:
            self._tree(d, exp=1704067200)        # 2024-01-01
            code, out, _ = self._run([d, "--now", NOW, "--within", "0"])
        self.assertEqual(1, code)
        self.assertIn("\t-731\t", out)

    def test_a_tree_with_no_files_exits_two(self):
        with tempfile.TemporaryDirectory() as d:
            code, _out, err = self._run([d, "--now", NOW])
        self.assertEqual(2, code)
        self.assertIn("not a clean result", err)

    def test_a_missing_path_exits_two(self):
        code, _out, err = self._run(["no-such-directory-here", "--now", NOW])
        self.assertEqual(2, code)
        self.assertIn("no such path", err)

    def test_no_path_exits_two(self):
        code, _out, err = self._run(["--now", NOW])
        self.assertEqual(2, code)
        self.assertIn("nothing was scanned", err)

    def test_output_never_contains_the_credential(self):
        with tempfile.TemporaryDirectory() as d:
            token = make_jwt({"exp": EXP_2026_02_01}).decode("ascii")
            (Path(d) / "token.env").write_text("TOKEN=" + token, encoding="utf-8")
            for fmt in ("tsv", "paste", "github"):
                _code, out, err = self._run([d, "--now", NOW, "--within", "60", "--format", fmt])
                self.assertNotIn(token, out + err, fmt)
                self.assertNotIn(token[:24], out + err, fmt)

    def test_paste_format_names_no_path(self):
        with tempfile.TemporaryDirectory() as d:
            code, out, _ = self._run([self._tree(d), "--now", NOW, "--within", "60",
                                      "--format", "paste"])
        self.assertEqual(1, code)
        self.assertNotIn("token.env", out)
        self.assertNotIn("server.pem", out)
        self.assertIn("jwt\t31", out)

    def test_github_format_emits_an_annotation(self):
        with tempfile.TemporaryDirectory() as d:
            code, out, _ = self._run([self._tree(d), "--now", NOW, "--within", "60",
                                      "--format", "github"])
        self.assertEqual(1, code)
        self.assertIn("::warning file=token.env,line=1::", out)

    def test_github_format_lists_only_what_is_due(self):
        with tempfile.TemporaryDirectory() as d:
            code, out, _ = self._run([self._tree(d), "--now", NOW, "--within", "35",
                                      "--format", "github"])
        self.assertEqual(1, code)
        self.assertIn("token.env", out)          # 31 days
        self.assertNotIn("server.pem", out)      # 90 days

    def test_skipped_directories_are_not_scanned(self):
        with tempfile.TemporaryDirectory() as d:
            junk = Path(d) / "__pycache__"
            junk.mkdir()
            (junk / "x.pyc").write_bytes(make_jwt({"exp": EXP_2026_02_01}))
            (Path(d) / "plain.txt").write_text("nothing here", encoding="utf-8")
            code, out, _ = self._run([d, "--now", NOW, "--within", "60"])
        self.assertEqual(0, code)
        self.assertNotIn("x.pyc", out)

    def test_a_single_file_target(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "token.env"
            p.write_bytes(make_jwt({"exp": EXP_2026_02_01}))
            code, out, _ = self._run([str(p), "--now", NOW, "--within", "60"])
        self.assertEqual(1, code)
        self.assertIn("token.env", out)

    def test_an_oversized_file_is_skipped_and_said_so(self):
        with tempfile.TemporaryDirectory() as d:
            big = Path(d) / "big.bin"
            big.write_bytes(b"\x00" * (ke.MAX_BYTES + 1))
            (Path(d) / "plain.txt").write_text("nothing", encoding="utf-8")
            code, _out, err = self._run([d, "--now", NOW])
        self.assertEqual(0, code)
        self.assertIn("1 skipped", err)


if __name__ == "__main__":
    unittest.main(verbosity=2)
