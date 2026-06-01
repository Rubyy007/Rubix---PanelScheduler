import os
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.routes.bookings import router as bookings_router
from backend.routes.admin import router as admin_router
from backend.sheets_service import SheetsService

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("main")

# Initialize FastAPI App
app = FastAPI(
    title="Mock Interview Panel Allocation System",
    description="Automated panel scheduling platform with Google Sheets backend",
    version="1.0.0"
)

# CORS Setup for direct local development access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- STARTUP EVENT ---

@app.on_event("startup")
async def startup_event():
    """Verify spreadsheet connectivity and initialize worksheets if they do not exist."""
    logger.info("Initializing Mock Panel Allocation Backend Server...")
    sheets = SheetsService()
    connected = sheets.connect_spreadsheet()
    if connected:
        logger.info("Successfully connected to Google Sheets database!")
    else:
        logger.warning(
            "Could not connect to Google Sheets on startup. "
            "Please ensure environment variables or credentials.json are set up correctly."
        )


# --- ROUTE MOUNTING ---

# Mount API routers
app.include_router(bookings_router, prefix="/api")
app.include_router(admin_router, prefix="/api")

# Verify directories exist before mounting static files
static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")

if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
else:
    logger.error(f"Static directory not found at: {static_dir}")

# --- FRONTEND ROUTING (Single Server Architecture) ---

@app.get("/", response_class=FileResponse)
async def serve_index():
    return FileResponse(os.path.join(frontend_dir, "index.html"))

@app.get("/booking", response_class=FileResponse)
async def serve_booking():
    return FileResponse(os.path.join(frontend_dir, "booking.html"))

@app.get("/admin", response_class=FileResponse)
async def serve_admin():
    return FileResponse(os.path.join(frontend_dir, "admin.html"))

@app.get("/dashboard", response_class=FileResponse)
async def serve_dashboard():
    return FileResponse(os.path.join(frontend_dir, "dashboard.html"))
