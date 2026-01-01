from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routers import router as instagram_router


app = FastAPI(title="Instagram Media Downloader API")


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(instagram_router, prefix="/instagram", tags=["Instagram"])

@app.get("/")
async def root():
    return {"message": "Welcome to the Instagram Media Downloader API"}
