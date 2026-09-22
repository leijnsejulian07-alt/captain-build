import unittest
from plugin_capability_grants import *

class Grants(unittest.TestCase):
    def setUp(self):
        self.a=Scope("chat-a","project-a","C:/repo/a")
        self.b=Scope("chat-b","project-a","C:/repo/a")
        self.c=Scope("chat-a","project-b","C:/repo/a")
        self.d=Scope("chat-a","project-a","C:/repo/b")
        self.g=issue_grant("github","repo:write",self.a)
    def test_exact_scope(self): self.assertTrue(permits(self.g,"github","repo:write",self.a))
    def test_cross_chat_denied(self): self.assertFalse(permits(self.g,"github","repo:write",self.b))
    def test_cross_project_denied(self): self.assertFalse(permits(self.g,"github","repo:write",self.c))
    def test_cross_repo_denied(self): self.assertFalse(permits(self.g,"github","repo:write",self.d))
    def test_capability_escalation_denied(self): self.assertFalse(permits(self.g,"github","connector:use",self.a))
    def test_plugin_substitution_denied(self): self.assertFalse(permits(self.g,"builder","repo:write",self.a))
    def test_unknown_capability_rejected(self):
        with self.assertRaises(ValueError): issue_grant("github","shell:any",self.a)
    def test_pathlike_plugin_rejected(self):
        with self.assertRaises(ValueError): issue_grant("../github","repo:read",self.a)
    def test_public_state_has_no_raw_scope(self):
        out=public_grant(self.g); text=str(out)
        self.assertNotIn("chat-a",text); self.assertNotIn("project-a",text); self.assertNotIn("C:/repo/a",text)

if __name__ == "__main__": unittest.main()
