#!/usr/bin/env python3
"""
기존 평문 OAuth 토큰 일회성 암호화 스크립트.

fernet_key를 EncryptedText 컬럼 타입에 연결하기 전에 저장된 토큰들은
여전히 평문으로 DB에 남아있다 — 새 코드는 "쓸 때"만 암호화하므로,
refresh_token처럼 자주 재발급되지 않는 값은 자연 갱신을 오래 기다려야
암호화된다. 이 스크립트로 한 번에 백필한다.

원시 SQL로 직접 읽고 쓴다 (ORM의 dirty-tracking에 기대면 "같은 평문 값 재대입"이
UPDATE로 이어지는지 보장할 수 없어서다). 이미 암호화된 값(Fernet.decrypt 성공)은
건드리지 않아 재실행해도 안전하다(idempotent).

사용법 (레포 루트에서):
  python scripts/encrypt_existing_tokens.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import text

from backend.config import settings
from backend.database import engine

TOKEN_COLUMNS = [
    "spotify_access_token",
    "spotify_refresh_token",
    "google_access_token",
    "google_refresh_token",
    "notion_token",
]


def main() -> None:
    if not settings.fernet_key:
        print("FERNET_KEY가 설정되어 있지 않습니다 — 암호화할 수 없어 종료합니다.")
        return

    fernet = Fernet(settings.fernet_key.encode())

    with engine.begin() as conn:
        rows = conn.execute(text(f"SELECT id, {', '.join(TOKEN_COLUMNS)} FROM users")).mappings().all()

        encrypted_count = 0
        already_count = 0
        for row in rows:
            updates = {}
            for col in TOKEN_COLUMNS:
                value = row[col]
                if value is None:
                    continue
                try:
                    fernet.decrypt(value.encode())
                    already_count += 1
                    continue  # 이미 암호화됨
                except InvalidToken:
                    updates[col] = fernet.encrypt(value.encode()).decode()

            if updates:
                set_clause = ", ".join(f"{col} = :{col}" for col in updates)
                conn.execute(
                    text(f"UPDATE users SET {set_clause} WHERE id = :id"),
                    {**updates, "id": row["id"]},
                )
                encrypted_count += len(updates)

    print(f"암호화 완료: {encrypted_count}개 필드, 이미 암호화되어 건너뜀: {already_count}개 필드.")


if __name__ == "__main__":
    main()
