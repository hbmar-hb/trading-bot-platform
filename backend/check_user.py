import asyncio, sys
sys.path.insert(0, "/app")
from app.services.database import AsyncSessionLocal
from app.models.user import User
from sqlalchemy import select
async def check():
    async with AsyncSessionLocal() as s:
        r = await s.execute(select(User).where(User.role == "admin").limit(1))
        u = r.scalar_one_or_none()
        if u:
            print(f"Admin user: {u.email} id={u.id}")
            from app.core.security import create_access_token
            token = create_access_token(subject=str(u.id))
            print(f"Token: {token}")
        else:
            print("No admin user found")
asyncio.run(check())
