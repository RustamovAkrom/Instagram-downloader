import os
import re
import time
import threading
import logging
from typing import List, Optional

import instaloader
from fastapi import HTTPException

from app.config import settings
from app.utils.helpers import extract_shortcode
from app.schemas.media import MediaItem

logger = logging.getLogger("instagram_service")
logger.setLevel(logging.INFO)

CHALLENGE_REGEX = re.compile(r"https://www\.instagram\.com/challenge/[^\s)'\"]+")

# Настройки retry при rate limit
MAX_RETRIES = 5
INITIAL_BACKOFF = 5  # секунд


class InstagramService:
    def __init__(self):
        self.loader = instaloader.Instaloader(
            dirname_pattern=str(settings.DOWNLOAD_DIR),
            download_comments=False,
            save_metadata=False,
            compress_json=False,
            download_video_thumbnails=False,
            quiet=True
        )

        # Директории
        settings.SESSION_DIR.mkdir(parents=True, exist_ok=True)
        settings.DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

        # Блокировка для логина
        self._lock = threading.Lock()
        self._logged_in = False

    def _extract_challenge_url(self, text: str) -> Optional[str]:
        m = CHALLENGE_REGEX.search(text)
        return m.group(0) if m else None

    def ensure_logged_in(self, force: bool = False):
        """
        Загружает сессию из файла. Не логинится на каждый запрос.
        """
        if self._logged_in and not force:
            return

        with self._lock:
            if self._logged_in and not force:
                return

            if not settings.SESSION_FILE.exists():
                raise HTTPException(status_code=403, detail="Session file not found. Run create_session.py first")

            try:
                self.loader.load_session_from_file(settings.IG_USERNAME, filename=str(settings.SESSION_FILE))
                self._logged_in = True
                logger.info("Session loaded successfully")
            except Exception as e:
                logger.exception("Failed to load Instagram session")
                raise HTTPException(status_code=500, detail=f"Failed to load session: {e}")

    def create_session(self):
        """
        Ручное создание/обновление сессии.
        """
        try:
            self.ensure_logged_in(force=True)
            if self._logged_in:
                return {"status": "ok", "detail": "Session created/loaded"}
        except HTTPException:
            raise
        except Exception as e:
            logger.exception("create_session failed")
            raise HTTPException(status_code=500, detail=f"Failed to create session: {e}")

    def download_post(self, shortcode: str, download: bool = False):
        """
        Возвращает метаданные или скачивает пост на диск.
        Реализован retry при rate limit.
        """
        self.ensure_logged_in()
        if not self._logged_in:
            raise HTTPException(status_code=403, detail="Not logged in. Create session first.")

        shortcode = extract_shortcode(shortcode)
        backoff = INITIAL_BACKOFF

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                post = instaloader.Post.from_shortcode(self.loader.context, shortcode)

                media: List[MediaItem] = []

                if getattr(post, "is_video", False):
                    media.append(MediaItem(type="video", url=post.video_url))
                elif getattr(post, "typename", "") != "GraphSidecar":
                    media.append(MediaItem(type="image", url=post.url))
                else:
                    for node in post.get_sidecar_nodes():
                        media.append(MediaItem(
                            type="video" if getattr(node, "is_video", False) else "image",
                            url=(node.video_url if getattr(node, "is_video", False) else node.display_url)
                        ))

                if not media:
                    raise HTTPException(status_code=404, detail="No media found")

                if download:
                    target_dir = settings.DOWNLOAD_DIR / shortcode
                    target_dir.mkdir(parents=True, exist_ok=True)
                    logger.info("Downloading post %s into %s", shortcode, target_dir)
                    self.loader.download_post(post, target=str(target_dir))
                    return {
                        "username": post.owner_username,
                        "status": "downloaded",
                        "count": len(media),
                        "path": str(target_dir)
                    }

                return {
                    "username": post.owner_username,
                    "status": "success",
                    "count": len(media),
                    "media": media
                }

            except instaloader.exceptions.LoginRequiredException:
                self._logged_in = False
                raise HTTPException(status_code=403, detail="Session expired. Recreate session.")

            except instaloader.exceptions.PrivateProfileNotFollowedException:
                raise HTTPException(status_code=403, detail="Cannot access private profile")

            except instaloader.exceptions.ConnectionException as e:
                logger.warning("Connection error attempt %d/%d: %s", attempt, MAX_RETRIES, e)
                if attempt == MAX_RETRIES:
                    raise HTTPException(status_code=502, detail="Instagram rate limit / network error. " + str(e))
                time.sleep(backoff)
                backoff *= 2  # экспоненциальная задержка
                continue

            except Exception as e:
                logger.exception("Unexpected error while downloading post")
                raise HTTPException(status_code=400, detail=str(e))

# import instaloader
# from fastapi import HTTPException
# from app.config import settings
# from app.utils.helpers import extract_shortcode
# from app.schemas.media import MediaItem, MediaRequest
# from typing import List, Dict
# import os


# class InstagramService:
#     def __init__(self):
#         self.loader = instaloader.Instaloader(
#             dirname_pattern=settings.DOWNLOAD_DIR,
#             download_comments=False,
#             save_metadata=False,
#             compress_json=False,
#             download_video_thumbnails=False,
#             quiet=True,
#         )
#         settings.SESSION_DIR.mkdir(parents=True, exist_ok=True)
#         self._login()
    
#     def _login(self):
#         try:
#             if os.path.exists(settings.SESSION_FILE):
#                 self.loader.load_session_from_file(
#                     settings.IG_USERNAME,
#                     filename=str(settings.SESSION_FILE)
#                 )
#                 print("Session loaded successfully.")
#             else:
#                 self.loader.login(settings.IG_USERNAME, settings.IG_PASSWORD)
#                 self.loader.save_session_to_file(
#                     filename=str(settings.SESSION_FILE)
#                 )
#         except Exception as e:
#             raise HTTPException(status_code=500, detail=f"Instagram login failed: {str(e)}")
        
#     def download_post(self, shortcode: str):
#         try:
#             shortcode = extract_shortcode(shortcode)
#             post = instaloader.Post.from_shortcode(self.loader.context, shortcode)

#             media: List[MediaItem] = []

#             if post.is_video:
#                 media.append(MediaItem(type="video", url=post.video_url))

#             elif post.typename != "GraphSidecar":
#                 media.append(MediaItem(type="image", url=post.url))

#             else:
#                 for node in post.get_sidecar_nodes():
#                     media.append(MediaItem(
#                         type="video" if node.is_video else "image",
#                         url=node.video_url if node.is_video else node.display_url
#                     ))

#             if not media:
#                 raise HTTPException(status_code=404, detail="No media found in this post")
            
#             return {
#                 "username": post.owner_username,
#                 "status": "success",
#                 "count": len(media),
#                 "media": media,
#             }
        
#         except instaloader.exceptions.LoginRequiredException:
#             raise HTTPException(status_code=403, detail="Login required to access this post")
#         except instaloader.exceptions.PrivateProfileNotFollowedException:
#             raise HTTPException(status_code=403, detail="Cannot access private profile")
#         except Exception as e:
#             raise HTTPException(status_code=400, detail=str(e))
