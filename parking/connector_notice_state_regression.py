"""Dependency-free regression for persistent connector remediation notices."""
from connector_notice_state import (
    MAX_EVENTS_PER_NOTICE, MAX_EVENT_CHARS, MAX_NOTICES, NoticeStore,
)


def health(cid="github.main", events=("auth_expired",), important=True):
    return {"connector_id": cid, "events": events, "important": important,
            "settings_deep_link": f"settings://connectors/{cid}"}


def rejects(fn):
    try:
        fn()
    except (TypeError, ValueError):
        return
    raise AssertionError("expected fail-closed rejection")


s = NoticeStore()
s.reconcile(health())
assert len(s.visible(now=100, launch_id=1)) == 1
s.dismiss("github.main", now=100, launch_id=1, snooze_seconds=3600)
assert s.visible(now=101, launch_id=1) == ()
assert len(s.visible(now=3700, launch_id=1)) == 1
assert len(s.visible(now=101, launch_id=2)) == 1

s.dismiss("github.main", now=4000, launch_id=2, snooze_seconds=100)
s.reconcile(health())
assert s.visible(now=4050, launch_id=2) == ()
s.reconcile(health(events=("provider_deprecated",)))
assert s.visible(now=4050, launch_id=2)[0].events == ("provider_deprecated",)
s.reconcile(health(events=(), important=False))
assert s.visible(now=4050, launch_id=2) == ()
assert s.snapshot() == ()

s.reconcile(health("safe", ("auth_expired",), True))
before = s.snapshot()
rejects(lambda: s.reconcile({"connector_id": "safe", "events": ["auth_expired"],
                             "important": True, "settings_deep_link": "settings://connectors/safe"}))
rejects(lambda: s.reconcile({"connector_id": "safe", "events": ("auth_expired",),
                             "important": True, "settings_deep_link": "https://evil.invalid"}))
rejects(lambda: s.reconcile(health("safe", ("x" * (MAX_EVENT_CHARS + 1),))))
rejects(lambda: s.reconcile(health("safe", tuple(str(i) for i in range(MAX_EVENTS_PER_NOTICE + 1)))))
rejects(lambda: s.reconcile(health("safe", ("duplicate", "duplicate"))))
assert s.snapshot() == before

class HostileInt(int):
    def __lt__(self, other):
        raise AssertionError("hostile comparison executed")

rejects(lambda: s.visible(now=HostileInt(1), launch_id=3))
rejects(lambda: s.dismiss("safe", now=1, launch_id=3, snooze_seconds=999999))
assert s.snapshot() == before

row = s.snapshot()[0]
assert set(row) == {"connector_id", "events", "settings_deep_link", "dismissed_until", "dismissed_launch"}

s.dismiss("safe", now=5000, launch_id=4, snooze_seconds=60)
snap = s.snapshot()
r = NoticeStore.from_snapshot(snap)
assert r.snapshot() == snap
assert r.visible(now=5001, launch_id=4) == ()
assert len(r.visible(now=5001, launch_id=5)) == 1
snap[0]["events"] = ("tampered",)
assert r.snapshot()[0]["events"] == ("auth_expired",)

base = r.snapshot()[0]
rejects(lambda: NoticeStore.from_snapshot([base]))
rejects(lambda: NoticeStore.from_snapshot((base, base)))
extra = dict(base); extra["secret"] = "must-not-load"
rejects(lambda: NoticeStore.from_snapshot((extra,)))
partial = dict(base); partial["dismissed_launch"] = None
rejects(lambda: NoticeStore.from_snapshot((partial,)))
badlink = dict(base); badlink["settings_deep_link"] = "https://evil.invalid"
rejects(lambda: NoticeStore.from_snapshot((badlink,)))
long_event = dict(base); long_event["events"] = ("x" * (MAX_EVENT_CHARS + 1),)
rejects(lambda: NoticeStore.from_snapshot((long_event,)))

# Runtime reconciliation is bounded too; persistence limits cannot be bypassed before snapshot.
capacity = NoticeStore()
for i in range(MAX_NOTICES):
    capacity.reconcile(health(f"c{i}"))
full = capacity.snapshot()
rejects(lambda: capacity.reconcile(health("overflow")))
assert capacity.snapshot() == full
# Existing notices can still be updated/resolved at capacity.
capacity.reconcile(health("c0", ("provider_deprecated",)))
capacity.reconcile(health("c1", (), False))
assert len(capacity.snapshot()) == MAX_NOTICES - 1
capacity.reconcile(health("replacement"))
assert len(capacity.snapshot()) == MAX_NOTICES

print("connector notice state regression: PASS")
