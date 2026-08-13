import math
import time
from collections import deque
from threading import Lock

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.security import create_access_token, hash_password, verify_password
from app.db.session import get_db
from app.models.user import User
from app.schemas.user import LoginRequest, LoginResponse, RegisterRequest, UserResponse

router = APIRouter(prefix="/auth", tags=["Authentication"])

LOGIN_RATE_LIMIT_MAX_ATTEMPTS = 5
LOGIN_RATE_LIMIT_WINDOW_SECONDS = 300

_login_failures: dict[tuple[str, str], deque[float]] = {}
_login_failures_lock = Lock()


def _login_rate_limit_key(request: Request, email: str) -> tuple[str, str]:
    client_ip = request.client.host if request.client else "unknown"
    return email.strip().lower(), client_ip


def _prune_login_failures(key: tuple[str, str], now: float) -> deque[float]:
    failures = _login_failures.setdefault(key, deque())
    cutoff = now - LOGIN_RATE_LIMIT_WINDOW_SECONDS
    while failures and failures[0] <= cutoff:
        failures.popleft()
    if not failures:
        _login_failures.pop(key, None)
        return deque()
    return failures


def _retry_after_seconds(key: tuple[str, str], now: float) -> int | None:
    with _login_failures_lock:
        failures = _prune_login_failures(key, now)
        if len(failures) < LOGIN_RATE_LIMIT_MAX_ATTEMPTS:
            return None
        return max(1, math.ceil(LOGIN_RATE_LIMIT_WINDOW_SECONDS - (now - failures[0])))


def _record_login_failure(key: tuple[str, str], now: float) -> None:
    with _login_failures_lock:
        failures = _prune_login_failures(key, now)
        if not failures:
            failures = _login_failures.setdefault(key, deque())
        failures.append(now)


def _clear_login_failures(key: tuple[str, str]) -> None:
    with _login_failures_lock:
        _login_failures.pop(key, None)


def reset_login_rate_limit() -> None:
    """Clear process-local login failures; intended for tests and controlled resets."""
    with _login_failures_lock:
        _login_failures.clear()


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    rate_limit_key = _login_rate_limit_key(request, body.email)
    now = time.monotonic()
    retry_after = _retry_after_seconds(rate_limit_key, now)
    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Quá nhiều lần đăng nhập không thành công. Vui lòng thử lại sau.",
            headers={"Retry-After": str(retry_after)},
        )

    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(body.password, user.password_hash):
        _record_login_failure(rate_limit_key, now)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email hoặc mật khẩu không đúng",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tài khoản đã bị khóa",
        )

    _clear_login_failures(rate_limit_key)
    access_token = create_access_token({"user_id": user.id, "email": user.email, "role": user.role})

    return LoginResponse(
        access_token=access_token,
        user=UserResponse.model_validate(user),
    )


@router.post("/register", response_model=LoginResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    if len(body.password) < 8:
        raise HTTPException(status_code=422, detail="Mật khẩu phải có ít nhất 8 ký tự")

    existing = await db.execute(select(User).where(User.email == body.email.strip().lower()))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email đã được sử dụng")

    user = User(
        email=body.email.strip().lower(),
        password_hash=hash_password(body.password),
        full_name=body.full_name.strip(),
        phone=body.phone,
        role="admin",
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    access_token = create_access_token({"user_id": user.id, "email": user.email, "role": user.role})
    return LoginResponse(access_token=access_token, user=UserResponse.model_validate(user))


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    return UserResponse.model_validate(current_user)
