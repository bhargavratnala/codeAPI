from pydantic import BaseModel

class CodeExecutionRequest(BaseModel):
    language_id: int
    code: str
    input: str = None
    memory_limit: int = 128
    time_limit: int = 5

class CodeExecutionResponse(BaseModel):
    output: str = None
    error: str = None
    execution_time: int = None
    status: str