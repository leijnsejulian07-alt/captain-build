import json
import os
import urllib.error
import urllib.request

PORT = int(os.getenv("AI_ROUTER_PORT", "20129"))
URL = f"http://127.0.0.1:{PORT}/v1/chat/completions"
BODY = json.dumps({"model": "captain", "messages": "not-a-list"}).encode("utf-8")

def post(headers=None):
    req = urllib.request.Request(
        URL,
        data=BODY,
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")

def expect(status, body, code, needle):
    assert status == code, (status, body)
    assert needle in body, body

status, body = post()
expect(status, body, 400, "messages must be a list")

status, body = post({
    "X-Captain-Project-Id": "scope-http-smoke",
    "X-Captain-Repo-Scope": "repo-a",
})
expect(status, body, 400, "messages must be a list")

status, body = post({"X-Captain-Project-Id": "scope-http-smoke"})
expect(status, body, 400, "complete project_id + repo_scope pair required")

status, body = post({"X-Captain-Repo-Scope": "repo-a"})
expect(status, body, 400, "complete project_id + repo_scope pair required")

status, body = post({
    "X-Captain-Project-Id": "   ",
    "X-Captain-Repo-Scope": "   ",
})
expect(status, body, 400, "messages must be a list")

print("CAPTAIN_SCOPE_PAIR_HTTP_PASS")
