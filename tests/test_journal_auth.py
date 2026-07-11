from urllib.parse import parse_qs, urlparse
from unittest import TestCase
from unittest.mock import patch

from fastapi import HTTPException

from backend.routers import auth
from backend.routers.auth import extension_done, google_extension_login, google_login
from backend.routers.journal import _resolve_user_id
from backend.routers.webhook import _verify_secret


class JournalAuthTest(TestCase):
    def setUp(self):
        auth._google_state_store.clear()

    def test_google_login_uses_one_time_web_state(self):
        data = google_login()
        parsed = urlparse(data["auth_url"])
        params = parse_qs(parsed.query)

        state = params["state"][0]
        self.assertNotEqual(state, "web")
        self.assertEqual(auth._google_state_pop(state), "web")
        self.assertIsNone(auth._google_state_pop(state))
        self.assertEqual(params["response_type"], ["code"])

    def test_google_extension_login_uses_one_time_extension_state(self):
        response = google_extension_login()
        parsed = urlparse(response.headers["location"])
        state = parse_qs(parsed.query)["state"][0]

        self.assertNotEqual(state, "extension")
        self.assertEqual(auth._google_state_pop(state), "extension")
        self.assertIsNone(auth._google_state_pop(state))

    def test_google_callback_rejects_invalid_state_before_token_exchange(self):
        with patch("backend.routers.auth.httpx.post") as post:
            with self.assertRaises(HTTPException) as ctx:
                auth.google_callback("code", state="missing")

        self.assertEqual(ctx.exception.status_code, 400)
        post.assert_not_called()

    def test_extension_done_escapes_token_attribute(self):
        response = extension_done('bad" onmouseover="alert(1)')

        self.assertIn(b"bad&quot; onmouseover=&quot;alert(1)", response.body)
        self.assertNotIn(b'data-token="bad" onmouseover=', response.body)

    def test_journal_requires_bearer_token(self):
        with self.assertRaises(HTTPException) as ctx:
            _resolve_user_id(None)

        self.assertEqual(ctx.exception.status_code, 401)

    def test_journal_uses_jwt_user_id(self):
        with patch("backend.routers.journal.decode_jwt", return_value=17):
            self.assertEqual(_resolve_user_id("Bearer token-value"), 17)

    def test_webhook_requires_configured_secret_by_default(self):
        with patch("backend.routers.webhook.settings.webhook_secret", ""), patch(
            "backend.routers.webhook.settings.allow_unprotected_webhooks", False
        ):
            with self.assertRaises(HTTPException) as ctx:
                _verify_secret(None)

        self.assertEqual(ctx.exception.status_code, 503)

    def test_webhook_accepts_matching_secret_only(self):
        with patch("backend.routers.webhook.settings.webhook_secret", "expected"), patch(
            "backend.routers.webhook.settings.allow_unprotected_webhooks", False
        ):
            _verify_secret("expected")
            with self.assertRaises(HTTPException) as ctx:
                _verify_secret("wrong")

        self.assertEqual(ctx.exception.status_code, 401)
