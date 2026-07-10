from urllib.parse import parse_qs, urlparse
from unittest import TestCase
from unittest.mock import patch

from fastapi import HTTPException

from backend.routers.auth import google_login
from backend.routers.journal import _resolve_user_id


class JournalAuthTest(TestCase):
    def test_google_login_uses_web_state(self):
        data = google_login()
        parsed = urlparse(data["auth_url"])
        params = parse_qs(parsed.query)

        self.assertEqual(params["state"], ["web"])
        self.assertEqual(params["response_type"], ["code"])

    def test_journal_requires_bearer_token(self):
        with self.assertRaises(HTTPException) as ctx:
            _resolve_user_id(None)

        self.assertEqual(ctx.exception.status_code, 401)

    def test_journal_uses_jwt_user_id(self):
        with patch("backend.routers.journal.decode_jwt", return_value=17):
            self.assertEqual(_resolve_user_id("Bearer token-value"), 17)
