import logging

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.types import Text, TypeDecorator

from backend.config import settings

logger = logging.getLogger(__name__)

_fernet = Fernet(settings.fernet_key.encode()) if settings.fernet_key else None

if _fernet is None:
    logger.warning(
        "FERNET_KEY not set — OAuth tokens will be stored in plaintext. "
        "Set fernet_key (backend/config.py) for production deployments."
    )


class EncryptedText(TypeDecorator):
    """Text column that is transparently Fernet-encrypted at rest.

    Falls back to plaintext when fernet_key is unset, so local dev/tests
    without the env var keep working. On read, rows written before
    encryption was enabled (plaintext) are detected via InvalidToken and
    returned as-is instead of erroring — they get re-encrypted on next write.
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None or _fernet is None:
            return value
        return _fernet.encrypt(value.encode()).decode()

    def process_result_value(self, value, dialect):
        if value is None or _fernet is None:
            return value
        try:
            return _fernet.decrypt(value.encode()).decode()
        except InvalidToken:
            return value
