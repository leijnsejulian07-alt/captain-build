import pytest

from provenance_gate import (
    Authority,
    EvidenceReceipt,
    ProvenanceError,
    authorize_reuse,
    create_receipt,
    minimize_url,
    public_receipt,
)


def authority(epoch="epoch-7", project="project-a", chat="chat-a", repo="repo-a"):
    return Authority(chat, project, repo, epoch)


def receipt(auth=None):
    return create_receipt(
        authority=auth or authority(),
        evidence_id="evidence-1",
        source_url="https://Example.com/docs/page?utm_source=x#part",
        source_text="source material",
        claim_text="supported claim",
        retrieved_at="2026-09-12T08:57:00Z",
        source_kind="official_docs",
    )


def test_url_is_minimized_and_hashes_replace_raw_text():
    auth = authority()
    item = receipt(auth)
    assert item.source_url == "https://example.com/docs/page"
    projection = public_receipt(item, auth)
    serialized = repr(projection)
    assert "source material" not in serialized
    assert "supported claim" not in serialized
    assert "utm_source" not in serialized
    assert "#part" not in serialized


@pytest.mark.parametrize(
    "other",
    [
        authority(epoch="epoch-8"),
        authority(project="project-b"),
        authority(chat="chat-b"),
        authority(repo="repo-b"),
    ],
)
def test_reuse_is_fail_closed_across_scope_and_epoch(other):
    with pytest.raises(ProvenanceError):
        authorize_reuse(receipt(), other)


def test_same_evidence_id_in_another_project_does_not_grant_access():
    a = receipt(authority(project="project-a"))
    b = receipt(authority(project="project-b"))
    assert a.evidence_id == b.evidence_id
    assert a.authority_digest != b.authority_digest
    with pytest.raises(ProvenanceError):
        authorize_reuse(a, authority(project="project-b"))


def test_secret_like_url_and_multiline_ids_are_rejected():
    with pytest.raises(ProvenanceError):
        minimize_url("https://example.com/a?access_token=secret")
    with pytest.raises(ProvenanceError):
        create_receipt(
            authority=authority(),
            evidence_id="bad\nid",
            source_url="https://example.com/",
            source_text="x",
            claim_text="y",
            retrieved_at="2026-09-12T08:57:00Z",
        )


def test_tampered_receipt_digest_and_hashes_are_rejected():
    auth = authority()
    item = receipt(auth)
    tampered_scope = EvidenceReceipt(
        evidence_id=item.evidence_id,
        authority_digest="0" * 64,
        source_url=item.source_url,
        source_hash=item.source_hash,
        claim_hash=item.claim_hash,
        retrieved_at=item.retrieved_at,
        source_kind=item.source_kind,
    )
    with pytest.raises(ProvenanceError):
        authorize_reuse(tampered_scope, auth)

    tampered_hash = EvidenceReceipt(
        evidence_id=item.evidence_id,
        authority_digest=item.authority_digest,
        source_url=item.source_url,
        source_hash="abc",
        claim_hash=item.claim_hash,
        retrieved_at=item.retrieved_at,
        source_kind=item.source_kind,
    )
    with pytest.raises(ProvenanceError):
        authorize_reuse(tampered_hash, auth)


def test_missing_authority_and_unknown_source_kind_are_rejected():
    with pytest.raises(ProvenanceError):
        receipt(Authority("", "project-a", "repo-a", "epoch-7"))
    with pytest.raises(ProvenanceError):
        create_receipt(
            authority=authority(),
            evidence_id="evidence-2",
            source_url="https://example.com/",
            source_text="x",
            claim_text="y",
            retrieved_at="2026-09-12T08:57:00Z",
            source_kind="mystery",
        )
