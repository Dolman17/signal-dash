from redis import Redis
from rq import Queue
from flask import current_app


def get_redis_connection():
    redis_url = current_app.config.get("REDIS_URL", "redis://localhost:6379/0")
    return Redis.from_url(redis_url)


def get_queue(name="default"):
    return Queue(name, connection=get_redis_connection())


def enqueue_local_ai_review(source_file_id: int):
    queue = get_queue("local_ai")

    job = queue.enqueue(
        "app.jobs.local_ai_jobs.run_local_ai_review_job",
        source_file_id,
        job_timeout=1800,
        result_ttl=86400,
        failure_ttl=86400,
        description=f"Local AI review for SourceFile {source_file_id}",
    )

    return job
