from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.security import decode_token
from app.services.auth_service import get_user_by_id
from app.services.workspace_service import get_workspace

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
) -> dict:
    if credentials is None:
        raise HTTPException(status_code=401, detail="missing access token")
    try:
        payload = decode_token(credentials.credentials, "access")
    except Exception:
        raise HTTPException(status_code=401, detail="invalid or expired access token")
    user = await get_user_by_id(payload["sub"])
    if not user:
        raise HTTPException(status_code=401, detail="user not found")
    return user


async def require_workspace(workspace_id: str, user: dict = Depends(get_current_user)) -> dict:
    workspace = await get_workspace(workspace_id, user["_id"])
    if not workspace:
        raise HTTPException(status_code=404, detail="workspace not found")
    return workspace
