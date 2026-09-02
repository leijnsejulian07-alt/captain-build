import hashlib
import unittest

from research_provenance_contract import (
    assert_evidence_access,
    bind_claim_evidence,
    issue_evidence,
    validate_evidence,
)


class ResearchProvenanceContractTests(unittest.TestCase):
    def setUp(self):
        self.claim = hashlib.sha256(b"claim").hexdigest()
        self.content = hashlib.sha256(b"source body").hexdigest()
        self.base = dict(
            evidence_id="ev_1",
            chat_id="chat_1",
            project_id="project_1",
            repo_scope="C:/Captain/repos/project-one",
            claim_digest=self.claim,
            source_url="HTTPS://Example.COM/report#section-2",
            source_kind="primary",
            stance="supports",
            content_digest=self.content,
            retrieved_at="2026-09-02T10:00:00Z",
            observed_at="2026-09-02T11:00:00Z",
        )

    def evidence(self, **overrides):
        args = dict(self.base)
        args.update(overrides)
        return issue_evidence(**args)

    def test_round_trip_is_secret_free_and_canonical(self):
        row = self.evidence()
        self.assertEqual(row["source_url"], "https://example.com/report")
        self.assertNotIn("chat_1", repr(row))
        self.assertNotIn("project_1", repr(row))
        self.assertNotIn("C:/Captain", repr(row))
        self.assertEqual(validate_evidence(row), row)

    def test_cross_chat_project_and_repo_access_fail_closed(self):
        row = self.evidence()
        for kwargs in (
            dict(chat_id="chat_2", project_id="project_1", repo_scope=self.base["repo_scope"]),
            dict(chat_id="chat_1", project_id="project_2", repo_scope=self.base["repo_scope"]),
            dict(chat_id="chat_1", project_id="project_1", repo_scope="C:/Captain/repos/project-two"),
        ):
            with self.assertRaises(ValueError):
                assert_evidence_access(row, **kwargs)

    def test_url_credentials_and_non_http_sources_are_rejected(self):
        with self.assertRaises(ValueError):
            self.evidence(source_url="https://user:secret@example.com/report")
        with self.assertRaises(ValueError):
            self.evidence(source_url="file:///etc/passwd")

    def test_future_and_unboundedly_old_evidence_are_rejected(self):
        with self.assertRaises(ValueError):
            self.evidence(retrieved_at="2026-09-02T12:00:00Z", observed_at="2026-09-02T11:00:00Z")
        with self.assertRaises(ValueError):
            self.evidence(retrieved_at="2024-01-01T00:00:00Z", observed_at="2026-09-02T11:00:00Z")

    def test_unknown_fields_and_tampering_fail_closed(self):
        row = self.evidence()
        row["snippet"] = "do not persist raw source text"
        with self.assertRaises(ValueError):
            validate_evidence(row)

    def test_claim_binding_rejects_foreign_claim(self):
        row = self.evidence(claim_digest=hashlib.sha256(b"other").hexdigest())
        with self.assertRaises(ValueError):
            bind_claim_evidence(
                claim_digest=self.claim,
                records=[row],
                chat_id="chat_1",
                project_id="project_1",
                repo_scope=self.base["repo_scope"],
            )

    def test_duplicate_source_version_is_rejected(self):
        one = self.evidence(evidence_id="ev_1")
        two = self.evidence(evidence_id="ev_2")
        with self.assertRaises(ValueError):
            bind_claim_evidence(
                claim_digest=self.claim,
                records=[one, two],
                chat_id="chat_1",
                project_id="project_1",
                repo_scope=self.base["repo_scope"],
            )

    def test_support_and_contradiction_are_preserved(self):
        support = self.evidence(evidence_id="ev_support")
        contradict = self.evidence(
            evidence_id="ev_contra",
            source_url="https://example.org/correction",
            content_digest=hashlib.sha256(b"correction").hexdigest(),
            stance="contradicts",
        )
        bound = bind_claim_evidence(
            claim_digest=self.claim,
            records=[support, contradict],
            chat_id="chat_1",
            project_id="project_1",
            repo_scope=self.base["repo_scope"],
        )
        self.assertTrue(bound["has_support"])
        self.assertTrue(bound["has_contradiction"])
        self.assertEqual(bound["evidence_count"], 2)

    def test_naive_timestamps_fail_closed(self):
        with self.assertRaises(ValueError):
            self.evidence(retrieved_at="2026-09-02T10:00:00")


if __name__ == "__main__":
    unittest.main()
