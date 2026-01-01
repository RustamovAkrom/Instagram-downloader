from pydantic import BaseModel

class MediaRequest(BaseModel):
    url: str
    download: bool = False
    

class MediaItem(BaseModel):
    type: str  # "image" or "video"
    url: str
