"""Provider-free acceptance contract for Captain Project Memory/context epoch isolation."""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Scope:
    project_id: Optional[str] = None
    repo_scope: Optional[str] = None
    state_epoch: Optional[int] = None

    def normal(self):
        return self.project_id is None and self.repo_scope is None and self.state_epoch is None

    def validate(self):
        if self.normal():
            return
        if not (self.project_id and self.repo_scope and isinstance(self.state_epoch, int) and self.state_epoch >= 0):
            raise ValueError("invalid partial project scope")


@dataclass(frozen=True)
class Record:
    record_id: str
    scope: Scope
    generic: bool = False
    project_specific: bool = False


def readable(record, request_scope):
    request_scope.validate()
    record.scope.validate()
    if request_scope.normal():
        return record.scope.normal() or (record.generic and not record.project_specific)
    return record.scope == request_scope


def test_normal_context():
    assert readable(Record("normal", Scope()), Scope())


def test_partial_scope_denied():
    for scope in (
        Scope(project_id="a"),
        Scope(repo_scope="r"),
        Scope(state_epoch=1),
        Scope(project_id="a", repo_scope="r"),
    ):
        try:
            scope.validate()
        except ValueError:
            continue
        raise AssertionError("partial scope accepted")


def test_project_and_repo_isolation():
    a = Scope("a", "repo/one", 3)
    other_project = Scope("b", "repo/one", 3)
    other_repo = Scope("a", "repo/two", 3)
    record = Record("m", a)
    assert readable(record, a)
    assert not readable(record, other_project)
    assert not readable(record, other_repo)


def test_stale_epoch_revoked():
    old = Scope("a", "repo/one", 3)
    current = Scope("a", "repo/one", 4)
    record = Record("m", old)
    assert readable(record, old)
    assert not readable(record, current)


def test_project_context_not_visible_to_normal_chat():
    assert not readable(Record("m", Scope("a", "repo/one", 1)), Scope())


def test_only_explicit_generic_distillation_can_cross_scope():
    project = Scope("a", "repo/one", 1)
    assert readable(Record("safe", project, generic=True, project_specific=False), Scope())
    assert not readable(Record("raw", project, generic=False, project_specific=False), Scope())
    assert not readable(Record("specific", project, generic=True, project_specific=True), Scope())


if __name__ == "__main__":
    test_normal_context()
    test_partial_scope_denied()
    test_project_and_repo_isolation()
    test_stale_epoch_revoked()
    test_project_context_not_visible_to_normal_chat()
    test_only_explicit_generic_distillation_can_cross_scope()
    print("MEMORY_CONTEXT_EPOCH_SCOPE_CONTRACT_PASS")
