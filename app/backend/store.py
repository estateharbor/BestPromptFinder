"""
Data access for votes and saved libraries — backed by SQLAlchemy (db.py).

Keeps the same vote interface the recommender expects (init / add_vote / stats / stats_all)
so `matcher.py` is unchanged, and adds per-user library operations.
"""
from sqlalchemy import select, func, delete
from db import SessionLocal, Vote, SavedPrompt, init_db


def init():
    init_db()


# ---- votes (Reliability flywheel) ----
def add_vote(prompt_id: str, verdict: str, model: str = "", user_id: int = None) -> None:
    if verdict not in ("worked", "didnt"):
        raise ValueError("verdict must be 'worked' or 'didnt'")
    with SessionLocal() as s:
        s.add(Vote(prompt_id=prompt_id, verdict=verdict, model=model or "", user_id=user_id))
        s.commit()


def stats(prompt_id: str) -> dict:
    with SessionLocal() as s:
        rows = s.execute(
            select(Vote.verdict, func.count()).where(Vote.prompt_id == prompt_id).group_by(Vote.verdict)
        ).all()
    d = {v: n for v, n in rows}
    return {"worked": d.get("worked", 0), "didnt": d.get("didnt", 0)}


def stats_all() -> dict:
    with SessionLocal() as s:
        rows = s.execute(select(Vote.prompt_id, Vote.verdict, func.count()).group_by(Vote.prompt_id, Vote.verdict)).all()
    out: dict = {}
    for pid, verdict, n in rows:
        out.setdefault(pid, {"worked": 0, "didnt": 0})[verdict] = n
    return out


# ---- per-user saved library ----
def library_ids(user_id: int) -> list:
    with SessionLocal() as s:
        rows = s.execute(
            select(SavedPrompt.prompt_id).where(SavedPrompt.user_id == user_id).order_by(SavedPrompt.saved_at.desc())
        ).all()
    return [r[0] for r in rows]


def save_prompt(user_id: int, prompt_id: str, note: str = "") -> bool:
    with SessionLocal() as s:
        exists = s.execute(
            select(SavedPrompt.id).where(SavedPrompt.user_id == user_id, SavedPrompt.prompt_id == prompt_id)
        ).first()
        if exists:
            return False
        s.add(SavedPrompt(user_id=user_id, prompt_id=prompt_id, note=note))
        s.commit()
        return True


def unsave_prompt(user_id: int, prompt_id: str) -> None:
    with SessionLocal() as s:
        s.execute(delete(SavedPrompt).where(SavedPrompt.user_id == user_id, SavedPrompt.prompt_id == prompt_id))
        s.commit()
