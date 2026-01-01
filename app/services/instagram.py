# app/services/instagram.py
import os
import re
import time
import threading
import logging
from typing import List

import instaloader
from fastapi import HTTPException

from app.config import settings
from app.utils.helpers import extract_shortcode
from app.schemas.media import MediaItem

logger = logging.getLogger("instagram_service")
logger.setLevel(logging.INFO)

CHALLENGE_REGEX = re.compile(r"https://www\.instagram\.com/challenge/[^\s)'\"]+")


class InstagramService:
    def __init__(self):
        # Настройка Instaloader (не логинится здесь)
        self.loader = instaloader.Instaloader(
            dirname_pattern=str(settings.DOWNLOAD_DIR),
            download_comments=False,
            save_metadata=False,
            compress_json=False,
            download_video_thumbnails=False,
            quiet=True,
        )

        # Убедимся, что директория для сессий/загрузок существует
        settings.SESSION_DIR.mkdir(parents=True, exist_ok=True)
        settings.DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

        # Блокировка чтобы предотвратить параллельные логины
        self._lock = threading.Lock()
        self._logged_in = False

    def _extract_challenge_url(self, text: str) -> str | None:
        m = CHALLENGE_REGEX.search(text)
        return m.group(0) if m else None

    def _ensure_logged_in(self, force: bool = False):
        """
        Пытается загрузить существующую сессию либо логинится.
        Не выбрасывает исключение при отсутствии credentials — возвращает False.
        """
        if self._logged_in and not force:
            return

        with self._lock:
            if self._logged_in and not force:
                return

            # Попытка загрузить сессию из файла
            try:
                if settings.SESSION_FILE.exists():
                    logger.info("Loading Instagram session from %s", settings.SESSION_FILE)
                    # load_session_from_file(username, filename=...)
                    self.loader.load_session_from_file(settings.IG_USERNAME, filename=str(settings.SESSION_FILE))
                    self._logged_in = True
                    logger.info("Session loaded successfully.")
                    return
            except Exception as e:
                logger.warning("Failed to load session file: %s", e)

            # Если нет файла сессии — попытка логина при наличии creds
            if not settings.IG_USERNAME or not settings.IG_PASSWORD:
                logger.warning("No IG credentials provided; cannot login automatically.")
                self._logged_in = False
                return

            try:
                logger.info("Attempting Instagram login for %s", settings.IG_USERNAME)
                self.loader.login(settings.IG_USERNAME, settings.IG_PASSWORD)
                # Сохраняем сессию в явный файл (чтобы потом использовать на этом же хосте)
                self.loader.save_session_to_file(filename=str(settings.SESSION_FILE))
                self._logged_in = True
                logger.info("Login successful and session saved to %s", settings.SESSION_FILE)
                return
            except instaloader.exceptions.LoginException as e:
                # Если требуется checkpoint — вытащим ссылку и вернём понятную ошибку
                challenge = self._extract_challenge_url(str(e))
                if challenge:
                    logger.error("Instagram checkpoint required: %s", challenge)
                    # Возвращаем 403 с URL, который нужно открыть в браузере
                    raise HTTPException(
                        status_code=403,
                        detail=f"Checkpoint required. Open this URL in a browser and follow instructions: {challenge}"
                    )
                logger.exception("Instagram login failed")
                raise HTTPException(status_code=403, detail=f"Instagram login failed: {str(e)}")
            except Exception as e:
                logger.exception("Unexpected error during Instagram login")
                raise HTTPException(status_code=500, detail="Unexpected error during Instagram login")

    def create_session(self):
        """
        Явно попытаться создать / обновить сессию (подходит для ручного вызова при деплое).
        Вернёт dict с результатом или бросит HTTPException с info о checkpoint.
        """
        try:
            self._ensure_logged_in(force=True)
            if self._logged_in:
                return {"status": "ok", "detail": "Session created/loaded"}
            else:
                raise HTTPException(status_code=403, detail="No credentials available for login")
        except HTTPException:
            raise
        except Exception as e:
            logger.exception("create_session failed")
            raise HTTPException(status_code=500, detail="Failed to create session")

    def download_post(self, shortcode: str, download: bool = False):
        """
        Возвращает метаданные media или скачивает пост на диск, если download=True.
        """
        # Убедимся в логине (если нет — вернём понятную ошибку)
        self._ensure_logged_in()
        if not self._logged_in:
            raise HTTPException(status_code=403, detail="Not logged in. Create session on the server or provide credentials.")

        try:
            shortcode = extract_shortcode(shortcode)
            post = instaloader.Post.from_shortcode(self.loader.context, shortcode)

            media: List[MediaItem] = []

            # Одиночное видео
            if getattr(post, "is_video", False):
                media.append(MediaItem(type="video", url=post.video_url))

            # Одиночное изображение
            elif getattr(post, "typename", "") != "GraphSidecar":
                media.append(MediaItem(type="image", url=post.url))

            # Несколько элементов (sidecar)
            else:
                for node in post.get_sidecar_nodes():
                    media.append(MediaItem(
                        type="video" if getattr(node, "is_video", False) else "image",
                        url=(node.video_url if getattr(node, "is_video", False) else node.display_url)
                    ))

            if not media:
                raise HTTPException(status_code=404, detail="No media found in this post")

            if download:
                # Скачиваем пост в папку <DOWNLOAD_DIR>/<shortcode>
                target_dir = settings.DOWNLOAD_DIR / shortcode
                target_dir.mkdir(parents=True, exist_ok=True)
                # loader.download_post ожидает target как str или path
                logger.info("Downloading post %s into %s", shortcode, target_dir)
                self.loader.download_post(post, target=str(target_dir))
                return {
                    "username": post.owner_username,
                    "status": "downloaded",
                    "count": len(media),
                    "path": str(target_dir)
                }

            # Иначе — просто возвращаем metadata
            return {
                "username": post.owner_username,
                "status": "success",
                "count": len(media),
                "media": media,
            }

        except instaloader.exceptions.PrivateProfileNotFollowedException:
            raise HTTPException(status_code=403, detail="Cannot access private profile")
        except instaloader.exceptions.LoginRequiredException:
            # Если сессия устарела - пометим и вернём понятную ошибку
            self._logged_in = False
            raise HTTPException(status_code=403, detail="Login required to access this post. Please recreate session.")
        except instaloader.exceptions.ConnectionException as e:
            logger.warning("Connection error to Instagram: %s", e)
            raise HTTPException(status_code=502, detail="Instagram network error / rate limit. " + str(e))
        except Exception as e:
            logger.exception("Error while downloading post")
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
