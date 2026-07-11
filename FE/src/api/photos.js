import { getAuthHeaderIfReal } from "../auth";

const API_BASE = "https://paperback-agent.fly.dev";

export const PHOTO_LIMITS = {
  maxFiles: 20,
  maxFileSize: 10 * 1024 * 1024,
  maxTotalSize: 80 * 1024 * 1024,
  accept: "image/jpeg,image/png,image/webp",
};

export async function uploadPhotos(files) {
  const authHeader = getAuthHeaderIfReal();
  if (!authHeader) {
    throw new Error("로그인이 필요합니다.");
  }

  const form = new FormData();
  files.forEach((file) => form.append("files", file));

  const res = await fetch(`${API_BASE}/photos/upload`, {
    method: "POST",
    headers: authHeader,
    body: form,
  });

  if (res.status === 401) {
    throw new Error("로그인이 만료되었습니다. 다시 로그인해주세요.");
  }
  if (!res.ok) {
    let detail = `사진 업로드 실패: HTTP ${res.status}`;
    try {
      const data = await res.json();
      if (data?.detail) detail = Array.isArray(data.detail) ? detail : data.detail;
    } catch {
      // Keep fallback message.
    }
    throw new Error(detail);
  }

  return res.json();
}
