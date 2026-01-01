import os
import instaloader
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv
from urllib.parse import urlparse
from typing import List, Dict

load_dotenv()

SESSION_USER = os.getenv("IG_USERNAME")
IG_PASSWORD = os.getenv("IG_PASSWORD")

if not SESSION_USER:
    raise RuntimeError("IG_USERNAME not set in .env")

if not IG_PASSWORD:
    print("Warning: IG_PASSWORD not set in .env. Ensure session file exists.")


def extract_shortcode(url: str) -> str:
    parsed = urlparse(url)
    parts = parsed.path.strip("/").split("/")
    if len(parts) >= 2 and parts[0] in {"p", "reel", "tv"}:
        return parts[1]
    raise ValueError("Invalid Instagram URL. URL must contain /p/, /reel/ or /tv/")


loader = instaloader.Instaloader(
    download_comments=False,
    save_metadata=False,
    compress_json=False,
    download_video_thumbnails=False,
)

try:
    loader.load_session_from_file(SESSION_USER)
except FileNotFoundError:
    if not IG_PASSWORD:
        raise RuntimeError("Session not found and IG_PASSWORD not set in .env")
    loader.login(SESSION_USER, IG_PASSWORD)
    loader.save_session_to_file()
    print("Session created and saved.")


app = FastAPI(title="Instagram Media Downloader API")


class MediaRequest(BaseModel):
    url: str


class MediaItem(BaseModel):
    type: str  # "image" or "video"
    url: str


@app.post("/media", response_model=Dict)
async def get_instagram_media(data: MediaRequest):
    try:
        shortcode = extract_shortcode(data.url)
        post = instaloader.Post.from_shortcode(loader.context, shortcode)

        media: List[MediaItem] = []

        # Видео / Reel
        if post.is_video:
            media.append(MediaItem(type="video", url=post.video_url))

        # Одиночное фото
        elif post.typename != "GraphSidecar":
            media.append(MediaItem(type="image", url=post.url))

        # Карусель (альбом)
        else:
            for node in post.get_sidecar_nodes():
                media.append(MediaItem(
                    type="video" if node.is_video else "image",
                    url=node.video_url if node.is_video else node.display_url
                ))

        if not media:
            raise HTTPException(status_code=404, detail="No media found in this post")

        return {
            "status": "success",
            "count": len(media),
            "media": [item.dict() for item in media]
        }

    except instaloader.exceptions.LoginRequiredException:
        raise HTTPException(status_code=403, detail="Login required to access this post")
    except instaloader.exceptions.PrivateProfileNotFollowedException:
        raise HTTPException(status_code=403, detail="Cannot access private profile")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
