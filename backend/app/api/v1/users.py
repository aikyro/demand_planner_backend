from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.core.deps import min_role, CurrentUser
from app.schemas.user import UserOut, UserCreateIn, UserPatchIn, UserStatusIn, UserDeleteIn
from app.services.user_service import UserService

router = APIRouter(prefix="/users", tags=["users"])


def _out(u) -> UserOut:
    return UserOut(id=str(u.id), email=u.email, role=u.role,
                   full_name=u.full_name, is_active=u.is_active,
                   created_at=u.created_at.isoformat() if u.created_at else None)


@router.get("", response_model=list[UserOut])
async def list_users(user: CurrentUser = Depends(min_role("admin")),
                     db: AsyncSession = Depends(get_db)):
    return [_out(u) for u in await UserService(db, user.company_id).list()]


@router.post("", response_model=UserOut)
async def create_user(data: UserCreateIn, user: CurrentUser = Depends(min_role("admin")),
                      db: AsyncSession = Depends(get_db)):
    try:
        u = await UserService(db, user.company_id).create(data)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    await db.commit()
    return _out(u)


@router.patch("/{user_id}", response_model=UserOut)
async def patch_user(user_id: str, data: UserPatchIn,
                     user: CurrentUser = Depends(min_role("admin")),
                     db: AsyncSession = Depends(get_db)):
    try:
        u = await UserService(db, user.company_id).patch(user_id, data)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    await db.commit()
    return _out(u)


@router.patch("/{user_id}/status", response_model=UserOut)
async def set_status(user_id: str, data: UserStatusIn,
                     user: CurrentUser = Depends(min_role("admin")),
                     db: AsyncSession = Depends(get_db)):
    try:
        u = await UserService(db, user.company_id).set_status(user_id, data.is_active)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    await db.commit()
    return _out(u)


@router.delete("")
async def delete_users(data: UserDeleteIn,
                    user: CurrentUser = Depends(min_role("admin")),
                    db: AsyncSession = Depends(get_db)):
    try:
        for uid in data.user_ids:
            await UserService(db, user.company_id).delete(uid)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    await db.commit()
    return {"deleted": len(data.user_ids)}
