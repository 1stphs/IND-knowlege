import json
import os
import threading
import traceback
import uuid
from datetime import datetime

try:
    from service.ingestion_service import IngestionService
except ModuleNotFoundError:
    from rag_backend.service.ingestion_service import IngestionService


def _utc_now():
    return datetime.utcnow().isoformat() + "Z"


class IndexJobService:
    def __init__(self, root_dir: str):
        self.root_dir = root_dir
        self.ingestion_service = IngestionService(root_dir)
        self.jobs_path = os.path.join(root_dir, "rag_backend", "simple_db", "index_jobs.json")
        self._lock = threading.Lock()
        self.jobs = self._load_jobs()

    def _load_jobs(self):
        if os.path.exists(self.jobs_path):
            with open(self.jobs_path, "r", encoding="utf-8") as file_obj:
                return json.load(file_obj)
        return {}

    def _persist(self):
        os.makedirs(os.path.dirname(self.jobs_path), exist_ok=True)
        with open(self.jobs_path, "w", encoding="utf-8") as file_obj:
            json.dump(self.jobs, file_obj, ensure_ascii=False, indent=2)

    def submit(self, markdown_dir: str):
        job_id = uuid.uuid4().hex
        with self._lock:
            self.jobs[job_id] = {
                "job_id": job_id,
                "status": "queued",
                "markdown_dir": markdown_dir,
                "created_at": _utc_now(),
                "updated_at": _utc_now(),
                "result": None,
                "error": None,
            }
            self._persist()

        thread = threading.Thread(target=self._run_job, args=(job_id, markdown_dir), daemon=True)
        thread.start()
        return self.jobs[job_id]

    def get(self, job_id: str):
        return self.jobs.get(job_id)

    def _run_job(self, job_id: str, markdown_dir: str):
        self._update(job_id, status="running")
        try:
            result = self.ingestion_service.ingest_directory(markdown_dir)
            self._update(job_id, status="completed", result=result)
        except Exception:
            self._update(job_id, status="failed", error=traceback.format_exc())

    def _update(self, job_id: str, **kwargs):
        with self._lock:
            job = self.jobs[job_id]
            job.update(kwargs)
            job["updated_at"] = _utc_now()
            self._persist()
