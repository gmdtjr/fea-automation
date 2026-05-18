import os
import uuid
import logging
from datetime import datetime

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from pipeline.geometry_parser import SUPPORTED_FORMATS

logger = logging.getLogger(__name__)


class GeometryFileHandler(FileSystemEventHandler):
    def __init__(self, db_factory, task_queue):
        self.db_factory = db_factory
        self.task_queue = task_queue

    def on_created(self, event):
        if event.is_directory:
            return
        ext = os.path.splitext(event.src_path)[1].lower()
        if ext not in SUPPORTED_FORMATS:
            return
        logger.info("New file detected: %s", event.src_path)
        self._create_job(event.src_path)

    def _create_job(self, file_path: str) -> None:
        from db.models import Job, JobStatus
        db = self.db_factory()
        try:
            job = Job(
                id=str(uuid.uuid4()),
                file_name=os.path.basename(file_path),
                file_path=file_path,
                status=JobStatus.PENDING,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            db.add(job)
            db.commit()
            db.refresh(job)
            logger.info("Created job %s for %s", job.id, file_path)
            # Trigger async geometry parse
            self.task_queue.send_task("worker.tasks.parse_geometry", args=[job.id])
        except Exception as e:
            logger.error("Failed to create job for %s: %s", file_path, e)
            db.rollback()
        finally:
            db.close()


def start_watcher(watch_dir: str, db_factory, task_queue) -> Observer:
    os.makedirs(watch_dir, exist_ok=True)
    handler = GeometryFileHandler(db_factory, task_queue)
    observer = Observer()
    observer.schedule(handler, watch_dir, recursive=False)
    observer.start()
    logger.info("Watching %s for geometry files", watch_dir)
    return observer
