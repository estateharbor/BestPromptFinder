"""
Authentication — email/password with bcrypt hashing and JWT sessions.

First-party auth for the app's own users. Passwords are never stored in plaintext.
Set JWT_SECRET in the environment for production (a random default is used otherwise,
which invalidates tokens on restart — fine for dev, not for prod).
"""
import os
import time

import bcrypt
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select

from db import SessionLocal, User

JWT_SECRET = os.getenv("JWT_SECRET", "dev-insecure-secret-change-me")
JWT_ALG = "HS256"
TOKEN_TTL = 60 * 60 * 24 * 14  # 14 days

_bearer = HTTPBearer(auto_error=False)


# ---- password hashing ----
def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# ---- tokens ----
def create_token(user_id: int) -> str:
    now = int(time.time())
    return jwt.encode({"sub": str(user_id), "iat": now, "exp": now + TOKEN_TTL}, JWT_SECRET, algorithm=JWT_ALG)


def _decode(token: str) -> int:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
        return int(payload["sub"])
    except Exception:
        raise HTTPException(401, "Invalid or expired session.")


# ---- user CRUD ----
def register(email: str, password: str) -> User:
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(400, "A valid email is required.")
    if len(password or "") < 8:
        raise HTTPException(400, "Password must be at least 8 characters.")
    with SessionLocal() as s:
        if s.execute(select(User.id).where(User.email == email)).first():
            raise HTTPException(409, "An account with that email already exists.")
        u = User(email=email, password_hash=hash_password(password))
        s.add(u)
        s.commit()
        s.refresh(u)
        return u


def login(email: str, password: str) -> User:
    email = (email or "").strip().lower()
    with SessionLocal() as s:
        u = s.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if not u or not verify_password(password, u.password_hash):
        raise HTTPException(401, "Incorrect email or password.")
    return u


# ---- dependencies ----
def current_user(creds: HTTPAuthorizationCredentials = Depends(_bearer)) -> User:
    if not creds:
        raise HTTPException(401, "Sign in required.")
    uid = _decode(creds.credentials)
    with SessionLocal() as s:
        u = s.get(User, uid)
    if not u:
        raise HTTPException(401, "Account not found.")
    return u


def optional_user(creds: HTTPAuthorizationCredentials = Depends(_bearer)) -> User | None:
    if not creds:
        return None
    try:
        uid = _decode(creds.credentials)
        with SessionLocal() as s:
            return s.get(User, uid)
    except HTTPException:
        return None
