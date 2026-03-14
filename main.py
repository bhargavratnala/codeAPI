from contextlib import asynccontextmanager
from fastapi import FastAPI
from routes import language_router, execute_router
from models import init_db
from utils import get_logger

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup code
    app.logger.info("Starting up CodeAPI...")
    init_db()
    yield
    # Shutdown code
    app.logger.info("Shutting down CodeAPI...")

logger = get_logger(__name__)

app = FastAPI(
    title="CodeAPI",
    description="API provider to run and execute code snippets in various programming languages.",
    version="1.0.0",
    lifespan=lifespan,
)

app.logger = logger

@app.get("/health")
async def health_check():
    return {"status": "ok"}

@app.get("")
async def root():
    return {"message": "Welcome to CodeAPI! Use /docs for API documentation."}

app.include_router(execute_router)
app.include_router(language_router)