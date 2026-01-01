from fastapi import APIRouter, HTTPException, Query
from app.services.instagram import InstagramService

router = APIRouter()
instagram_service = InstagramService()


@router.post("/download", response_model=dict)
def download_instagram_media(
    url: str = Query(..., description="Instagram post URL to download media from")
):
    """
    Download media (images/videos) from a given Instagram post URL.
    Returns a dictionary containing username, media count, and media items.
    """
    try:
        return instagram_service.download_post(url)
    except HTTPException as he:
        # Пробрасываем ошибки, которые уже корректно обработаны сервисом
        raise he
    except Exception as e:
        # Любые неожиданные ошибки
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected error while processing the request: {str(e)}"
        )
