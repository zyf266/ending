"""认证 API"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backpack_quant_trading.database.models import DatabaseManager
from backpack_quant_trading.api.deps import (
    get_password_hash,
    verify_password,
    create_access_token,
    get_current_user,
    require_user,
)

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    id: int
    username: str
    role: str


@router.post("/login")
def login(req: LoginRequest):
    db = DatabaseManager()
    user = db.get_user_by_username(req.username)
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = create_access_token({"sub": str(user.id)})
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {"id": user.id, "username": user.username, "role": user.role},
    }


@router.post("/register")
def register(req: RegisterRequest):
    if not req.username or not req.password:
        raise HTTPException(status_code=400, detail="用户名和密码不能为空")
    db = DatabaseManager()
    if db.get_user_by_username(req.username):
        raise HTTPException(status_code=400, detail="用户名已存在")
    try:
        session = db.get_session()
        from backpack_quant_trading.database.models import User
        has_user = session.query(User).first() is not None
        session.close()
        role = "user" if has_user else "superuser"
    except Exception:
        role = "user"
    user = db.create_user(req.username, get_password_hash(req.password), role=role)
    token = create_access_token({"sub": str(user.id)})
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {"id": user.id, "username": user.username, "role": user.role},
    }


@router.get("/me", response_model=UserResponse)
def me(user: dict = Depends(require_user)):
    return user


@router.post("/logout")
def logout():
    return {"message": "ok"}
