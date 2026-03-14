from celery import Celery
import io
import os, docker
import tarfile
from time import monotonic
import requests
from models import ExecutionResultModel, LanguageModel, get_db
from utils import DOCKERFILES_DIR, get_logger, ExecutionStatus, redis_client

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

app = Celery(
    "worker",
    broker=REDIS_URL,
    backend=REDIS_URL
)

app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_track_started=True,
    result_expires=3600,
)

logger = get_logger(__name__)

STOP_REQUEST_KEY_PREFIX = "execution:stop:"


def get_stop_request_key(task_id: str) -> str:
    return f"{STOP_REQUEST_KEY_PREFIX}{task_id}"

def _build_files_archive(files: dict[str, str]) -> bytes:
    archive_buffer = io.BytesIO()
    with tarfile.open(fileobj=archive_buffer, mode="w") as tar:
        for file_name, content in files.items():
            data = content.encode("utf-8")
            tar_info = tarfile.TarInfo(name=file_name)
            tar_info.size = len(data)
            tar.addfile(tar_info, io.BytesIO(data))
    archive_buffer.seek(0)
    return archive_buffer.read()


@app.task(bind=True)
def execute_code(self, language_id, code, input_data, time_limit=5, memory_limit=128):
    db = next(get_db())
    task_id = self.request.id

    try:
        execution_result = None
        if task_id:
            execution_result = db.query(ExecutionResultModel).filter(ExecutionResultModel.task_id == task_id).first()
            if execution_result:
                execution_result.status = ExecutionStatus.RUNNING.value
                db.commit()

        if task_id and redis_client.get(get_stop_request_key(task_id)):
            if execution_result:
                execution_result.status = ExecutionStatus.STOPPED.value
                execution_result.error = "Execution force stopped"
                db.commit()
            return {
                "status": ExecutionStatus.STOPPED.value,
                "output": "Execution force stopped",
            }

        client = docker.from_env(timeout=max(10, int(time_limit) + 5))

        language = db.query(LanguageModel).filter(
            LanguageModel.id == language_id
        ).first()

        if not language:
            logger.error(f"Language with ID {language_id} not found")
            if execution_result:
                execution_result.status = ExecutionStatus.ERROR.value
                execution_result.error = "Language not found"
                db.commit()
            return {"status": ExecutionStatus.ERROR.value, "output": "Language not found"}

        image_name = language.image_name or f"codeapi_{language.name.lower()}"

        logger.info(f"Starting execution for task {task_id} with language {language.name}")
        logger.debug(f"Code:\n{code}\nInput:\n{input_data}")

        container = client.containers.create(
            image=image_name,
            command=["sh", "-c", language.command],
            working_dir="/app",
            detach=True,
            mem_limit=f"{memory_limit}m",
            network_disabled=True,
            pids_limit=64,
            cpu_period=100000,
            cpu_quota=50000,
        )

        try:
            files_archive = _build_files_archive(
                {
                    "code": code,
                    "input": input_data or "",
                }
            )
            container.put_archive("/app", files_archive)
            container.start()

            start_time = monotonic()

            while True:
                if task_id and redis_client.get(get_stop_request_key(task_id)):
                    container.kill()
                    logs = "Execution force stopped"
                    status = ExecutionStatus.STOPPED.value
                    break

                if monotonic() - start_time > time_limit:
                    container.kill()
                    logs = "Time limit exceeded"
                    status = ExecutionStatus.TIMEOUT.value
                    break

                try:
                    result = container.wait(timeout=1)
                    try:
                        logs = container.logs().decode("utf-8")
                    except requests.exceptions.ReadTimeout:
                        logs = "Execution completed, but fetching logs timed out"
                    if result["StatusCode"] != 0:
                        logger.error(f"Execution failed with status code {result['StatusCode']}. Result:\n{result}\nLogs:\n{logs}", )
                        status = ExecutionStatus.MEMORY_LIMIT.value if result["StatusCode"] == 137 else ExecutionStatus.FAILURE.value
                    else:
                        status = ExecutionStatus.SUCCESS.value
                    break
                except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError):
                    continue

        finally:
            if task_id:
                redis_client.delete(get_stop_request_key(task_id))
            container.remove(force=True)

        execution_time = int((monotonic() - start_time) * 1000)
        if task_id:
            execution_result = db.query(ExecutionResultModel).filter(ExecutionResultModel.task_id == task_id).first()
            if execution_result:
                execution_result.status = status
                execution_result.output = logs
                execution_result.error = None if status == ExecutionStatus.SUCCESS.value else logs
                execution_result.execution_time = execution_time
                db.commit()

        return {
            "status": status,
            "output": logs,
            "execution_time": execution_time,
        }

    except Exception as e:
        logger.error(f"Execution error: {e}", exc_info=True)
        execution_result = None
        if task_id:
            execution_result = db.query(ExecutionResultModel).filter(ExecutionResultModel.task_id == task_id).first()
            if execution_result:
                execution_result.status = ExecutionStatus.ERROR.value
                execution_result.error = str(e)
                db.commit()
        return {
            "status": ExecutionStatus.ERROR.value,
            "output": str(e),
        }

    finally:
        db.close()

@app.task
def build_language_image(language_id):
    db = next(get_db())
    try:
        client = docker.from_env()
        language = db.query(LanguageModel).filter(LanguageModel.id == language_id).first()
        if not language:
            logger.error(f"Language with ID {language_id} not found")
            return
        image_name = f"codeapi_{language.name.lower()}"
        dockerfile_path = DOCKERFILES_DIR / f"Dockerfile.{language.name.lower()}"

        logger.info(f"Building image for language {language.name} using Dockerfile at {dockerfile_path}")
        image, build_logs = client.images.build(path=str(DOCKERFILES_DIR), dockerfile=dockerfile_path.name, tag=image_name)
        logger.info(f"Successfully built image {image_name} for language {language.name}")
        language.image_name = image_name
        logs = []
        for chunk in build_logs:
            if "stream" in chunk:
                logs.append(chunk["stream"])

        language.build_logs = "".join(logs)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Error building image for {language_id}: {e}")
    finally:
        db.close()
