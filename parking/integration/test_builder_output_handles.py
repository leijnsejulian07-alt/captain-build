import hashlib, json, unittest
from builder_output_handles import BuilderOutputHandleStore, AccessDenied, HandleError

D=hashlib.sha256(b"artifact").hexdigest()

class T(unittest.TestCase):
    def setUp(self):
        self.s=BuilderOutputHandleStore(b"x"*32)
        self.kw=dict(kind="diff", chat_id="c1", project_id="p1", repo_scope="repoA",
                     epoch=7,builder_session_id="s1",revision=3,artifact_digest=D,now=100)

    def issue(self): return self.s.issue(**self.kw)

    def test_exact_scope_resolves(self):
        h=self.issue()
        r=self.s.resolve(h,expected_kind="diff",chat_id="c1",project_id="p1",repo_scope="repoA",
                         current_epoch=7,builder_session_id="s1",min_revision=3,now=101)
        self.assertEqual(r["artifact_digest"],D)

    def test_stale_epoch_denied(self):
        h=self.issue()
        with self.assertRaises(AccessDenied): self.s.resolve(h,expected_kind="diff",chat_id="c1",project_id="p1",repo_scope="repoA",current_epoch=8,builder_session_id="s1",now=101)

    def test_cross_session_denied(self):
        h=self.issue()
        with self.assertRaises(AccessDenied): self.s.resolve(h,expected_kind="diff",chat_id="c1",project_id="p1",repo_scope="repoA",current_epoch=7,builder_session_id="s2",now=101)

    def test_cross_project_repo_denied(self):
        h=self.issue()
        for p,r in [("p2","repoA"),("p1","repoB")]:
            with self.assertRaises(AccessDenied): self.s.resolve(h,expected_kind="diff",chat_id="c1",project_id=p,repo_scope=r,current_epoch=7,builder_session_id="s1",now=101)

    def test_wrong_kind_and_revision_denied(self):
        h=self.issue()
        with self.assertRaises(AccessDenied): self.s.resolve(h,expected_kind="file",chat_id="c1",project_id="p1",repo_scope="repoA",current_epoch=7,builder_session_id="s1",now=101)
        with self.assertRaises(AccessDenied): self.s.resolve(h,expected_kind="diff",chat_id="c1",project_id="p1",repo_scope="repoA",current_epoch=7,builder_session_id="s1",min_revision=4,now=101)

    def test_expiry_denied(self):
        h=self.issue()
        with self.assertRaises(AccessDenied): self.s.resolve(h,expected_kind="diff",chat_id="c1",project_id="p1",repo_scope="repoA",current_epoch=7,builder_session_id="s1",now=1001)

    def test_revocation(self):
        h=self.issue(); self.assertEqual(self.s.revoke_session("s1"),1)
        with self.assertRaises(AccessDenied): self.s.resolve(h,expected_kind="diff",chat_id="c1",project_id="p1",repo_scope="repoA",current_epoch=7,builder_session_id="s1",now=101)

    def test_export_has_no_raw_scope_or_body(self):
        self.issue()
        rows=json.loads(self.s.export_metadata())
        self.assertEqual(len(rows),1)
        row=rows[0]
        for forbidden_key in ["repo_scope","chat_id","project_id","builder_session_id","artifact_body","content","prompt"]:
            self.assertNotIn(forbidden_key,row)
        self.assertEqual(row["artifact_digest"],D)
        self.assertRegex(row["scope_digest"], r"^[0-9a-f]{64}$")
        self.assertRegex(row["builder_session_id_hash"], r"^[0-9a-f]{64}$")

    def test_pathlike_ids_fail_closed(self):
        with self.assertRaises(HandleError):
            self.s.issue(**{**self.kw,"builder_session_id":"../s1"})

if __name__=="__main__": unittest.main()
