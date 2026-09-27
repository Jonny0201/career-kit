"""On-demand IMAP/SMTP. Secrets never enter CLI output or durable drafts."""
from __future__ import annotations

from datetime import datetime, UTC, timedelta
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import make_msgid
import imaplib
import json
import mimetypes
import smtplib
import ssl
import stat
import hashlib

from .canonical_json import canonical_sha256
from .documents import digest
from .errors import ContractError
from .ids import new_id
from .store import Store
from .workflows import require, redact


class Mail:
    def __init__(self, paths, *, smtp_factory=None, imap_factory=None):
        self.paths = paths
        self.store = Store(paths)
        self.smtp_factory = smtp_factory
        self.imap_factory = imap_factory

    def config(self):
        path = self.paths.permanent("credentials/mail.json")
        require(path.is_file(), "MAIL_NOT_CONFIGURED", "configure credentials/mail.json privately; never paste its password into chat")
        require(stat.S_IMODE(path.stat().st_mode) & 0o077 == 0, "SECRET_PERMISSIONS", "mail credentials must be owner-only")
        value = json.loads(path.read_text())
        require(value.get("auth_kind") == "app_password" and value.get("username") and value.get("password"),
                "MAIL_CONFIG_INVALID", "use a provider-supported dedicated app password, not a primary account password")
        for kind in ("imap", "smtp"):
            part = value.get(kind, {})
            require(part.get("host") and isinstance(part.get("port"), int), "MAIL_CONFIG_INVALID", "declare IMAP/SMTP host and port")
        require(value["smtp"].get("tls") in {"ssl", "starttls"}, "MAIL_CONFIG_INVALID", "SMTP requires TLS")
        return value

    def sync(self, limit=10):
        require(1 <= limit <= 50, "MAIL_LIMIT_INVALID", "request 1..50 messages")
        config = self.config()
        factory = self.imap_factory or imaplib.IMAP4_SSL
        client = None
        summaries = []
        try:
            client = factory(config["imap"]["host"], config["imap"]["port"], ssl_context=ssl.create_default_context(), timeout=30)
            client.login(config["username"], config["password"])
            status, _ = client.select("INBOX", readonly=True)
            require(status == "OK", "MAIL_READ_FAILED", "could not select the read-only inbox")
            status, data = client.uid("search", None, "ALL")
            require(status == "OK", "MAIL_READ_FAILED", "message lookup failed")
            for uid in data[0].split()[-limit:]:
                status, items = client.uid("fetch", uid, "(BODY.PEEK[])")
                require(status == "OK", "MAIL_READ_FAILED", "message fetch failed")
                raw = next((item[1] for item in items if isinstance(item, tuple)), b"")
                require(len(raw) <= 5_000_000, "MAIL_READ_FAILED", "message exceeds the bounded read size")
                message = BytesParser(policy=policy.default).parsebytes(raw)
                part = message.get_body(preferencelist=("plain",)) if message.is_multipart() else message
                body = part.get_content() if part and part.get_content_type() == "text/plain" else "[HTML-only message; inspect locally]"
                # No raw MIME, sender identity, one-time link or verification code is stored.
                summaries.append({"subject": redact(str(message.get("Subject", ""))),
                                  "date": redact(str(message.get("Date", ""))), "body": redact(str(body))[:4000],
                                  "untrusted_content": True})
        except ContractError:
            raise
        except Exception:
            raise ContractError("MAIL_READ_FAILED", "mail read failed; raw provider responses and private values are withheld") from None
        finally:
            try:
                if client:
                    client.logout()
            except Exception:
                pass
        return {"messages": summaries, "persisted": False, "read_only": True}

    def draft(self, value):
        require(isinstance(value.get("to"), list) and value["to"] and value.get("subject") and value.get("body"),
                "MAIL_DRAFT_INVALID", "declare exact recipients, subject and body in a private input file")
        require(all(isinstance(item, str) and "@" in item and not any(c in item for c in "\r\n") for item in value["to"])
                and not any(c in value["subject"] for c in "\r\n"), "MAIL_DRAFT_INVALID", "invalid header values")
        require(all(value.get(k) is None or (isinstance(value[k], str) and not any(c in value[k] for c in "\r\n"))
                    for k in ("in_reply_to", "references")), "MAIL_DRAFT_INVALID", "reply headers cannot contain line breaks")
        attachments = []
        for item in value.get("attachments", []):
            path = self.paths.permanent(item["path"])
            require(item["path"].startswith(("data/documents/", "local/attachments/")) and path.is_file()
                    and digest(path) == item["sha256"], "MAIL_ATTACHMENT_INVALID", "attachment must bind exact approved local bytes")
            attachments.append({"path": item["path"], "sha256": item["sha256"]})
        payload = {"to": value["to"], "subject": value["subject"], "body": value["body"], "attachments": attachments,
                   "in_reply_to": value.get("in_reply_to"), "references": value.get("references")}
        fingerprint = canonical_sha256(payload)
        for effect in self.store.list("effect"):
            status = effect["payload"].get("status")
            expired = status == "authorized" and datetime.now(UTC) >= datetime.fromisoformat(effect["payload"]["expires_at"])
            if status in {"authorized", "claimed", "uncertain", "unknown"} and not expired:
                prior = self.store.get("mail_draft", effect["payload"]["draft_id"], effect["payload"]["draft_revision"])
                require(prior["payload"].get("content_hash") != fingerprint, "MAIL_DUPLICATE_PENDING",
                        "an identical message already has a pending effect; recover it rather than creating another draft")
        payload.update(content_hash=fingerprint, message_id=make_msgid(domain="career-kit.invalid"))
        return self.store.put("mail_draft", new_id("mail_thread"), payload, reason="Prepared exact private mail draft; not permission to send")

    def authorize(self, draft_id, revision):
        draft = self.store.get("mail_draft", draft_id)
        require(draft["revision"] == revision, "REVISION_CONFLICT", "draft changed since presentation")
        # Existing authorization/claim for this exact draft is reused, not duplicated.
        for effect in self.store.list("effect"):
            if effect["payload"].get("draft_revision") == revision:
                if effect["payload"]["status"] == "expired":
                    continue
                if effect["payload"]["status"] == "authorized" and datetime.now(UTC) >= datetime.fromisoformat(effect["payload"]["expires_at"]):
                    self.store.put("effect", effect["id"], {**effect["payload"], "status": "expired"}, expected=effect["revision"],
                                   reason="Unused authorization expired before any send claim; current user requests a fresh authorization")
                    continue
                return {"id": effect["id"], "revision": effect["revision"], "status": effect["payload"]["status"], "reused": True}
        return self.store.put("effect", new_id("execution"), {"action": "mail_send", "draft_id": draft_id,
            "draft_revision": revision, "status": "authorized", "expires_at": (datetime.now(UTC) + timedelta(minutes=15)).isoformat()},
            actor="user", reason="User authorized exactly this draft's recipients, body and attachments once")

    def send(self, authorization_id):
        effect = self.store.get("effect", authorization_id)
        require(effect["payload"]["action"] == "mail_send" and effect["payload"]["status"] == "authorized",
                "MAIL_EFFECT_NOT_EXECUTABLE", "send is already claimed, completed or uncertain; do not retry")
        require(datetime.now(UTC) < datetime.fromisoformat(effect["payload"]["expires_at"]), "MAIL_AUTH_EXPIRED", "the exact send authorization expired")
        draft = self.store.get("mail_draft", effect["payload"]["draft_id"], effect["payload"]["draft_revision"])
        config = self.config()
        message = EmailMessage()
        message["From"] = config["username"]
        message["To"] = ", ".join(draft["payload"]["to"])
        message["Subject"] = draft["payload"]["subject"]
        message["Message-ID"] = draft["payload"]["message_id"]
        for header, key in (("In-Reply-To", "in_reply_to"), ("References", "references")):
            if draft["payload"].get(key):
                message[header] = draft["payload"][key]
        message.set_content(draft["payload"]["body"])
        for item in draft["payload"]["attachments"]:
            path = self.paths.permanent(item["path"])
            content = path.read_bytes()
            require(hashlib.sha256(content).hexdigest() == item["sha256"], "MAIL_ATTACHMENT_INVALID", "attachment changed after authorization")
            mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            main, sub = mime.split("/", 1)
            message.add_attachment(content, maintype=main, subtype=sub, filename=path.name)
        claim = self.store.put("effect", authorization_id, {**effect["payload"], "status": "claimed"},
                               expected=effect["revision"], reason="Persist single-use claim before contacting SMTP")
        client = None
        try:
            settings = config["smtp"]
            if self.smtp_factory:
                client = self.smtp_factory(settings)
            elif settings["tls"] == "ssl":
                client = smtplib.SMTP_SSL(settings["host"], settings["port"], context=ssl.create_default_context(), timeout=30)
            else:
                client = smtplib.SMTP(settings["host"], settings["port"], timeout=30)
                client.starttls(context=ssl.create_default_context())
            client.login(config["username"], config["password"])
            refused = client.send_message(message)
            require(not refused, "MAIL_PARTIAL_DELIVERY", "some recipients were refused; do not resend the whole message")
        except Exception:
            self.store.put("effect", authorization_id, {**effect["payload"], "status": "uncertain"},
                           expected=claim["revision"], reason="Delivery was not positively confirmed; inspect provider state, never replay this claim")
            raise ContractError("MAIL_SEND_UNCERTAIN", "inspect Sent/provider state before deciding any further action; credentials and provider response are withheld") from None
        finally:
            if client:
                try:
                    client.quit()
                except Exception:
                    pass
        return self.store.put("effect", authorization_id, {**effect["payload"], "status": "confirmed"},
                              expected=claim["revision"], reason="SMTP accepted this exact message; acceptance is not proof that the recipient read it")

    def reconcile(self, identifier, outcome, evidence):
        require(outcome in {"confirmed", "not_sent", "unknown"} and evidence.strip(), "RECONCILIATION_INVALID", "record an actual provider observation")
        effect = self.store.get("effect", identifier)
        require(effect["payload"]["status"] in {"claimed", "uncertain", "unknown"}, "RECONCILIATION_INVALID", "this effect does not need reconciliation")
        return self.store.put("effect", identifier, {**effect["payload"], "status": outcome, "evidence": evidence},
                              expected=effect["revision"], reason="Recorded provider evidence; the original authorization remains consumed")
