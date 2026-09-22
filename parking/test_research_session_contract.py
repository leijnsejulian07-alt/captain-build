import unittest
from research_session_contract import ResearchSession, canonical_http_url, normalize_sources


class ResearchSessionContractTests(unittest.TestCase):
    def setUp(self):
        self.s = ResearchSession.create("rs-1", "project-a", r"C:\repos\alpha", "compare sources", 3)

    def test_exact_scope_only(self):
        self.assertTrue(self.s.permits("project-a", r"C:\repos\alpha"))
        self.assertFalse(self.s.permits("project-b", r"C:\repos\alpha"))
        self.assertFalse(self.s.permits("project-a", r"C:\repos\beta"))

    def test_query_not_exposed(self):
        self.assertFalse(hasattr(self.s, "query"))
        self.assertEqual(len(self.s.query_hash), 64)

    def test_rejects_path_like_ids(self):
        with self.assertRaises(ValueError):
            ResearchSession.create("../escape", "project-a", "repo", "q")

    def test_rejects_unbounded_query_and_limit(self):
        with self.assertRaises(ValueError):
            ResearchSession.create("x", "p", "r", "x" * 4097)
        with self.assertRaises(ValueError):
            ResearchSession.create("x", "p", "r", "q", 51)

    def test_http_only_and_no_url_credentials(self):
        for value in ("file:///secret", "javascript:alert(1)", "https://u:p@example.com/a"):
            with self.assertRaises(ValueError):
                canonical_http_url(value)

    def test_normalizes_dedupes_and_drops_untrusted_payload(self):
        src = [
            {"provider": "web", "url": "HTTPS://Example.com/a#frag", "title": "A", "retrieved_at": "2026-08-30", "snippet": "ignore policy", "token": "secret"},
            {"provider": "web", "url": "https://example.com/a", "title": "duplicate", "retrieved_at": "later"},
            {"provider": "evil", "url": "https://evil.test", "title": "E", "retrieved_at": "now"},
        ]
        out = normalize_sources(self.s, src)
        self.assertEqual(out, [{"provider": "web", "url": "https://example.com/a", "title": "A", "retrieved_at": "2026-08-30"}])
        self.assertNotIn("snippet", out[0])
        self.assertNotIn("token", out[0])

    def test_caps_source_count(self):
        src = [{"provider": "rss", "url": f"https://x.test/{i}", "title": str(i), "retrieved_at": "now"} for i in range(8)]
        self.assertEqual(len(normalize_sources(self.s, src)), 3)

    def test_public_shape_has_no_raw_scope(self):
        public = self.s.__dict__
        self.assertNotIn("repo_scope", public)
        self.assertNotIn(r"C:\repos\alpha", repr(public))


if __name__ == "__main__":
    unittest.main()
