from pathlib import Path
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent.parent
DOCKERFILES_DIR = BASE_DIR / "dockerfiles"

class Language(BaseModel):
    id: int | None = None
    name: str
    version: str
    description: str | None = None
    command: str | None = None

    class Config:
        from_attributes = True

class LanguageDisplay(BaseModel):
    name: str
    version: str
    description: str | None = None

class LanguageDocker(Language):
    dockerfile: str

    def get_dockerfile_path(self) -> Path:
        return DOCKERFILES_DIR / self.dockerfile

class LanguageList(BaseModel):
    languages: list[Language]

    class Config:
        from_attributes = True
