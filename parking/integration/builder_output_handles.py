from __future__ import annotations
from dataclasses import dataclass
import hashlib, hmac, json, re, secrets, time
from typing import Any

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
KINDS = frozenset({"diff","file","console","preview","test","build","rollback"})

class HandleError(ValueError): pass
class AccessDenied(PermissionError): pass

def _id(name:str, value:str)->str:
    if not isinstance(value,str) or not _ID.fullmatch(value) or "/" in value or "\\" in value:
        raise HandleError(f"invalid {name}")
    return value

def _scope_digest(chat_id:str, project_id:str, repo_scope:str)->str:
    _id("chat_id", chat_id); _id("project_id", project_id)
    if not isinstance(repo_scope,str) or not repo_scope or len(repo_scope)>1024:
        raise HandleError("invalid repo_scope")
    return hashlib.sha256(f"{chat_id}\0{project_id}\0{repo_scope}".encode()).hexdigest()

@dataclass(frozen=True)
class HandleRecord:
    handle_id: str
    kind: str
    scope_digest: str
    epoch: int
    builder_session_id: str
    revision: int
    artifact_digest: str
    created_at: int
    expires_at: int

    def public(self)->dict[str,Any]:
        return {
            "handle_id": self.handle_id, "kind": self.kind,
            "scope_digest": self.scope_digest, "epoch": self.epoch,
            "builder_session_id_hash": hashlib.sha256(self.builder_session_id.encode()).hexdigest(),
            "revision": self.revision, "artifact_digest": self.artifact_digest,
            "created_at": self.created_at, "expires_at": self.expires_at,
        }

class BuilderOutputHandleStore:
    """Metadata-only opaque handle store. Artifact bodies live elsewhere."""
    def __init__(self, secret:bytes):
        if not isinstance(secret,(bytes,bytearray)) or len(secret)<32: raise HandleError("secret too short")
        self._secret=bytes(secret); self._records:dict[str,HandleRecord]={}

    def issue(self, *, kind:str, chat_id:str, project_id:str, repo_scope:str,
              epoch:int, builder_session_id:str, revision:int, artifact_digest:str,
              ttl_seconds:int=900, now:int|None=None)->str:
        if kind not in KINDS: raise HandleError("unsupported kind")
        if not isinstance(epoch,int) or isinstance(epoch,bool) or epoch<0: raise HandleError("invalid epoch")
        _id("builder_session_id", builder_session_id)
        if not isinstance(revision,int) or isinstance(revision,bool) or revision<0: raise HandleError("invalid revision")
        if not isinstance(artifact_digest,str) or not re.fullmatch(r"[0-9a-f]{64}",artifact_digest): raise HandleError("invalid artifact_digest")
        if not isinstance(ttl_seconds,int) or not 1 <= ttl_seconds <= 3600: raise HandleError("invalid ttl")
        now = int(time.time() if now is None else now)
        nonce=secrets.token_hex(16)
        scope=_scope_digest(chat_id,project_id,repo_scope)
        body=f"{kind}.{scope}.{epoch}.{builder_session_id}.{revision}.{artifact_digest}.{nonce}".encode()
        sig=hmac.new(self._secret,body,hashlib.sha256).hexdigest()[:32]
        hid=f"boh1.{nonce}.{sig}"
        self._records[hid]=HandleRecord(hid,kind,scope,epoch,builder_session_id,revision,artifact_digest,now,now+ttl_seconds)
        return hid

    def resolve(self, handle_id:str, *, expected_kind:str, chat_id:str, project_id:str,
                repo_scope:str, current_epoch:int, builder_session_id:str,
                min_revision:int=0, now:int|None=None)->dict[str,Any]:
        rec=self._records.get(handle_id)
        if rec is None: raise AccessDenied("unknown handle")
        now=int(time.time() if now is None else now)
        scope=_scope_digest(chat_id,project_id,repo_scope)
        checks = (
            rec.kind == expected_kind,
            hmac.compare_digest(rec.scope_digest, scope),
            rec.epoch == current_epoch,
            hmac.compare_digest(rec.builder_session_id, _id("builder_session_id", builder_session_id)),
            rec.revision >= min_revision,
            now <= rec.expires_at,
        )
        if not all(checks): raise AccessDenied("handle scope/session/epoch/revision/ttl mismatch")
        return rec.public()

    def revoke_session(self, builder_session_id:str)->int:
        sid=_id("builder_session_id",builder_session_id)
        doomed=[k for k,v in self._records.items() if hmac.compare_digest(v.builder_session_id,sid)]
        for k in doomed: self._records.pop(k,None)
        return len(doomed)

    def export_metadata(self)->str:
        # Never exports repo_scope, chat_id, project_id, or artifact body.
        return json.dumps([r.public() for r in self._records.values()], sort_keys=True, separators=(",",":"))
