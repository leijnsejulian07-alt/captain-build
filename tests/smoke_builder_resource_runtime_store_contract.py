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

    # Resource IDs cannot be overwritten by another project/repo/chat/epoch.
    denied(
        lambda: store.put(
            resource("preview", "preview-4", authority(project_id="project-b")),
            actor=authority(project_id="project-b"),
            current_epoch=7,
        )
    )

    # Epoch transition: stale resources are inaccessible before cleanup, and the
    # active epoch can remove old resources without touching another project.
    other = authority(project_id="project-b", state_epoch=8)
    store.put(resource("preview", "other-preview", other), actor=other, current_epoch=8)
    next_owner = authority(state_epoch=8)
    denied(lambda: store.get("preview-4", request=owner, current_epoch=8))
    assert store.get("preview-4", request=next_owner, current_epoch=8) is None
    removed = store.revoke_epoch(authority=next_owner, current_epoch=8)
    assert removed == len(ALLOWED_BUILDER_RESOURCE_TYPES)
    assert store.get("other-preview", request=other, current_epoch=8) is not None

    print("BUILDER_RESOURCE_RUNTIME_EPOCH_PASS")


if __name__ == "__main__":
    main()
