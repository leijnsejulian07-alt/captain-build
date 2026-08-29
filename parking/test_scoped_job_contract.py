import unittest
from scoped_job_contract import ScopeError, make_scope, validate_job, validate_result

class ScopedJobContractTests(unittest.TestCase):
    def setUp(self):
        self.scope = make_scope("chat-1", "project-1", r"C:\repos\alpha")

    def job(self, **updates):
        value = {"job_id":"job-1", "kind":"build", "chat_id":"chat-1", "project_id":"project-1", "repo_scope":r"C:\repos\alpha"}
        value.update(updates)
        return value

    def test_accepts_exact_scope(self):
        self.assertEqual(validate_job(self.job(), self.scope)["scope"], self.scope)

    def test_rejects_cross_chat(self):
        with self.assertRaises(ScopeError): validate_job(self.job(chat_id="chat-2"), self.scope)

    def test_rejects_cross_project(self):
        with self.assertRaises(ScopeError): validate_job(self.job(project_id="project-2"), self.scope)

    def test_rejects_cross_repo(self):
        with self.assertRaises(ScopeError): validate_job(self.job(repo_scope=r"C:\repos\beta"), self.scope)

    def test_rejects_unknown_kind(self):
        with self.assertRaises(ScopeError): validate_job(self.job(kind="shell-anything"), self.scope)

    def test_rejects_pathlike_id(self):
        with self.assertRaises(ScopeError): validate_job(self.job(job_id="../escape"), self.scope)

    def test_result_must_match_job(self):
        job = validate_job(self.job(), self.scope)
        with self.assertRaises(ScopeError): validate_result(job, {"job_id":"other"}, self.scope)

    def test_result_cannot_override_scope(self):
        job = validate_job(self.job(), self.scope)
        out = validate_result(job, {"job_id":"job-1", "project_id":"evil", "repo_scope":"evil", "status":"ok"}, self.scope)
        self.assertEqual(out["scope"], self.scope)
        self.assertNotIn("project_id", out)

if __name__ == "__main__": unittest.main()
