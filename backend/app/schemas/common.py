from pydantic import BaseModel


class PaginatedResponse(BaseModel):
    total: int
    page: int = 1
    limit: int = 20


class MessageResponse(BaseModel):
    message: str
