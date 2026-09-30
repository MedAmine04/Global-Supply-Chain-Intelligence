from pydantic import BaseModel


class CopilotQuestion(BaseModel):
    question: str


class CopilotToolCall(BaseModel):
    tool: str
    input: dict
    result: object


class CopilotAnswer(BaseModel):
    answer: str
    tool_calls: list[CopilotToolCall]
