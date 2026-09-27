import json
import unittest

from career_kit.accounts import prepare, report
from career_kit.errors import ContractError
from career_kit.mail import Mail
from helpers import workspace, setup


class MailAccountTests(unittest.TestCase):
    def test_reply_header_injection_is_rejected(self):
        with workspace() as paths:
            with self.assertRaises(ContractError):
                Mail(paths).draft({"to": ["recipient@example.invalid"], "subject": "Synthetic", "body": "Synthetic", "references": "example\r\nBcc: injected@example.invalid"})

    def config(self, paths):
        directory = paths.permanent("credentials"); directory.mkdir(mode=0o700)
        path = directory / "mail.json"
        path.write_text(json.dumps({"auth_kind": "app_password", "username": "synthetic@example.invalid",
            "password": "synthetic-app-secret", "imap": {"host": "imap.example.invalid", "port": 993},
            "smtp": {"host": "smtp.example.invalid", "port": 465, "tls": "ssl"}})); path.chmod(0o600)

    def test_registration_handoff_reuses_secret_and_never_claims_registration(self):
        with workspace() as paths:
            setup(paths)
            first = prepare(paths, "account-example", "https://employer.invalid/register")
            self.assertFalse(first["registered"])
            raw = paths.permanent(first["path"]).read_bytes()
            value = json.loads(raw)
            self.assertEqual(len(value["password"]), 12)
            self.assertTrue(value["password"].isalnum())
            self.assertNotIn(value["password"], json.dumps(first))
            self.assertTrue(prepare(paths, "account-example", "https://employer.invalid/register")["reused"])
            self.assertEqual(paths.permanent(first["path"]).read_bytes(), raw)
            with self.assertRaises(ContractError): prepare(paths, "account-example", "https://different.invalid/register")
            result = report(paths, "account-example", "registered")
            self.assertEqual(result["kind"], "account")

    def test_passwordless_handoff_stores_no_password(self):
        with workspace() as paths:
            setup(paths)
            result = prepare(paths, "passwordless-example", "https://employer.invalid/register", passwordless=True)
            self.assertIsNone(json.loads(paths.permanent(result["path"]).read_text())["password"])

    def test_send_requires_separate_authorization_and_is_never_repeated(self):
        with workspace() as paths:
            self.config(paths)
            calls = []
            class SMTP:
                def login(self, *args): pass
                def send_message(self, message): calls.append(message); return {}
                def quit(self): pass
            mail = Mail(paths, smtp_factory=lambda settings: SMTP())
            draft = mail.draft({"to": ["recipient@example.invalid"], "subject": "Synthetic message", "body": "Synthetic content"})
            with self.assertRaises(ContractError): mail.send(draft["id"])
            authorization = mail.authorize(draft["id"], draft["revision"])
            result = mail.send(authorization["id"])
            self.assertEqual(mail.store.get("effect", result["id"])["payload"]["status"], "confirmed")
            with self.assertRaises(ContractError): mail.send(authorization["id"])
            self.assertEqual(len(calls), 1)
            self.assertEqual(mail.authorize(draft["id"], draft["revision"])["id"], authorization["id"])

    def test_delivery_exception_is_uncertain_and_does_not_expose_provider_values(self):
        with workspace() as paths:
            self.config(paths)
            class SMTP:
                def login(self, *args): pass
                def send_message(self, message): raise OSError("synthetic-sensitive-provider-response")
                def quit(self): pass
            mail = Mail(paths, smtp_factory=lambda settings: SMTP())
            draft = mail.draft({"to": ["recipient@example.invalid"], "subject": "Synthetic", "body": "Synthetic"})
            authorization = mail.authorize(draft["id"], draft["revision"])
            with self.assertRaises(ContractError) as error: mail.send(authorization["id"])
            self.assertNotIn("sensitive-provider", str(error.exception))
            self.assertEqual(mail.store.get("effect", authorization["id"])["payload"]["status"], "uncertain")
            with self.assertRaises(ContractError): mail.send(authorization["id"])
            mail.reconcile(authorization["id"], "confirmed", "Synthetic provider observation")
            with self.assertRaises(ContractError): mail.send(authorization["id"])

    def test_imap_reads_without_mutating_mailbox_or_persisting_raw_mail(self):
        with workspace() as paths:
            self.config(paths); calls = []
            class IMAP:
                def __init__(self, *args, **kwargs): pass
                def login(self, *args): pass
                def select(self, name, readonly): calls.append(readonly); return "OK", []
                def uid(self, command, *args):
                    if command == "search": return "OK", [b"1"]
                    calls.append(args[-1])
                    return "OK", [(b"header", b"Subject: Synthetic invitation\nContent-Type: text/plain\n\nPlease use https://example.invalid/verify?token=synthetic for this verification code: 456789\n")]
                def logout(self): pass
            result = Mail(paths, imap_factory=IMAP).sync()
            self.assertEqual(calls, [True, "(BODY.PEEK[])"])
            self.assertFalse(result["persisted"])
            self.assertNotIn("456789", json.dumps(result))
            self.assertNotIn("?token=", json.dumps(result))
            self.assertFalse(paths.permanent("data").exists())

    def test_credentials_permissions_and_primary_password_are_rejected(self):
        with workspace() as paths:
            self.config(paths)
            path = paths.permanent("credentials/mail.json"); path.chmod(0o644)
            with self.assertRaises(ContractError): Mail(paths).config()
            path.chmod(0o600)
            value = json.loads(path.read_text()); value["auth_kind"] = "primary_password"; path.write_text(json.dumps(value))
            with self.assertRaises(ContractError): Mail(paths).config()

    def test_imap_error_never_exposes_provider_response(self):
        import imaplib
        with workspace() as paths:
            self.config(paths)
            def failing_factory(*args, **kwargs):
                raise imaplib.IMAP4.error("synthetic-sensitive-provider-response")
            with self.assertRaises(ContractError) as result:
                Mail(paths, imap_factory=failing_factory).sync()
            self.assertNotIn("synthetic-sensitive", str(result.exception))

    def test_uncertain_effect_blocks_new_identical_draft(self):
        with workspace() as paths:
            self.config(paths)
            class SMTP:
                def login(self, *args): pass
                def send_message(self, message): raise OSError("synthetic failure")
                def quit(self): pass
            mail = Mail(paths, smtp_factory=lambda _: SMTP())
            value = {"to": ["recipient@example.invalid"], "subject": "Synthetic", "body": "Synthetic"}
            draft = mail.draft(value); auth = mail.authorize(draft["id"], draft["revision"])
            with self.assertRaises(ContractError): mail.send(auth["id"])
            with self.assertRaises(ContractError): mail.draft(value)
            mail.reconcile(auth["id"], "not_sent", "Synthetic positive non-delivery observation")
            self.assertNotEqual(mail.draft(value)["id"], draft["id"])

    def test_expired_unclaimed_authorization_can_be_reauthorized_explicitly(self):
        with workspace() as paths:
            mail = Mail(paths)
            draft = mail.draft({"to": ["recipient@example.invalid"], "subject": "Synthetic", "body": "Synthetic"})
            auth = mail.authorize(draft["id"], draft["revision"])
            old = mail.store.get("effect", auth["id"])
            mail.store.put("effect", auth["id"], {**old["payload"], "expires_at": "2000-01-01T00:00:00+00:00"}, expected=old["revision"], reason="Synthetic expiry")
            renewed = mail.authorize(draft["id"], draft["revision"])
            self.assertNotEqual(renewed["id"], auth["id"])
