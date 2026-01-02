# app/services/instagram.py
import os
import re
import time
import threading
import logging
import random
from typing import List, Optional

import instaloader
from fastapi import HTTPException

from app.config import settings
from app.utils.helpers import extract_shortcode
from app.schemas.media import MediaItem

logger = logging.getLogger("instagram_service")
logger.setLevel(logging.INFO)

CHALLENGE_REGEX = re.compile(r"https://www\.instagram\.com/challenge/[^\s)'\"]+")

# Настройки retry / throttle
MAX_RETRIES = 6
INITIAL_BACKOFF = 10       # стартовая задержка при rate-limit (сек)
MAX_BACKOFF = 300          # макс задержка (сек) при экспоненциальном backoff
MIN_REQUEST_INTERVAL = 8   # минимальное время между запросами к Instagram (сек)
JITTER_MAX = 2.0           # максимум случайного джиттера (сек)


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

        # Блокировки
        self._lock = threading.Lock()           # для логина/сессии
        self._request_lock = threading.Lock()   # для throttle по времени запросов
        self._logged_in = False

        # Время последнего запроса (monotonic)
        self._last_request_time = 0.0

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
                logger.info("Loading session file: %s", settings.SESSION_FILE)
                # reload session to refresh cookies/context
                self.loader.load_session_from_file(settings.IG_USERNAME, filename=str(settings.SESSION_FILE))
                self._logged_in = True
                logger.info("Session loaded successfully")
            except Exception as e:
                logger.exception("Failed to load Instagram session")
                # если сессия не загрузилась — пометка
                self._logged_in = False
                raise HTTPException(status_code=500, detail=f"Failed to load session: {e}")

    def create_session(self):
        """
        Ручное создание/обновление сессии (вызывается вручную при деплое).
        """
        if not settings.IG_USERNAME or not settings.IG_PASSWORD:
            raise HTTPException(status_code=403, detail="IG credentials not provided (IG_USERNAME/IG_PASSWORD).")

        with self._lock:
            try:
                logger.info("Attempting login for user %s", settings.IG_USERNAME)
                self.loader.login(settings.IG_USERNAME, settings.IG_PASSWORD)
                self.loader.save_session_to_file(filename=str(settings.SESSION_FILE))
                self._logged_in = True
                logger.info("Login success and session saved: %s", settings.SESSION_FILE)
                return {"status": "ok", "detail": "Session created/updated"}
            except instaloader.exceptions.LoginException as e:
                challenge = self._extract_challenge_url(str(e))
                if challenge:
                    logger.error("Checkpoint required during create_session: %s", challenge)
                    raise HTTPException(status_code=403, detail=f"Checkpoint required. Open: {challenge}")
                logger.exception("LoginException during create_session")
                raise HTTPException(status_code=403, detail=f"Login failed: {e}")
            except Exception as e:
                logger.exception("Unexpected error during create_session")
                raise HTTPException(status_code=500, detail=f"Failed to create session: {e}")

    def _throttle(self):
        """Обеспечить MIN_REQUEST_INTERVAL между запросами к Instagram (thread-safe)."""
        with self._request_lock:
            now = time.monotonic()
            elapsed = now - self._last_request_time
            to_wait = MIN_REQUEST_INTERVAL - elapsed
            if to_wait > 0:
                jitter = random.uniform(0, JITTER_MAX)
                sleep_for = to_wait + jitter
                logger.info("Throttling: sleeping %.2fs to respect MIN_REQUEST_INTERVAL", sleep_for)
                time.sleep(sleep_for)
            self._last_request_time = time.monotonic()

    def download_post(self, shortcode: str, download: bool = False):
        """
        Возвращает метаданные или скачивает пост на диск.
        Реализован retry при rate limit + session reload.
        """
        # Убедимся, что есть сессия на сервере
        try:
            self.ensure_logged_in()
        except HTTPException:
            # пробросим вверх
            raise

        shortcode = extract_shortcode(shortcode)
        backoff = INITIAL_BACKOFF

        for attempt in range(1, MAX_RETRIES + 1):
            # Обязанное throttle перед каждым реальным сетевым запросом к Instagram
            self._throttle()

            try:
                logger.info("Attempt %d to fetch shortcode %s", attempt, shortcode)
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
                # Сессия устарела — пометим и запросим пересоздание
                self._logged_in = False
                logger.warning("LoginRequiredException: session expired")
                raise HTTPException(status_code=403, detail="Session expired. Recreate session.")

            except instaloader.exceptions.PrivateProfileNotFollowedException:
                logger.info("Private profile not accessible for shortcode %s", shortcode)
                raise HTTPException(status_code=403, detail="Cannot access private profile")

            except instaloader.exceptions.ConnectionException as e:
                # Очень важно смотреть текст ошибки — если это "Please wait a few minutes" -> rate limit
                err_text = str(e)
                logger.warning("Connection error attempt %d/%d: %s", attempt, MAX_RETRIES, err_text)

                # Если это checkpoint-like message, extract link and return actionable HTTPException
                challenge = self._extract_challenge_url(err_text)
                if challenge:
                    logger.error("Checkpoint URL found in connection error: %s", challenge)
                    raise HTTPException(status_code=403,
                                        detail=f"Checkpoint required. Open this URL in a browser and follow instructions: {challenge}")

                # Если превышен лимит, делаем retry с backoff + jitter
                if attempt == MAX_RETRIES:
                    logger.error("Max retries reached - giving up for shortcode %s", shortcode)
                    raise HTTPException(status_code=502, detail="Instagram rate limit / network error. " + err_text)

                # Попытка обновить сессию на средине retry-последовательности
                if attempt >= 2:
                    try:
                        logger.info("Attempting to reload session file (attempt %d)", attempt)
                        # пробуем перезагрузить сессию, возможно cookies устарели, но файл всё ещё пригоден
                        self.loader.load_session_from_file(settings.IG_USERNAME, filename=str(settings.SESSION_FILE))
                        self._logged_in = True
                        logger.info("Session reloaded from file during retry")
                    except Exception as reload_exc:
                        logger.warning("Reload session failed: %s", reload_exc)
                        # не прерываем — просто продолжим с увеличенным backoff

                # Sleep with exponential backoff + jitter, but cap to MAX_BACKOFF
                jitter = random.uniform(0, JITTER_MAX)
                sleep_for = min(MAX_BACKOFF, backoff) + jitter
                logger.info("Sleeping %.2fs before retrying (attempt %d)", sleep_for, attempt)
                time.sleep(sleep_for)
                backoff = min(MAX_BACKOFF, backoff * 2)
                continue

            except Exception as e:
                logger.exception("Unexpected error while downloading post")
                raise HTTPException(status_code=400, detail=str(e))

        # если цикл по какой-то причине закончился без результата
        raise HTTPException(status_code=502, detail="Failed to fetch post after retries")

# import os
# import re
# import time
# import threading
# import logging
# import random
# from typing import List, Optional

# import instaloader
# from fastapi import HTTPException

# from app.config import settings
# from app.utils.helpers import extract_shortcode
# from app.schemas.media import MediaItem

# logger = logging.getLogger("instagram_service")
# logger.setLevel(logging.INFO)

# CHALLENGE_REGEX = re.compile(r"https://www\.instagram\.com/challenge/[^\s)'\"]+")

# # Настройки retry / throttle
# MAX_RETRIES = 6
# INITIAL_BACKOFF = 10       # стартовая задержка при rate-limit (сек)
# MAX_BACKOFF = 300          # макс задержка (сек) при экспоненциальном backoff
# MIN_REQUEST_INTERVAL = 8   # минимальное время между запросами к Instagram (сек)
# JITTER_MAX = 2.0           # максимум случайного джиттера (сек)


# class InstagramService:
#     def __init__(self):
#         self.loader = instaloader.Instaloader(
#             dirname_pattern=str(settings.DOWNLOAD_DIR),
#             download_comments=False,
#             save_metadata=False,
#             compress_json=False,
#             download_video_thumbnails=False,
#             quiet=True
#         )

#         # Директории
#         settings.SESSION_DIR.mkdir(parents=True, exist_ok=True)
#         settings.DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

#         # Блокировка для логина
#         self._lock = threading.Lock()
#         self._logged_in = False

#     def _extract_challenge_url(self, text: str) -> Optional[str]:
#         m = CHALLENGE_REGEX.search(text)
#         return m.group(0) if m else None

#     def ensure_logged_in(self, force: bool = False):
#         """
#         Загружает сессию из файла. Не логинится на каждый запрос.
#         """
#         if self._logged_in and not force:
#             return

#         with self._lock:
#             if self._logged_in and not force:
#                 return

#             if not settings.SESSION_FILE.exists():
#                 raise HTTPException(status_code=403, detail="Session file not found. Run create_session.py first")

#             try:
#                 self.loader.load_session_from_file(settings.IG_USERNAME, filename=str(settings.SESSION_FILE))
#                 self._logged_in = True
#                 logger.info("Session loaded successfully")
#             except Exception as e:
#                 logger.exception("Failed to load Instagram session")
#                 raise HTTPException(status_code=500, detail=f"Failed to load session: {e}")

#     def create_session(self):
#         """
#         Ручное создание/обновление сессии.
#         """
#         try:
#             self.ensure_logged_in(force=True)
#             if self._logged_in:
#                 return {"status": "ok", "detail": "Session created/loaded"}
#         except HTTPException:
#             raise
#         except Exception as e:
#             logger.exception("create_session failed")
#             raise HTTPException(status_code=500, detail=f"Failed to create session: {e}")

#     def download_post(self, shortcode: str, download: bool = False):
#         """
#         Возвращает метаданные или скачивает пост на диск.
#         Реализован retry при rate limit.
#         """
#         self.ensure_logged_in()
#         if not self._logged_in:
#             raise HTTPException(status_code=403, detail="Not logged in. Create session first.")

#         shortcode = extract_shortcode(shortcode)
#         backoff = INITIAL_BACKOFF

#         for attempt in range(1, MAX_RETRIES + 1):
#             try:
#                 post = instaloader.Post.from_shortcode(self.loader.context, shortcode)

#                 media: List[MediaItem] = []

#                 if getattr(post, "is_video", False):
#                     media.append(MediaItem(type="video", url=post.video_url))
#                 elif getattr(post, "typename", "") != "GraphSidecar":
#                     media.append(MediaItem(type="image", url=post.url))
#                 else:
#                     for node in post.get_sidecar_nodes():
#                         media.append(MediaItem(
#                             type="video" if getattr(node, "is_video", False) else "image",
#                             url=(node.video_url if getattr(node, "is_video", False) else node.display_url)
#                         ))

#                 if not media:
#                     raise HTTPException(status_code=404, detail="No media found")

#                 if download:
#                     target_dir = settings.DOWNLOAD_DIR / shortcode
#                     target_dir.mkdir(parents=True, exist_ok=True)
#                     logger.info("Downloading post %s into %s", shortcode, target_dir)
#                     self.loader.download_post(post, target=str(target_dir))
#                     return {
#                         "username": post.owner_username,
#                         "status": "downloaded",
#                         "count": len(media),
#                         "path": str(target_dir)
#                     }

#                 return {
#                     "username": post.owner_username,
#                     "status": "success",
#                     "count": len(media),
#                     "media": media
#                 }

#             except instaloader.exceptions.LoginRequiredException:
#                 self._logged_in = False
#                 raise HTTPException(status_code=403, detail="Session expired. Recreate session.")

#             except instaloader.exceptions.PrivateProfileNotFollowedException:
#                 raise HTTPException(status_code=403, detail="Cannot access private profile")

#             except instaloader.exceptions.ConnectionException as e:
#                 logger.warning("Connection error attempt %d/%d: %s", attempt, MAX_RETRIES, e)
#                 if attempt == MAX_RETRIES:
#                     raise HTTPException(status_code=502, detail="Instagram rate limit / network error. " + str(e))
#                 time.sleep(backoff)
#                 backoff *= 2  # экспоненциальная задержка
#                 continue

#             except Exception as e:
#                 logger.exception("Unexpected error while downloading post")
#                 raise HTTPException(status_code=400, detail=str(e))

# # import instaloader
# # from fastapi import HTTPException
# # from app.config import settings
# # from app.utils.helpers import extract_shortcode
# # from app.schemas.media import MediaItem, MediaRequest
# # from typing import List, Dict
# # import os


# # class InstagramService:
# #     def __init__(self):
# #         self.loader = instaloader.Instaloader(
# #             dirname_pattern=settings.DOWNLOAD_DIR,
# #             download_comments=False,
# #             save_metadata=False,
# #             compress_json=False,
# #             download_video_thumbnails=False,
# #             quiet=True,
# #         )
# #         settings.SESSION_DIR.mkdir(parents=True, exist_ok=True)
# #         self._login()
    
# #     def _login(self):
# #         try:
# #             if os.path.exists(settings.SESSION_FILE):
# #                 self.loader.load_session_from_file(
# #                     settings.IG_USERNAME,
# #                     filename=str(settings.SESSION_FILE)
# #                 )
# #                 print("Session loaded successfully.")
# #             else:
# #                 self.loader.login(settings.IG_USERNAME, settings.IG_PASSWORD)
# #                 self.loader.save_session_to_file(
# #                     filename=str(settings.SESSION_FILE)
# #                 )
# #         except Exception as e:
# #             raise HTTPException(status_code=500, detail=f"Instagram login failed: {str(e)}")
        
# #     def download_post(self, shortcode: str):
# #         try:
# #             shortcode = extract_shortcode(shortcode)
# #             post = instaloader.Post.from_shortcode(self.loader.context, shortcode)

# #             media: List[MediaItem] = []

# #             if post.is_video:
# #                 media.append(MediaItem(type="video", url=post.video_url))

# #             elif post.typename != "GraphSidecar":
# #                 media.append(MediaItem(type="image", url=post.url))

# #             else:
# #                 for node in post.get_sidecar_nodes():
# #                     media.append(MediaItem(
# #                         type="video" if node.is_video else "image",
# #                         url=node.video_url if node.is_video else node.display_url
# #                     ))

# #             if not media:
# #                 raise HTTPException(status_code=404, detail="No media found in this post")
            
# #             return {
# #                 "username": post.owner_username,
# #                 "status": "success",
# #                 "count": len(media),
# #                 "media": media,
# #             }
        
# #         except instaloader.exceptions.LoginRequiredException:
# #             raise HTTPException(status_code=403, detail="Login required to access this post")
# #         except instaloader.exceptions.PrivateProfileNotFollowedException:
# #             raise HTTPException(status_code=403, detail="Cannot access private profile")
# #         except Exception as e:
# #             raise HTTPException(status_code=400, detail=str(e))
