from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user
from app.models.schemas import LoginIn, RefreshIn, RegisterIn, TokenPair, UserOut
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenPair, status_code=201)
async def register(payload: RegisterIn) -> TokenPair:
    try:
        tokens = await auth_service.signup(payload.email, payload.password, payload.name)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return TokenPair(**tokens)


@router.post("/login", response_model=TokenPair)
async def login(payload: LoginIn) -> TokenPair:
    try:
        tokens = await auth_service.login(payload.email, payload.password)
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    return TokenPair(**tokens)


@router.post("/refresh", response_model=TokenPair)
async def refresh(payload: RefreshIn) -> TokenPair:
    try:
        tokens = await auth_service.refresh_tokens(payload.refresh_token)
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    return TokenPair(**tokens)


@router.get("/me", response_model=UserOut)
async def me(user: dict = Depends(get_current_user)) -> UserOut:
    return UserOut(
        id=user["_id"], email=user["email"], name=user["name"], created_at=user["created_at"]
    )
