import os

from dotenv import load_dotenv
from redis import Redis
from rq import Queue, Worker

load_dotenv()

redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")

listen = [
    "default",
    "ingest",
    "local_ai",
    "cloud_ai",
    "briefings",
]

conn = Redis.from_url(redis_url)


if __name__ == "__main__":
    queues = [Queue(name, connection=conn) for name in listen]
    worker = Worker(queues, connection=conn)
    worker.work()
