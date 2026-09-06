"""Provider-free acceptance contract for Captain Project Memory/context epoch isolation."""

from dataclasses import dataclass

from project_scope_contract import Scope


@dataclass(frozen=True)
class Record:
    record_id: str
    scope: Scope
    generic: bool = False
    project_specific: bool = False


def readable(record, request_scope):
    request_scope.validate()
    record.scope.validate()

    # Raw project memory never crosses an ownership wall. Shared learning must
    # first be distilled into explicitly global, non-project-specific state.
    if request_scope.normal():
        return record.scope.normal()

    if record.scope.normal():
        return record.generic and not record.project_specific

    return record.scope == request_scope


def test_normal_context():
    assert readable(Record("normal", Scope()), Scope())


def test_partial_and_malformed_scope_denied():
    for scope in (
        Scope(project_id="a"),
        Scope(repo_scope="r"),
        Scope(state_epoch=1),
        Scope(project_id="a", repo_scope="r"),
        Scope(" ", "repo/one", 1),
        Scope("a", " ", 1),
        Scope("a", "repo/one", True),
        Scope("a", "repo/one", False),
        Scope("a", "repo/one", -1),
    ):
        try:
            scope.validate()
        except ValueError:
            continue
        raise AssertionError(f"invalid scope accepted: {scope!r}")


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


def test_shared_learning_requires_global_distillation():
    project = Scope("a", "repo/one", 1)

    # Merely marking raw project memory generic is insufficient.
    assert not readable(
        Record("unsafe-raw", project, generic=True, project_specific=False),
        Scope(),
    )

    # Explicitly global distilled learning may be consumed inside a project.
    assert readable(
        Record("safe-global", Scope(), generic=True, project_specific=False),
        project,
    )
    assert not readable(
        Record("specific-global", Scope(), generic=True, project_specific=True),
        project,
    )


if __name__ == "__main__":
    test_normal_context()
    test_partial_and_malformed_scope_denied()
    test_project_and_repo_isolation()
    test_stale_epoch_revoked()
    test_project_context_not_visible_to_normal_chat()
    test_shared_learning_requires_global_distillation()
    print("MEMORY_CONTEXT_EPOCH_SCOPE_HARDENED_PASS")
