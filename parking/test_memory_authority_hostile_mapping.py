"""Regression: Project State authority parsing must not execute hostile Mapping hooks."""
from collections.abc import Mapping

from memory_authority import MemoryAuthority, MemoryAuthorityError, project_memory_visible

H = "1" * 64
BASE = {"chat_id": "chat-a", "project_id": "project-a", "repo_scope_hash": H, "state_epoch": 1}


class HostileMapping(Mapping):
    touched = False

    def __iter__(self):
        type(self).touched = True
        raise RuntimeError("hostile iterator executed")

    def __len__(self):
        return 4

    def __getitem__(self, key):
        type(self).touched = True
        raise RuntimeError("hostile getter executed")


def run():
    hostile = HostileMapping()
    try:
        MemoryAuthority.parse(hostile)
    except MemoryAuthorityError:
        pass
    except RuntimeError as exc:
        raise AssertionError("authority parser executed caller Mapping hooks") from exc
    else:
        raise AssertionError("hostile Mapping unexpectedly accepted")
    assert HostileMapping.touched is False
    assert project_memory_visible(hostile, BASE) is False
    assert HostileMapping.touched is False
    print("PASS: authority boundary rejects non-dict mappings without executing hooks")


if __name__ == "__main__":
    run()
