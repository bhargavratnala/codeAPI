from celery import states
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from schema import CodeExecutionRequest
from models import ExecutionResultModel, LanguageModel, get_db
from worker import app as celery_app, execute_code, get_stop_request_key
from utils import redis_client, ExecutionStatus

router = APIRouter(prefix="/execute", tags=["execute"])


def _normalize_status(task_state: str, result_payload: dict | None = None) -> str:
    if result_payload and isinstance(result_payload, dict) and result_payload.get("status"):
        return result_payload["status"]

    state_map = {
        states.PENDING: "pending",
        states.RECEIVED: "pending",
        states.STARTED: "running",
        states.RETRY: "running",
        states.SUCCESS: "success",
        states.FAILURE: "error",
        states.REVOKED: "failure",
    }
    return state_map.get(task_state, "pending")


@router.post("/")
async def start_execution(request: CodeExecutionRequest, db: Session = Depends(get_db)):
    language = db.query(LanguageModel).filter(LanguageModel.id == request.language_id).first()
    if not language:
        raise HTTPException(status_code=404, detail="Language not found")

    task = execute_code.delay(
        language_id=request.language_id,
        code=request.code,
        input_data=request.input,
        time_limit=request.time_limit,
        memory_limit=request.memory_limit,
    )

    execution_result = ExecutionResultModel(
        task_id=task.id,
        language_id=request.language_id,
        code=request.code,
        input=request.input,
        status=ExecutionStatus.PENDING.value,
    )
    db.add(execution_result)
    db.commit()
    db.refresh(execution_result)

    return {
        "execution_id": execution_result.id,
        "task_id": task.id,
        "status": "pending",
        "message": "Execution started",
    }


@router.get("/{task_id}")
async def get_execution_result(task_id: str, db: Session = Depends(get_db)):
    task = celery_app.AsyncResult(task_id)
    task_state = task.state
    execution_result = db.query(ExecutionResultModel).filter(ExecutionResultModel.task_id == task_id).first()

    if task_state == states.PENDING and task.result is None:
        return {
            "execution_id": execution_result.id if execution_result else None,
            "task_id": task_id,
            "task_state": task_state,
            "ready": False,
            "status": execution_result.status if execution_result else "pending",
            "output": execution_result.output if execution_result else None,
            "error": execution_result.error if execution_result else None,
            "execution_time": execution_result.execution_time if execution_result else None,
        }

    if task_state == states.FAILURE:
        return {
            "execution_id": execution_result.id if execution_result else None,
            "task_id": task_id,
            "task_state": task_state,
            "ready": True,
            "status": execution_result.status if execution_result else "error",
            "output": execution_result.output if execution_result else None,
            "error": execution_result.error if execution_result else str(task.result),
            "execution_time": execution_result.execution_time if execution_result else None,
        }

    result_payload = task.result if isinstance(task.result, dict) else {}
    return {
        "execution_id": execution_result.id if execution_result else None,
        "task_id": task_id,
        "task_state": task_state,
        "ready": task.ready(),
        "status": execution_result.status if execution_result else _normalize_status(task_state, result_payload),
        "output": execution_result.output if execution_result else result_payload.get("output"),
        "error": execution_result.error if execution_result else result_payload.get("error"),
        "execution_time": execution_result.execution_time if execution_result else result_payload.get("execution_time"),
    }


@router.post("/{task_id}/stop")
async def force_stop_execution(task_id: str, db: Session = Depends(get_db)):
    task = celery_app.AsyncResult(task_id)

    if task.state in {states.SUCCESS, states.FAILURE, states.REVOKED}:
        raise HTTPException(status_code=400, detail=f"Task is already finished with state {task.state}")

    redis_client.set(get_stop_request_key(task_id), "1", ex=300)
    celery_app.control.revoke(task_id, terminate=True)

    execution_result = db.query(ExecutionResultModel).filter(ExecutionResultModel.task_id == task_id).first()
    if execution_result and execution_result.status in {
        ExecutionStatus.PENDING.value,
        ExecutionStatus.RUNNING.value,
    }:
        execution_result.status = ExecutionStatus.STOPPED.value
        execution_result.error = "Force stop requested"
        db.commit()

    return {
        "task_id": task_id,
        "status": "stopping",
        "message": "Force stop requested",
    }
