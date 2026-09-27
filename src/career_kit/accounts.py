"""Private local handoff for human-operated registration; no browser automation."""
import json
import secrets
import string

from .atomic import atomic_publish_noreplace
from .canonical_json import pretty_bytes
from .store import Store, safe_id
from .workflows import require, official_url


def prepare(paths, identifier, registration_url, *, passwordless=False):
    safe_id(identifier); official_url(registration_url)
    store = Store(paths)
    profile = store.get("candidate_profile", "profile")
    require(profile["payload"].get("status") == "confirmed", "CANDIDATE_UNCONFIRMED", "confirm the local identity profile first")
    target = paths.permanent(f"credentials/registration/{identifier}.json")
    if target.exists():
        require(json.loads(target.read_text())["registration_url"] == registration_url,
                "ACCOUNT_SCOPE_CONFLICT", "this account identifier is already bound to another registration page")
        return {"path": target.relative_to(paths.root).as_posix(), "reused": True, "registered": False}
    require(profile["payload"].get("email") or profile["payload"].get("phone"), "ACCOUNT_IDENTITY_MISSING", "provide the account identifier privately first")
    password = None
    if not passwordless:
        alphabet = string.ascii_letters + string.digits
        while True:
            password = "".join(secrets.choice(alphabet) for _ in range(12))
            if any(c.isupper() for c in password) and any(c.islower() for c in password) and any(c.isdigit() for c in password):
                break
    target.parent.mkdir(parents=True, exist_ok=True); target.parent.chmod(0o700)
    paths.permanent("credentials").chmod(0o700)
    atomic_publish_noreplace(target, pretty_bytes({"registration_url": registration_url,
        "identifier": profile["payload"].get("email"), "phone": profile["payload"].get("phone"),
        "password": password, "status": "prepared_for_user"}))
    return {"path": target.relative_to(paths.root).as_posix(), "reused": False,
            "registered": False, "next_action": "user opens this file locally and registers; do not read it into model context"}


def report(paths, identifier, status):
    require(status in {"registered", "awaiting_verification", "cancelled"}, "ACCOUNT_INVALID", "record the user's actual report")
    safe_id(identifier)
    target = paths.permanent(f"credentials/registration/{identifier}.json")
    require(target.is_file(), "ACCOUNT_INVALID", "private account handoff is missing")
    store = Store(paths)
    current = [a for a in store.list("account") if a["id"] == identifier]
    return store.put("account", identifier, {"status": status, "credential_path": target.relative_to(paths.root).as_posix(), "source": "user_report"},
                     expected=current[0]["revision"] if current else None, actor="user", reason="User-operated registration report, not an Agent-created or verified login")
