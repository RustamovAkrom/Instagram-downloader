from fastapi import APIRouter, HTTPException
from app.services.instagram import InstagramService


router = APIRouter()
instagram_service = InstagramService()


@router.post("/download", response_model=dict)
def download_instagram_media(url: str):
    try:
        result = instagram_service.download_post(url)
        return result
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail="An error occurred while processing the request.")
