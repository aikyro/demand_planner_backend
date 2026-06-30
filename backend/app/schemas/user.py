from pydantic import BaseModel, EmailStr


class UserOut(BaseModel):
    id: str
    email: EmailStr
    role: str
    full_name: str | None = None
    is_active: bool
    created_at: str | None = None


class UserCreateIn(BaseModel):
    email: EmailStr
    password: str
    role: str = "viewer"
    full_name: str | None = None


class UserPatchIn(BaseModel):
    role: str | None = None
    full_name: str | None = None


class UserStatusIn(BaseModel):
    is_active: bool


class UserDeleteIn(BaseModel):
    user_ids: list[str]
