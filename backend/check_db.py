import asyncio, sys
sys.path.insert(0, "/app")
from app.services.database import AsyncSessionLocal
from sqlalchemy import text
async def check():
    async with AsyncSessionLocal() as s:
        # Alembic version table structure
        r = await s.execute(text("SELECT * FROM alembic_version"))
        rows = r.fetchall()
        print("Alembic versions:", rows)
        r = await s.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename LIKE 'llm%'"))
        print("LLM tables:", [x[0] for x in r.fetchall()])
        r = await s.execute(text("SELECT COUNT(*) FROM llm_signal_diagnoses"))
        print("Diagnoses count:", r.scalar())
        r = await s.execute(text("SELECT COUNT(*) FROM ai_signals"))
        print("AI signals count:", r.scalar())
        r = await s.execute(text("SELECT COUNT(*) FROM ai_signal_rejected"))
        print("Rejected signals count:", r.scalar())
        # Check outcome columns exist in llm_signal_diagnoses
        r = await s.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='llm_signal_diagnoses'"))
        cols = [x[0] for x in r.fetchall()]
        print("LLM diagnosis columns:", sorted(cols))
asyncio.run(check())
