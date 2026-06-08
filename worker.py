import os

from dotenv import load_dotenv
from redis import Redis
from rq import Queue, Worker

load_dotenv()

redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")

DEFAULT_QUEUES = [
    "default",
    "ingest",
    "local_ai",
]


def _queue_names_from_env():
    configured = os.getenv("WORKER_QUEUES", "").strip()

    if not configured:
        return DEFAULT_QUEUES

    queue_names = [name.strip() for name in configured.split(",") if name.strip()]

    return queue_names or DEFAULT_QUEUES


listen = _queue_names_from_env()
conn = Redis.from_url(redis_url)


if __name__ == "__main__":
    queues = [Queue(name, connection=conn) for name in listen]
    worker = Worker(queues, connection=conn)
    worker.work()
