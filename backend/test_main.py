from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1 import attendance

app = FastAPI(title="Test API")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routers
app.include_router(attendance.router, prefix="/api/v1/attendance", tags=["attendance"])

@app.get("/")
async def root():
    return {"message": "Test API", "status": "running"}