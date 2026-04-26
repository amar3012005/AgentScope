import asyncio
import os
import sys

# Add src to path
sys.path.append(os.path.join(os.getcwd(), "AgentScope-BLAIQ", "src"))

from agentscope_blaiq.persistence.database import engine
from agentscope_blaiq.persistence.models import Base

async def sync_db():
    print("Connecting to database...")
    async with engine.begin() as conn:
        print("Running migrations (create_all)...")
        await conn.run_sync(Base.metadata.create_all)
    print("Done.")

if __name__ == "__main__":
    asyncio.run(sync_db())
