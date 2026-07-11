import asyncio
from io import BytesIO
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from fastapi import HTTPException
from PIL import Image

from backend.routers import photo


def _png_bytes() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (4, 4), color="white").save(buf, format="PNG")
    return buf.getvalue()


class FakeQuery:
    def __init__(self, existing=None):
        self.existing = existing

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return self.existing


class FakeSession:
    def __init__(self, existing=None):
        self.existing = existing
        self.added = []
        self.committed = False
        self.flushed = False

    def query(self, *_args, **_kwargs):
        return FakeQuery(self.existing)

    def add(self, item):
        self.added.append(item)

    def flush(self):
        self.flushed = True
        for item in self.added:
            if getattr(item, "id", None) is None:
                item.id = 123

    def commit(self):
        self.committed = True


class FakeUpload:
    def __init__(self, filename: str, content_type: str, content: bytes):
        self.filename = filename
        self.content_type = content_type
        self._content = content

    async def read(self):
        return self._content


class PhotoUploadTest(TestCase):
    def test_requires_bearer_token(self):
        with self.assertRaises(HTTPException) as ctx:
            photo._resolve_user_id(None)

        self.assertEqual(ctx.exception.status_code, 401)

    def test_rejects_non_image_content_type(self):
        with self.assertRaises(HTTPException) as ctx:
            photo._validate_file("note.txt", "text/plain", b"hello")

        self.assertEqual(ctx.exception.status_code, 415)

    def test_upload_uses_jwt_user_id(self):
        upload = FakeUpload("shot.png", "image/png", _png_bytes())
        db = FakeSession()

        with patch("backend.routers.photo.decode_jwt", return_value=42), patch(
            "backend.routers.photo.extract_exif",
            return_value={"taken_at": None, "latitude": None, "longitude": None, "camera_model": None},
        ), patch("backend.routers.photo.is_screenshot", return_value=False), patch(
            "backend.routers.photo.settings.google_api_key",
            "",
        ):
            result = asyncio.run(photo.upload_photos([upload], authorization="Bearer token", db=db))

        self.assertEqual(result["uploaded"], 1)
        self.assertEqual(result["results"][0]["photo_id"], 123)
        self.assertEqual(result["results"][0]["image_url"], "/photos/123/content")
        self.assertTrue(db.committed)
        saved_photo = next(item for item in db.added if isinstance(item, photo.Photo))
        self.assertEqual(saved_photo.user_id, 42)
        self.assertEqual(saved_photo.image_data, upload._content)
        self.assertEqual(saved_photo.content_type, "image/png")
        saved_doc = next(item for item in db.added if isinstance(item, photo.UnifiedDocument))
        self.assertEqual(saved_doc.user_id, 42)
        self.assertEqual(saved_doc.source, "photo")
        self.assertEqual(saved_doc.source_id, saved_photo.id)
        self.assertEqual(saved_doc.content_type, "photo")
        self.assertIn("사진 업로드: shot.png", saved_doc.content_text)

    def test_upload_stores_scene_labels_in_photo_and_document(self):
        upload = FakeUpload("mountain.jpg", "image/jpeg", _png_bytes())
        db = FakeSession()
        vision = {
            "ocr_text": None,
            "labels": [
                {"description": "Mountain", "score": 0.98},
                {"description": "Sky", "score": 0.91},
            ],
        }

        with patch("backend.routers.photo.decode_jwt", return_value=42), patch(
            "backend.routers.photo.extract_exif",
            return_value={"taken_at": None, "latitude": None, "longitude": None, "camera_model": None},
        ), patch("backend.routers.photo.is_screenshot", return_value=False), patch(
            "backend.routers.photo.settings.google_api_key",
            "vision-key",
        ), patch("backend.routers.photo.analyze_image_vision", return_value=vision):
            result = asyncio.run(photo.upload_photos([upload], authorization="Bearer token", db=db))

        self.assertEqual(result["results"][0]["labels"], vision["labels"])
        saved_photo = next(item for item in db.added if isinstance(item, photo.Photo))
        self.assertIn("Mountain", saved_photo.vision_labels)
        saved_doc = next(item for item in db.added if isinstance(item, photo.UnifiedDocument))
        self.assertIn("장면 키워드: Mountain, Sky", saved_doc.content_text)

    def test_duplicate_is_scoped_to_jwt_user_id(self):
        existing = SimpleNamespace(id=77, image_data=b"already-stored")
        upload = FakeUpload("dup.png", "image/png", _png_bytes())
        db = FakeSession(existing=existing)

        with patch("backend.routers.photo.decode_jwt", return_value=42):
            result = asyncio.run(photo.upload_photos([upload], authorization="Bearer token", db=db))

        self.assertEqual(result["results"][0]["duplicate"], True)
        self.assertEqual(result["results"][0]["photo_id"], 77)
        self.assertEqual(db.added, [])

    def test_get_photo_content_requires_owner(self):
        stored = SimpleNamespace(id=12, user_id=42, image_data=b"image-bytes", content_type="image/png")
        db = FakeSession(existing=stored)

        with patch("backend.routers.photo.decode_jwt", return_value=42):
            response = photo.get_photo_content(12, authorization="Bearer token", db=db)

        self.assertEqual(response.body, b"image-bytes")
        self.assertEqual(response.media_type, "image/png")
