"""The chat endpoints: the models on offer, the conversations kept, and one
streamed answer.

`POST /api/chat` and `POST /api/chat/cards/{id}` are the only two places in
the API that stream, and the only two that earn it: without it a chat is a
frozen box for several seconds per question, which is the difference between a
conversation and submitting a form. Server-sent events over plain HTTP — one
direction, no WebSocket, no new dependency. Each event is `event: <kind>` plus
one `schemas.ChatEvent` as JSON on the `data:` line.

The second one exists because the stream is one-directional. A card cannot be
answered down the pipe that proposed it, so the answer is a new request against
the stored conversation — which also means a closed browser leaves nothing
pending, and a card nobody ever answered is still there, still saying so.

The question is stored and the context built inside the request, before the
response starts; the answer is stored when the stream ends, in a session of
its own. The request's session is never used from inside the stream.

One card is different, and it is `run_analysis`: three to six model calls, a
minute of them, so its work happens ON the stream and arrives as `step` events.
Everything else about it is unchanged — the decision is still taken before the
first byte, and the reader still hears what the model makes of it afterwards.
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app import chat, crud, models, schemas, tools
from app.database import get_db
from app.routers.deps import get_or_404

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _sse(events: Iterator[schemas.ChatEvent]) -> Iterator[str]:
    """One SSE frame per event. JSON on the data line, so a newline inside the
    model's text cannot break the frame."""
    for event in events:
        yield f"event: {event.kind}\ndata: {event.model_dump_json()}\n\n"


@router.get("/models", response_model=schemas.ChatModelsRead)
def get_models() -> schemas.ChatModelsRead:
    """The model dropdown, default first."""
    return chat.available_models()


@router.get("/conversations", response_model=list[schemas.ChatConversationRead])
def list_conversations(db: Session = Depends(get_db)) -> list[models.ChatConversation]:
    """Every conversation, most recently spoken to first — the history list."""
    return crud.get_chat_conversations(db)


@router.get("/conversations/{conversation_id}", response_model=schemas.ChatConversationDetail)
def get_conversation(
    conversation_id: int, db: Session = Depends(get_db)
) -> schemas.ChatConversationDetail:
    """One conversation with every turn, oldest first, each card in the
    reader's words (`tools.present`), as the stream sends it."""
    detail = schemas.ChatConversationDetail.model_validate(
        get_or_404(db, models.ChatConversation, conversation_id)
    )
    for message in detail.messages:
        message.blocks = [
            schemas.ChatCardBlock(**tools.present(block.model_dump(mode="json")))
            if isinstance(block, schemas.ChatCardBlock)
            else block
            for block in message.blocks
        ]
    return detail


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(conversation_id: int, db: Session = Depends(get_db)) -> None:
    """Forget a conversation and every turn in it."""
    get_or_404(db, models.ChatConversation, conversation_id)
    crud.delete_chat_conversation(db, conversation_id)


# Named once and used by both streaming routes, so the event shapes reach the
# frontend's generated types from either. FastAPI files the schema under
# application/json; the event-stream entry beside it says what actually
# arrives.
_STREAMS = {
    200: {
        "model": schemas.ChatEvent,
        "content": {"text/event-stream": {}},
        "description": (
            "Server-sent events: `start`, then "
            "`decided`/`thought`/`delta`/`tool`/`source`/`step`/`card` as "
            "they happen, then exactly one `done` or one `error`."
        ),
    }
}


def _stream(events: Iterator[schemas.ChatEvent]) -> StreamingResponse:
    """One streamed answer, with the headers that keep it a stream."""
    return StreamingResponse(
        _sse(events),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # A proxy that buffers a stream turns it back into a frozen box.
            "X-Accel-Buffering": "no",
        },
    )


@router.post("", response_class=StreamingResponse, responses=_STREAMS)
def send(payload: schemas.ChatRequest, db: Session = Depends(get_db)) -> StreamingResponse:
    """Ask one more question, streaming the reply. No conversation id opens a
    new conversation; the `start` event says which.

    Configuration problems (no key, no package) arrive as an `error` event
    rather than a 503: the client has one path for "this stopped, and here is
    why", whichever moment it stopped at. A conversation that does not exist
    is the one thing refused before the stream: there is nowhere to store the
    question."""
    try:
        turn = chat.prepare(db, payload)
    except LookupError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Chat conversation {payload.conversation_id} not found",
        )
    return _stream(chat.stream(turn))


@router.post(
    "/cards/{card_id}", response_class=StreamingResponse, responses=_STREAMS
)
def decide(
    card_id: str, payload: schemas.ChatCardDecision, db: Session = Depends(get_db)
) -> StreamingResponse:
    """Confirm or reject one proposed write, and stream what the model says
    about it.

    On confirm the tool runs first, inside one unit of work with the record of
    it, so the card cannot end up reading "confirmed" over a write that rolled
    back. Only then does the stream start. The analyzer is the exception and
    keeps the guarantee that matters: its run is written before its card is
    settled, so the ordering can fail into a run no receipt names and never
    into a receipt over a run that did not happen.

    Three refusals, all of them BEFORE the first byte, because a refusal
    arriving mid-stream is one the client has to fish out of an event — except
    for the analyzer, whose work is a minute long and therefore happens ON the
    stream. Its card is still checked here and cannot be decided twice; what
    moves is only the running, and a refusal that surfaces after it started
    arrives as an `error` event, because by then there is no status line left
    to send:

      404  no card with that id
      409  it has already been confirmed or rejected — a decision is taken
           once, and a second confirm would write the row twice
      409  it is stale: what it was drawn against has moved since it was
           proposed, so what the card says would happen is no longer what
           would happen

    Anything the model itself fails at afterwards arrives as an `error` event,
    the same as any other turn — by then the write has happened and the reader
    is owed the stream, not a status code. Which is why the stream says the
    decision first: `decided`, the card as stored, right after `start` (for
    the analyzer, once its run is stored), so a failure after it cannot leave
    the card looking undecided.
    """
    try:
        turn = chat.resume(db, card_id, payload)
    except chat.CardGone:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Chat card {card_id} not found"
        )
    except chat.CardStale as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except chat.CardSettled as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"That card was already {exc}. A decision is taken once.",
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return _stream(chat.stream(turn))
