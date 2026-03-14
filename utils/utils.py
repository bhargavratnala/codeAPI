from enum import Enum
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DOCKERFILES_DIR = BASE_DIR / "dockerfiles"
IMAGES_DIR = BASE_DIR / "images"

class ExecutionStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"
    MEMORY_LIMIT = "memory_limit"
    STOPPED = "stopped"
    ERROR = "error"