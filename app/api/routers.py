from fastapi import APIRouter, HTTPException, Query
from app.services.instagram import InstagramService
from app.services.task_manager import submit_task, get_task_result
from app.schemas.media import MediaRequest

router = APIRouter()
instagram_service = InstagramService()


@router.post("/download", response_model=dict)
def download_instagram_media(
    request: MediaRequest
):
    try:
        task_id = submit_task(instagram_service.download_post, request.url, request.download)
        return {"status": "submitted", "task_id": task_id}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected error while processing the request: {str(e)}"
        )


@router.get("/task/{task_id}/results", response_model=dict)
def check_task(task_id: str):
    return get_task_result(task_id)
