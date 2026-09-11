"""Runtime regression for epoch-bound OpenBuilder resources."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from captain.builder_resource_store import (  # noqa: E402
    ALLOWED_BUILDER_RESOURCE_TYPES,
    BuilderResource,
    EpochBoundBuilderResourceStore,
)
from captain.project_authority import AuthorityError, ProjectAuthority  # noqa: E402


def authority(
    *,
    chat_id: str = "chat-a",
    project_id: str = "project-a",
    repo_scope: str = "repo-a",
    state_epoch: int = 7,
) -> ProjectAuthority:
    return ProjectAuthority(chat_id, project_id, repo_scope, state_epoch)


def resource(kind: str, resource_id: str, owner: ProjectAuthority) -> BuilderResource:
    return BuilderResource(kind, resource_id, owner, {"safe": True})


def denied(fn) -> None:
    try:
        fn()
    except AuthorityError:
        return
    raise AssertionError("expected fail-closed AuthorityError")


def main() -> None:
    store = EpochBoundBuilderResourceStore()
    owner = authority()

    for index, kind in enumerate(sorted(ALLOWED_BUILDER_RESOURCE_TYPES)):
        item = resource(kind, f"{kind}-{index}", owner)
        store.put(item, actor=owner, current_epoch=7)
        assert store.get(item.resource_id, request=owner, current_epoch=7) == item
        assert store.get(
            item.resource_id,
            request=owner,
            current_epoch=7,
            resource_type=kind,
        ) == item

    assert len(store.list_readable(request=owner, current_epoch=7)) == len(
        ALLOWED_BUILDER_RESOURCE_TYPES
    )

    # Cross-wall resource discovery returns nothing rather than leaking metadata.
    for outsider in (
        authority(chat_id="chat-b"),
        authority(project_id="project-b"),
        authority(repo_scope="repo-b"),
    ):
        assert store.get("preview-4", request=outsider, current_epoch=7) is None
        assert store.list_readable(request=outsider, current_epoch=7) == []

    # Requesters must themselves be at the active Project State epoch.
    denied(lambda: store.get("preview-4", request=authority(state_epoch=6), current_epoch=7))
    denied(lambda: store.get("preview-4", request=authority(state_epoch=8), current_epoch=7))

    # Normal/partial authority can never access or create builder state.
    normal = ProjectAuthority()
    denied(lambda: store.get("preview-4", request=normal, current_epoch=7))
    denied(
        lambda: store.put(
            resource("preview", "normal-preview", owner),
            actor=normal,
            current_epoch=7,
        )
    )
    partial = ProjectAuthority("chat-a", "project-a", None, 7)
    denied(lambda: store.list_readable(request=partial, current_epoch=7))

    # Unknown kinds and type-confusion fail closed.
    denied(
        lambda: store.put(
            resource("future_unknown_kind", "unknown", owner),
            actor=owner,
            current_epoch=7,
        )
    )
    denied(
        lambda: store.get(
            "preview-4",
            request=owner,
            current_epoch=7,
            resource_type="future_unknown_kind",
        )
    )

    # Provider-local resource IDs are authority-scoped rather than globally unique.
    # Two unrelated projects may both legitimately have "preview-4" without either
    # blocking or overwriting the other.
    other_project = authority(project_id="project-b")
    store.put(
        BuilderResource("preview", "preview-4", other_project, {"project": "b"}),
        actor=other_project,
        current_epoch=7,
    )
    assert store.get("preview-4", request=owner, current_epoch=7).payload["safe"] is True
    assert (
        store.get("preview-4", request=other_project, current_epoch=7).payload["project"]
        == "b"
    )

    # Stored payloads are immutable snapshots. Post-write mutation of an adapter's
    # nested objects must not alter Captain-owned preview/session state.
    nested = {"files": [{"path": "src/app.ts", "status": "clean"}]}
    snap = BuilderResource("session", "mutable-session", owner, nested)
    store.put(snap, actor=owner, current_epoch=7)
    nested["files"][0]["status"] = "tampered"
    stored = store.get("mutable-session", request=owner, current_epoch=7)
    assert stored is not None
    assert stored.payload["files"][0]["status"] == "clean"
    try:
        stored.payload["files"] = ()
    except TypeError:
        pass
    else:
        raise AssertionError("stored builder payload must be read-only")

    class HostilePayload:
        def __deepcopy__(self, memo):
            raise AssertionError("custom deepcopy hooks must never execute")

    denied(
        lambda: store.put(
            BuilderResource("session", "hostile", owner, {"value": HostilePayload()}),
            actor=owner,
            current_epoch=7,
        )
    )
    denied(
        lambda: store.put(
            BuilderResource("session", "nan", owner, {"value": float("nan")}),
            actor=owner,
            current_epoch=7,
        )
    )

    # Epoch transition: the new epoch may reuse a provider-local ID immediately;
    # stale resources remain unreadable before cleanup and can then be reclaimed.
    next_owner = authority(state_epoch=8)
    store.put(
        BuilderResource("preview", "preview-4", next_owner, {"epoch": 8}),
        actor=next_owner,
        current_epoch=8,
    )
    denied(lambda: store.get("preview-4", request=owner, current_epoch=8))
    assert store.get("preview-4", request=next_owner, current_epoch=8).payload["epoch"] == 8

    other_epoch_project = authority(project_id="project-c", state_epoch=8)
    store.put(
        resource("preview", "other-preview", other_epoch_project),
        actor=other_epoch_project,
        current_epoch=8,
    )
    removed = store.revoke_epoch(authority=next_owner, current_epoch=8)
    assert removed == len(ALLOWED_BUILDER_RESOURCE_TYPES) + 1  # original set + mutable session
    assert store.get("preview-4", request=next_owner, current_epoch=8) is not None
    assert store.get("other-preview", request=other_epoch_project, current_epoch=8) is not None

    print("BUILDER_RESOURCE_RUNTIME_EPOCH_PASS")


if __name__ == "__main__":
    main()
