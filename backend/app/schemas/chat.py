import uuid
from datetime import datetime
from pydantic import BaseModel


class ChatRoomCreate(BaseModel):
    name: str
    description: str | None = None


class ChatRoomResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    created_by: uuid.UUID
    created_at: datetime

    model_config = {"from_attributes": True}


class ChatMessageResponse(BaseModel):
    id: uuid.UUID
    room_id: uuid.UUID
    user_id: uuid.UUID
    username: str
    content: str
    created_at: datetime
