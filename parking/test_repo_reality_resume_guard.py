"""Regression for repo_reality_resume_guard. Pure local-data tests only."""
from copy import deepcopy
from repo_reality_resume_guard import resume_delta_usable, MAX_CHANGED_PATHS


def fixture():
    scope = {"chat_id":"chat-a","project_id":"project-a","repo_scope":"repo-a","builder_session_id":"session-a","state_epoch":7}
    saved = {
        "version":1,
        "scope":deepcopy(scope),
        "observed":{"head":"abcdef1","base":"1234567","generated_at":"2026-09-24T01:00:00Z"},
        "delta":{"changed_paths":["src/app.py"],"manifest_hashes":{"package.json":"a"*64},"symbol_delta":["src/app.py:App"]},
        "freshness":{"scope_match":True,"epoch_match":True,"head_match":True,"usable":True},
    }
    return saved, {**scope,"head":"abcdef1"}


def reject(mutator):
    saved,current=fixture(); mutator(saved,current); assert not resume_delta_usable(saved,current)


def test_owner_and_walls():
    saved,current=fixture(); assert resume_delta_usable(saved,current)
    for wall in ("chat_id","project_id","repo_scope","builder_session_id"):
        reject(lambda s,c,w=wall: c.__setitem__(w,c[w]+"-other"))
    reject(lambda s,c: c.__setitem__("state_epoch",8))
    reject(lambda s,c: c.__setitem__("head","fedcba9"))


def test_bounded_and_paths():
    reject(lambda s,c: s["delta"].__setitem__("changed_paths",["x"]*(MAX_CHANGED_PATHS+1)))
    for p in ("../secret","/etc/passwd","src\\x.py","C:/x","src//x","./src/x"):
        reject(lambda s,c,p=p: s["delta"].__setitem__("changed_paths",[p]))
    reject(lambda s,c: s["delta"].__setitem__("manifest_hashes",{"package.json":"bad"}))


def test_hostile_containers_and_scalars_are_inert():
    touched=[]
    class EvilDict(dict):
        def get(self,*a,**k): touched.append("get"); raise AssertionError("hook")
    class EvilStr(str):
        def __eq__(self,other): touched.append("eq"); raise AssertionError("hook")
        def __hash__(self): touched.append("hash"); raise AssertionError("hook")
    saved,current=fixture(); assert not resume_delta_usable(EvilDict(saved),current); assert touched == []
    saved,current=fixture(); saved["scope"]["project_id"]=EvilStr("project-a"); assert not resume_delta_usable(saved,current); assert touched == []


def test_shape_and_freshness_fail_closed():
    reject(lambda s,c: s["scope"].__setitem__("extra","x"))
    reject(lambda s,c: s["freshness"].__setitem__("usable",False))
    reject(lambda s,c: s["freshness"].__setitem__("extra",True))
    reject(lambda s,c: s.__setitem__("version",2))


if __name__ == "__main__":
    test_owner_and_walls(); test_bounded_and_paths(); test_hostile_containers_and_scalars_are_inert(); test_shape_and_freshness_fail_closed(); print("REPO_REALITY_RESUME_GUARD_OK")
