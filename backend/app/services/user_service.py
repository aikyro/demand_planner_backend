from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import User
from app.core.security import hash_password

VALID_ROLES = {"admin", "planner", "analyst", "viewer"}


class UserService:
    def __init__(self, db: AsyncSession, company_id: str):
        self.db = db
        self.company_id = company_id

    async def list(self):
        return (
            await self.db.execute(select(User).where(User.company_id == self.company_id))
        ).scalars().all()

    async def _get(self, user_id: str) -> User | None:
        return (
            await self.db.execute(
                select(User).where(User.id == user_id, User.company_id == self.company_id)
            )
        ).scalar_one_or_none()

    async def create(self, data) -> User:
        if data.role not in VALID_ROLES:
            raise ValueError("Invalid role")
        user = User(
            company_id=self.company_id, email=data.email,
            password_hash=hash_password(data.password),
            role=data.role, full_name=data.full_name,
        )
        self.db.add(user)
        await self.db.flush()
        return user

    async def patch(self, user_id: str, data) -> User:
        user = await self._get(user_id)
        if not user:
            raise ValueError("User not found")
        if data.role is not None:
            if data.role not in VALID_ROLES:
                raise ValueError("Invalid role")
            user.role = data.role
        if data.full_name is not None:
            user.full_name = data.full_name
        await self.db.flush()
        return user

    async def set_status(self, user_id: str, is_active: bool) -> User:
        user = await self._get(user_id)
        if not user:
            raise ValueError("User not found")
        user.is_active = is_active
        await self.db.flush()
        return user

    async def delete(self, user_id: str) -> None:
        user = await self._get(user_id)
        if not user:
            raise ValueError("User not found")
        await self.db.delete(user)
