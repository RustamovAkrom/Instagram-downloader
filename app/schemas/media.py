from pydantic import BaseModel

class MediaRequest(BaseModel):
    url: str

class MediaItem(BaseModel):
    type: str  # "image" or "video"
    url: str
