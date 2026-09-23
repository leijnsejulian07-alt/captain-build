"""Regressions for deterministic, authority-local memory cardinality."""
from memory_authority import MemoryAuthority, MemoryAuthorityError
from memory_cardinality_policy import apply_write, MAX_RECORDS_PER_AUTHORITY
from memory_store_epoch_adapter import MemoryRecord

H1 = "1" * 64
H2 = "2" * 64

def auth(chat="c", project="p", repo=H1, epoch=1):
    return MemoryAuthority.parse({"chat_id": chat, "project_id": project,
                                  "repo_scope_hash": repo, "state_epoch": epoch})

def rec(a, key, value):
    return MemoryRecord(a, key, value, {"source": "captain", "kind": "derived"})

def run():
    a = auth(); other = auth(project="other", repo=H2, epoch=9)
    records = (rec(a, "decision", 1), rec(other, "keep", "other-project"))
    updated = apply_write(records, rec(a, "decision", 2))
    assert len(updated) == 2
    assert updated[0].value == 2
    assert updated[1] is records[1]

    # New keys append only inside the owning authority; unrelated records survive.
    updated = apply_write(updated, rec(a, "new", 3))
    assert [r.key for r in updated] == ["decision", "keep", "new"]

    # A full authority rejects growth rather than evicting or touching another project.
    full = tuple(rec(a, f"k{i}", i) for i in range(MAX_RECORDS_PER_AUTHORITY))
    sentinel = rec(other, "sentinel", 1)
    try:
        apply_write(full + (sentinel,), rec(a, "overflow", 1))
    except MemoryAuthorityError:
        pass
    else:
        raise AssertionError("full project-memory authority accepted overflow")
    assert sentinel.key == "sentinel"

    # Replacement remains possible at the cap, so bounded storage does not deadlock updates.
    replaced = apply_write(full, rec(a, "k0", "latest"))
    assert len(replaced) == MAX_RECORDS_PER_AUTHORITY
    assert replaced[0].value == "latest"
    print("PASS: project-memory cardinality is bounded, deterministic and authority-local")

if __name__ == "__main__":
    run()
