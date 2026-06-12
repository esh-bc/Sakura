from motor.motor_asyncio import AsyncIOMotorClient
from config import MONGODB_URI, DB_NAME

client = AsyncIOMotorClient(MONGODB_URI)
db = client[DB_NAME]

keys_col = db["keys"]
users_col = db["users"]
queue_col = db["queue"]


async def setup_indexes():
    await keys_col.create_index("key_string", unique=True)
    await users_col.create_index("telegram_id", unique=True)
    await queue_col.create_index("user_id")
    await queue_col.create_index("status")
