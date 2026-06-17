import asyncio, sys, os
sys.path.insert(0, "/app")
os.chdir("/app")

from app.services.database import AsyncSessionLocal
from sqlalchemy import text
from app.models.user import User
from sqlalchemy import select

async def check():
    async with AsyncSessionLocal() as s:
        # Alembic
        r = await s.execute(text("SELECT version_num FROM alembic_version"))
        print("Alembic version:", [x[0] for x in r.fetchall()])
        
        # LLM tables
        r = await s.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename LIKE 'llm%'"))
        print("LLM tables:", [x[0] for x in r.fetchall()])
        
        # AI signal tables
        r = await s.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public' AND (tablename LIKE 'ai_signal%' OR tablename LIKE 'ai%reject%')"))
        print("AI signal tables:", [x[0] for x in r.fetchall()])
        
        # Counts
        r = await s.execute(text("SELECT COUNT(*) FROM llm_signal_diagnoses"))
        print("Diagnoses count:", r.scalar())
        r = await s.execute(text("SELECT COUNT(*) FROM ai_signals"))
        print("AI signals count:", r.scalar())
        
        # Columns in llm_signal_diagnoses
        r = await s.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='llm_signal_diagnoses'"))
        cols = [x[0] for x in r.fetchall()]
        print("LLM diagnosis columns:", sorted(cols))
        
        # Admin user
        r = await s.execute(select(User).where(User.role == "admin").limit(1))
        u = r.scalar_one_or_none()
        if u:
            print("Admin user:", u.email, "id=", str(u.id))
        else:
            print("No admin user found")

asyncio.run(check())
