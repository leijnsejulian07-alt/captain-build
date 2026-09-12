from pathlib import Path
import sys

import pytest

FALLBACK = Path(__file__).resolve().parents[1]
for subdir in ("Memory", "Research", "Sandbox"):
    path = str(FALLBACK / subdir)
    if path not in sys.path:
        sys.path.insert(0, path)

from project_memory_epoch import assert_memory_access, build_memory
from provenance_gate import Authority, ProvenanceError, authorize_reuse, create_receipt
from builder_pane_snapshot import assert_builder_pane_access, project_builder_pane
from openbuilder_execution_flow import OpenBuilderExecution
from sandbox_session_policy import create_sandbox_lease

AUTH = dict(chat_id="chat-a", project_id="project-a", repo_scope="repo-a", state_epoch=7)


def _research_authority(authority):
    return Authority(
        chat_id=authority["chat_id"],
        project_id=authority["project_id"],
        repo_scope=authority["repo_scope"],
        state_epoch=str(authority["state_epoch"]),
    )


def _project_artifacts():
    memory = build_memory(
        memory_id="memory-a",
        kind="project_context",
        payload={"summary": "safe project context"},
        **AUTH,
    )
    research_authority = _research_authority(AUTH)
    evidence = create_receipt(
        authority=research_authority,
        evidence_id="evidence-a",
        source_url="https://example.com/source?tracking=removed#fragment",
        source_text="verified source text",
        claim_text="supported claim",
        retrieved_at="2026-09-12T11:00:00Z",
        source_kind="web",
    )
    lease = create_sandbox_lease(
        session_id="sandbox-a",
        backend="local-test",
        **AUTH,
    )
    execution = OpenBuilderExecution(lease=lease)
    pane = project_builder_pane(execution, **AUTH)
    return memory, evidence, pane


def test_same_project_state_epoch_authorizes_all_project_subsystems():
    memory, evidence, pane = _project_artifacts()

    assert_memory_access(memory, **AUTH)
    assert authorize_reuse(evidence, _research_authority(AUTH)) is evidence
    assert_builder_pane_access(pane, **AUTH)


def test_epoch_rotation_revokes_memory_research_and_builder_together():
    memory, evidence, pane = _project_artifacts()
    rotated = {**AUTH, "state_epoch": AUTH["state_epoch"] + 1}

    with pytest.raises(PermissionError):
        assert_memory_access(memory, **rotated)
    with pytest.raises(ProvenanceError):
        authorize_reuse(evidence, _research_authority(rotated))
    with pytest.raises(PermissionError):
        assert_builder_pane_access(pane, **rotated)


def test_foreign_project_or_repo_cannot_reuse_any_project_artifact():
    memory, evidence, pane = _project_artifacts()

    for foreign in (
        {**AUTH, "project_id": "project-b"},
        {**AUTH, "repo_scope": "repo-b"},
        {**AUTH, "chat_id": "chat-b"},
    ):
        with pytest.raises(PermissionError):
            assert_memory_access(memory, **foreign)
        with pytest.raises(ProvenanceError):
            authorize_reuse(evidence, _research_authority(foreign))
        with pytest.raises(PermissionError):
            assert_builder_pane_access(pane, **foreign)


def test_normal_chat_context_survives_project_epoch_rotation_without_project_authority():
    chat_memory = build_memory(
        memory_id="chat-memory-a",
        kind="chat_context",
        payload={"summary": "ordinary conversation context"},
        chat_id=AUTH["chat_id"],
    )

    assert_memory_access(chat_memory, chat_id=AUTH["chat_id"])

    with pytest.raises(PermissionError):
        assert_memory_access(
            chat_memory,
            chat_id=AUTH["chat_id"],
            project_id=AUTH["project_id"],
            repo_scope=AUTH["repo_scope"],
            state_epoch=AUTH["state_epoch"] + 1,
        )
