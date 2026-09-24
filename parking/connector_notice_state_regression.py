"""Dependency-free regression for persistent connector remediation notices."""
from connector_notice_state import NoticeStore


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

# Temporary dismissal hides only during the same launch/reminder window.
s.dismiss("github.main", now=100, launch_id=1, snooze_seconds=3600)
assert s.visible(now=101, launch_id=1) == ()
assert len(s.visible(now=3700, launch_id=1)) == 1
assert len(s.visible(now=101, launch_id=2)) == 1

# Same unresolved problem may be reconciled without losing the snooze.
s.dismiss("github.main", now=4000, launch_id=2, snooze_seconds=100)
s.reconcile(health())
assert s.visible(now=4050, launch_id=2) == ()

# A changed important problem is immediately visible.
s.reconcile(health(events=("provider_deprecated",)))
assert s.visible(now=4050, launch_id=2)[0].events == ("provider_deprecated",)

# Resolution clears the notice automatically.
s.reconcile(health(events=(), important=False))
assert s.visible(now=4050, launch_id=2) == ()
assert s.snapshot() == ()

# Malformed/hostile health output fails before mutating existing state.
s.reconcile(health("safe", ("auth_expired",), True))
before = s.snapshot()
rejects(lambda: s.reconcile({"connector_id": "safe", "events": ["auth_expired"],
                             "important": True, "settings_deep_link": "settings://connectors/safe"}))
rejects(lambda: s.reconcile({"connector_id": "safe", "events": ("auth_expired",),
                             "important": True, "settings_deep_link": "https://evil.invalid"}))
assert s.snapshot() == before

class HostileInt(int):
    def __lt__(self, other):
        raise AssertionError("hostile comparison executed")

rejects(lambda: s.visible(now=HostileInt(1), launch_id=3))
rejects(lambda: s.dismiss("safe", now=1, launch_id=3, snooze_seconds=999999))
assert s.snapshot() == before

# Persistence representation contains codes/IDs/deep links only, never diagnostics/secrets.
row = s.snapshot()[0]
assert set(row) == {"connector_id", "events", "settings_deep_link", "dismissed_until", "dismissed_launch"}
print("connector notice state regression: PASS")
