import os

from sqlalchemy import Column, Integer, String, ForeignKey, create_engine, inspect, text
from sqlalchemy.orm import relationship, sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from utils import ExecutionStatus

Base = declarative_base()

class LanguageModel(Base):
    __tablename__ = 'languages'

    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    version = Column(String, nullable=False)
    dockerfile = Column(String, nullable=False)
    description = Column(String, nullable=True)
    command = Column(String, nullable=False, default="python3 /app/code < /app/input")
    image_name = Column(String, nullable=True)
    build_logs = Column(String, nullable=True)

class ExecutionResultModel(Base):
    __tablename__ = 'execution_results'

    id = Column(Integer, primary_key=True)
    task_id = Column(String, nullable=True, index=True)
    language_id = Column(Integer, ForeignKey('languages.id', ondelete='CASCADE'), nullable=False)
    code = Column(String, nullable=False)
    input = Column(String, nullable=True)
    output = Column(String, nullable=True)
    error = Column(String, nullable=True)
    status = Column(String, nullable=False, default=ExecutionStatus.PENDING.value)
    execution_time = Column(Integer, nullable=True)


DATABASE_HOST = os.getenv('DATABASE_HOST', 'localhost')
DATABASE_PORT = os.getenv('DATABASE_PORT', '5432')
DATABASE_USER = os.getenv('DATABASE_USER', 'postgres')
DATABASE_PASSWORD = os.getenv('DATABASE_PASSWORD', 'password')
DATABASE_NAME = os.getenv('DATABASE_NAME', 'codeapi')

POSTGRESQL_URL = f"postgresql://{DATABASE_USER}:{DATABASE_PASSWORD}@{DATABASE_HOST}:{DATABASE_PORT}/{DATABASE_NAME}"

engine = create_engine(POSTGRESQL_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)
    with engine.begin() as connection:
        language_columns = {column["name"] for column in inspector.get_columns("languages")}
        if "command" not in language_columns:
            connection.execute(
                text(
                    "ALTER TABLE languages "
                    "ADD COLUMN command VARCHAR NOT NULL DEFAULT 'python3 /app/code < /app/input'"
                )
            )

        execution_columns = {column["name"] for column in inspector.get_columns("execution_results")}
        if "task_id" not in execution_columns:
            connection.execute(
                text(
                    "ALTER TABLE execution_results "
                    "ADD COLUMN task_id VARCHAR NULL"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_execution_results_task_id "
                    "ON execution_results (task_id)"
                )
            )

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
