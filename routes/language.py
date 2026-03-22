from typing import Annotated
from fastapi import APIRouter, Depends, File, UploadFile, Form, HTTPException
from sqlalchemy.orm import Session
from models import LanguageModel, get_db
from schema import LanguageList, Language, LanguageDisplay
import shutil
from worker import build_language_image
from utils import DOCKERFILES_DIR

router = APIRouter(prefix="/language", tags=["language"])

@router.get("/")
async def list_languages(db: Session = Depends(get_db)):
    languages = [Language.model_validate(language) for language in db.query(LanguageModel).all()]
    return LanguageList(languages=languages)

@router.post("/")
async def create_language(
    name: Annotated[str, Form(...)],
    version: Annotated[str, Form(...)],
    command: Annotated[str, Form(...)],
    dockerfile: Annotated[UploadFile, File(...)],
    description: Annotated[str | None, Form()] = None,
    db: Session = Depends(get_db)
):
    
    language_exists = db.query(LanguageModel).filter(
        LanguageModel.name == name
    ).first()

    if language_exists:
        return {"error": "Language already exists"}

    dockerfile_path = DOCKERFILES_DIR / f"Dockerfile.{name.lower()}"

    with open(dockerfile_path, "wb") as buffer:
        shutil.copyfileobj(dockerfile.file, buffer)

    db_language = LanguageModel(
        name=name,
        version=version,
        command=command,
        description=description,
        dockerfile=dockerfile_path.name
    )

    db.add(db_language)
    db.commit()
    db.refresh(db_language)
    build_language_image.delay(db_language.id)

    return Language.model_validate(db_language)

@router.get("/{id:int}")
async def get_language(id: int, db: Session = Depends(get_db)):
    language = db.query(LanguageModel).filter(LanguageModel.id == id).first()
    if not language:
        return {"error": "Language not found"}
    return Language.model_validate(language)

@router.delete("/{id:int}")
async def delete_language(id: int, db: Session = Depends(get_db)):
    language = db.query(LanguageModel).filter(LanguageModel.id == id).first()
    if not language:
        raise HTTPException(status_code=404, detail="Language not found")

    dockerfile_path = DOCKERFILES_DIR / language.dockerfile
    image_name = language.image_name or f"codeapi_{language.name.lower()}"
    image_archive_paths = (
        DOCKERFILES_DIR / f"{image_name}.tar",
        DOCKERFILES_DIR / image_name,
    )

    db.delete(language)
    db.commit()

    for file_path in (dockerfile_path, *image_archive_paths):
        if file_path.exists():
            file_path.unlink()

    return {"message": "Language deleted successfully", "id": id}
