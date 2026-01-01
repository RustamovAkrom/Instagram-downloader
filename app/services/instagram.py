import instaloader
from fastapi import HTTPException
from app.config import settings
from app.utils.helpers import extract_shortcode
from app.schemas.media import MediaItem, MediaRequest
from typing import List, Dict
import os


class InstagramService:
    def __init__(self):
        self.loader = instaloader.Instaloader(
            dirname_pattern=settings.DOWNLOAD_DIR,
            download_comments=False,
            save_metadata=False,
            compress_json=False,
            download_video_thumbnails=False,
            quiet=True,
        )
        settings.SESSION_DIR.mkdir(parents=True, exist_ok=True)
        self._login()
    
    def _login(self):
        try:
            if os.path.exists(settings.SESSION_FILE):
                self.loader.load_session_from_file(
                    settings.IG_USERNAME,
                    filename=str(settings.SESSION_FILE)
                )
                print("Session loaded successfully.")
            else:
                self.loader.login(settings.IG_USERNAME, settings.IG_PASSWORD)
                self.loader.save_session_to_file(
                    filename=str(settings.SESSION_FILE)
                )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Instagram login failed: {str(e)}")
        
    def download_post(self, shortcode: str):
        try:
            shortcode = extract_shortcode(shortcode)
            post = instaloader.Post.from_shortcode(self.loader.context, shortcode)

            media: List[MediaItem] = []

            if post.is_video:
                media.append(MediaItem(type="video", url=post.video_url))

            elif post.typename != "GraphSidecar":
                media.append(MediaItem(type="image", url=post.url))

            else:
                for node in post.get_sidecar_nodes():
                    media.append(MediaItem(
                        type="video" if node.is_video else "image",
                        url=node.video_url if node.is_video else node.display_url
                    ))

            if not media:
                raise HTTPException(status_code=404, detail="No media found in this post")
            
            return {
                "username": post.owner_username,
                "status": "success",
                "count": len(media),
                "media": media,
            }
        
        except instaloader.exceptions.LoginRequiredException:
            raise HTTPException(status_code=403, detail="Login required to access this post")
        except instaloader.exceptions.PrivateProfileNotFollowedException:
            raise HTTPException(status_code=403, detail="Cannot access private profile")
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))
