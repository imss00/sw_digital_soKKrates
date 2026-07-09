from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.routers import auth, browsing, youtube, photo, webhook, journal

app = FastAPI(title="PaperBack Agent", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(browsing.router, prefix="/browsing", tags=["browsing"])
app.include_router(youtube.router, prefix="/youtube", tags=["youtube"])
app.include_router(photo.router, prefix="/photos", tags=["photos"])
app.include_router(webhook.router, prefix="/webhook", tags=["webhook"])
app.include_router(journal.router, prefix="/journal", tags=["journal"])


@app.get("/health")
def health_check():
    return {"status": "ok", "service": "paperback-agent"}
