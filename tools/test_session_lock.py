# -*- coding: utf-8 -*-
"""session_lock.py の検査(標準ライブラリのみ)。python tools/test_session_lock.py"""
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import session_lock as L  # noqa: E402


class LockTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "SESSION.lock")

    def tearDown(self):
        if os.path.exists(self.path):
            os.remove(self.path)
        os.rmdir(self.dir)

    def test_acquire_then_second_is_blocked(self):
        rc, _, tok = L.acquire(4, "first", self.path)
        self.assertEqual(rc, 0)
        self.assertTrue(tok)
        rc2, msg2, tok2 = L.acquire(4, "second", self.path)
        self.assertEqual(rc2, 3)
        self.assertIsNone(tok2)
        self.assertIn("先行あり", msg2)
        self.assertEqual(L.status(4, self.path)[0], 3)

    def test_release_only_by_owner(self):
        rc, _, tok = L.acquire(4, "a", self.path)
        self.assertEqual(L.release("wrong", self.path)[0], 4)
        self.assertTrue(os.path.exists(self.path))
        self.assertEqual(L.release(tok, self.path)[0], 0)
        self.assertFalse(os.path.exists(self.path))
        self.assertEqual(L.status(4, self.path)[0], 0)

    def test_stale_lock_is_taken_over(self):
        rc, _, tok = L.acquire(4, "old", self.path)
        old = time.time() - 5 * 3600
        os.utime(self.path, (old, old))
        self.assertEqual(L.status(4, self.path)[0], 0)
        rc2, msg2, tok2 = L.acquire(4, "new", self.path)
        self.assertEqual(rc2, 0)
        self.assertIn("乗っ取った", msg2)
        self.assertNotEqual(tok, tok2)

    def test_heartbeat_refreshes_mtime(self):
        rc, _, tok = L.acquire(4, "a", self.path)
        old = time.time() - 3 * 3600
        os.utime(self.path, (old, old))
        self.assertEqual(L.heartbeat("wrong", self.path)[0], 4)
        self.assertEqual(L.heartbeat(tok, self.path)[0], 0)
        self.assertLess(time.time() - os.path.getmtime(self.path), 60)

    def test_broken_lock_is_overwritten(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("not json")
        self.assertEqual(L.status(4, self.path)[0], 0)
        rc, msg, tok = L.acquire(4, "x", self.path)
        self.assertEqual(rc, 0)
        self.assertIn("壊れた錠", msg)


if __name__ == "__main__":
    unittest.main(verbosity=1)
