"""Regression: builder resources are scoped by type as well as ProjectAuthority."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from captain.builder_resource_store import BuilderResource, EpochBoundBuilderResourceStore  # noqa: E402
from captain.project_authority import AuthorityError, ProjectAuthority  # noqa: E402


def denied(fn) -> None:
    try:
        fn()
    except AuthorityError:
        return
    raise AssertionError("expected fail-closed AuthorityError")


def main() -> None:
    owner = ProjectAuthority("chat-a", "project-a", "repo-a", 12)
    store = EpochBoundBuilderResourceStore()

    # Providers often use small local IDs. A session and preview named "1" must
    # coexist rather than silently overwriting each other.
    session = BuilderResource("session", "1", owner, {"kind": "session"})
    preview = BuilderResource("preview", "1", owner, {"kind": "preview"})
    store.put(session, actor=owner, current_epoch=12)
    store.put(preview, actor=owner, current_epoch=12)

    got_session = store.get("1", request=owner, current_epoch=12, resource_type="session")
    got_preview = store.get("1", request=owner, current_epoch=12, resource_type="preview")
    assert got_session is not None and got_session.payload["kind"] == "session"
    assert got_preview is not None and got_preview.payload["kind"] == "preview"
    assert len(store.list_readable(request=owner, current_epoch=12)) == 2

    # Untyped lookup is safe only when unique. Ambiguity must fail closed so a
    # caller can never receive the wrong capability-bearing resource by accident.
    denied(lambda: store.get("1", request=owner, current_epoch=12))

    unique = BuilderResource("diff", "unique", owner, {"kind": "diff"})
    store.put(unique, actor=owner, current_epoch=12)
    assert store.get("unique", request=owner, current_epoch=12) is not None

    # Type separation does not weaken the existing epoch wall.
    stale = ProjectAuthority("chat-a", "project-a", "repo-a", 11)
    denied(lambda: store.get("1", request=stale, current_epoch=12, resource_type="session"))

    print("BUILDER_RESOURCE_TYPE_IDENTITY_PASS")


if __name__ == "__main__":
    main()
