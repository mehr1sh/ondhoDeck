"""Assistant conversations: general or about one household, answered with the user's own AI provider key.

Conversations are private to their author. A household conversation also requires current membership of that
household, so losing access to a household also hides its conversations.

Sending a message streams the reply as server-sent events:
    event: delta  data: {"text": "..."}                       (repeated)
    event: done   data: {"user_message": {...}, "assistant_message": {...}, "title": "..."}
    event: error  data: {"code": "...", "message": "..."}     (instead of done; nothing is saved)
The user's message and the reply are saved together only when the reply completes.
"""
from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..api_schemas import ChatCreate, ChatDetailOut, ChatMessageIn, ChatMessageOut, ChatOut, ChatUpdate
from ..auth import CurrentUser, get_current_user
from ..authz import require_household
from ..config import Settings, get_settings
from ..db import get_db, session_scope
from ..errors import ApiError
from ..llm import ProviderError
from ..models import ChatConversation, ChatMessage
from ..ratelimit import check_rate
from ..services.assistant import NEW_TITLE, chat_provider, system_prompt, title_from, turns_for

router = APIRouter(tags=["assistant"])
log = logging.getLogger("slipslopes.assistant")


def _get_chat(db: Session, user: CurrentUser, chat_id: uuid.UUID) -> ChatConversation:
    chat = db.get(ChatConversation, chat_id)
    if chat is None or chat.user_id != user.id:
        raise ApiError(404, "not_found", "Conversation not found.")
    if chat.household_id is not None:
        require_household(db, user, chat.household_id)
    return chat


@router.get("/chats", response_model=list[ChatOut])
def list_chats(household_id: Optional[uuid.UUID] = Query(None, description="Omit for general conversations"),
               user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    if household_id is not None:
        require_household(db, user, household_id)
    where = (ChatConversation.household_id == household_id if household_id is not None
             else ChatConversation.household_id.is_(None))
    return db.scalars(select(ChatConversation).where(ChatConversation.user_id == user.id, where)
                      .order_by(ChatConversation.updated_at.desc()).limit(100)).all()


@router.post("/chats", response_model=ChatOut, status_code=201)
def create_chat(body: ChatCreate, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    if body.household_id is not None:
        require_household(db, user, body.household_id)
    chat = ChatConversation(user_id=user.id, household_id=body.household_id, title=NEW_TITLE)
    db.add(chat)
    db.commit()
    db.refresh(chat)
    return chat


@router.get("/chats/{chat_id}", response_model=ChatDetailOut)
def get_chat(chat_id: uuid.UUID, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    return _get_chat(db, user, chat_id)


@router.patch("/chats/{chat_id}", response_model=ChatOut)
def rename_chat(chat_id: uuid.UUID, body: ChatUpdate, user: CurrentUser = Depends(get_current_user),
                db: Session = Depends(get_db)):
    chat = _get_chat(db, user, chat_id)
    chat.title = body.title.strip() or NEW_TITLE
    db.commit()
    db.refresh(chat)
    return chat


@router.delete("/chats/{chat_id}", status_code=204)
def delete_chat(chat_id: uuid.UUID, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    db.delete(_get_chat(db, user, chat_id))
    db.commit()


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


@router.post("/chats/{chat_id}/messages")
def send_message(chat_id: uuid.UUID, body: ChatMessageIn, user: CurrentUser = Depends(get_current_user),
                 db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> StreamingResponse:
    """Stream the assistant's reply (server-sent events; see the module docstring)."""
    chat = _get_chat(db, user, chat_id)
    check_rate(str(user.id), "chat", settings.rate_limit_chat_per_minute, 60)
    provider = chat_provider(db, user.id, settings)  # missing or unusable key: a normal JSON error, before streaming
    system = system_prompt(db, chat)
    turns = turns_for([(m.role, m.content) for m in chat.messages], body.content)
    first = not chat.messages
    sent_at = datetime.now(UTC)

    def events() -> Iterator[str]:
        parts: list[str] = []
        try:
            for delta in provider.stream_chat(system, turns):
                parts.append(delta)
                yield _sse("delta", {"text": delta})
        except ProviderError as exc:  # our own messages; provider text and keys never reach the client
            yield _sse("error", {"code": exc.code, "message": str(exc)})
            return
        except Exception:
            log.exception("assistant reply failed chat_id=%s", chat_id)
            yield _sse("error", {"code": "internal_error", "message": "The assistant could not answer. Try again."})
            return
        reply = "".join(parts).strip()
        if not reply:
            yield _sse("error", {"code": "empty_response", "message": "The model returned an empty reply."})
            return
        with session_scope() as s:
            conv = s.get(ChatConversation, chat_id)
            if conv is None:
                done = None
            else:
                question = ChatMessage(conversation_id=chat_id, role="user", content=body.content, created_at=sent_at)
                answer = ChatMessage(conversation_id=chat_id, role="assistant", content=reply,
                                     provider=provider.name, model=provider.model,
                                     input_tokens=provider.last_usage.input_tokens,
                                     output_tokens=provider.last_usage.output_tokens,
                                     truncated=provider.last_truncated, created_at=datetime.now(UTC))
                s.add_all([question, answer])
                if first and conv.title == NEW_TITLE:
                    conv.title = title_from(body.content)
                conv.updated_at = datetime.now(UTC)
                s.flush()
                done = {"user_message": ChatMessageOut.model_validate(question).model_dump(mode="json"),
                        "assistant_message": ChatMessageOut.model_validate(answer).model_dump(mode="json"),
                        "title": conv.title}
        if done is None:
            yield _sse("error", {"code": "not_found", "message": "The conversation was deleted."})
        else:
            yield _sse("done", done)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
