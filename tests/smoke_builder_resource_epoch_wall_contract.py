"""Fail-closed OpenBuilder resource ownership contract.

This is a fallback acceptance contract only. It does not claim the live Captain
implementation is integrated until reconciled and run against the local workspace.
"""

from dataclasses import dataclass

from project_scope_contract import Scope


ALLOWED_RESOURCE_TYPES = {
    "session",
    "preview",
    "console",
    "diff",
    "rollback",
    "builder_context",
    "builder_update",
}


@dataclass(frozen=True)
class BuilderOwner:
    chat_id: str
    scope: Scope

    def validate(self) -> None:
        if not isinstance(self.chat_id, str) or not self.chat_id.strip():
            raise ValueError("builder owner requires chat_id")
        self.scope.validate()
        if self.scope.is_normal:
            raise ValueError("builder resources require complete project scope")


@dataclass(frozen=True)
class BuilderResource:
    resource_type: str
    resource_id: str
    owner: BuilderOwner

    def validate(self) -> None:
        if self.resource_type not in ALLOWED_RESOURCE_TYPES:
            raise ValueError("unknown builder resource type must fail closed")
        if not isinstance(self.resource_id, str) or not self.resource_id.strip():
            raise ValueError("builder resource requires resource_id")
        self.owner.validate()


def can_access(resource: BuilderResource, requester: BuilderOwner) -> bool:
    try:
        resource.validate()
        requester.validate()
    except ValueError:
        return False
    return resource.owner == requester


def project_owner(
    *,
    chat_id: str = "chat-a",
    project_id: str = "project-a",
    repo_scope: str = "repo-a",
    state_epoch: int = 7,
) -> BuilderOwner:
    return BuilderOwner(
        chat_id=chat_id,
        scope=Scope(
            project_id=project_id,
            repo_scope=repo_scope,
            state_epoch=state_epoch,
        ),
    )


def resource(resource_type: str = "preview") -> BuilderResource:
    return BuilderResource(
        resource_type=resource_type,
        resource_id=f"{resource_type}-1",
        owner=project_owner(),
    )


def assert_denied(target: BuilderResource, requester: BuilderOwner) -> None:
    assert can_access(target, requester) is False


def main() -> None:
    for resource_type in sorted(ALLOWED_RESOURCE_TYPES):
        target = resource(resource_type)
        assert can_access(target, project_owner()) is True

        # Stale/new epochs are both inaccessible: access is exact-epoch bound.
        assert_denied(target, project_owner(state_epoch=6))
        assert_denied(target, project_owner(state_epoch=8))

        # Cross-wall access must fail closed independently for every dimension.
        assert_denied(target, project_owner(chat_id="chat-b"))
        assert_denied(target, project_owner(project_id="project-b"))
        assert_denied(target, project_owner(repo_scope="repo-b"))

    # Invalid/partial/normal scopes cannot own builder resources.
    invalid_requesters = (
        BuilderOwner(chat_id="", scope=Scope("project-a", "repo-a", 7)),
        BuilderOwner(chat_id="chat-a", scope=Scope()),
        BuilderOwner(chat_id="chat-a", scope=Scope("project-a", None, 7)),
        BuilderOwner(chat_id="chat-a", scope=Scope("project-a", "repo-a", None)),
        BuilderOwner(chat_id="chat-a", scope=Scope("project-a", "repo-a", -1)),
    )
    target = resource()
    for requester in invalid_requesters:
        assert_denied(target, requester)

    # Unknown resource kinds fail closed instead of silently inheriting access.
    unknown = BuilderResource(
        resource_type="future_unregistered_resource",
        resource_id="x",
        owner=project_owner(),
    )
    assert_denied(unknown, project_owner())

    # Normal non-project chat remains valid in the shared Scope contract, while
    # being intentionally unable to access project-bound builder resources.
    normal_scope = Scope()
    normal_scope.validate()
    assert normal_scope.is_normal_chat is True
    assert_denied(target, BuilderOwner(chat_id="chat-normal", scope=normal_scope))


if __name__ == "__main__":
    main()
