# src/utils/job_store.py

"""
File-based job storage for GraphRAG Pipeline API
Persists job status across server restarts
Single JSON file per API for efficient storage
"""

import json
import logging
import time
from pathlib import Path
from threading import Lock
from typing import Dict, List, Optional

from utils.logging_utils import log_flow

logger = logging.getLogger("job_store")


class JobStore:
    """Thread-safe file-based job storage - Single JSON file per API"""

    def __init__(self, storage_dir: str = "_jobs", api_name: str = "pipeline"):
        """
        Initialize job store

        Args:
            storage_dir: Directory to store job log files
            api_name: Name of the API (creates {api_name}_api_log.json)
        """
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        self.api_name = api_name
        self.log_file = self.storage_dir / f"{api_name}_api_log.json"
        self._lock = Lock()

        # Initialize or load existing log file
        self._ensure_log_file_exists()

        log_flow(logger, "job_store_init", api_name=self.api_name, log_file=str(self.log_file.absolute()))

        # Load existing jobs on startup
        existing_jobs = self.list_all_jobs()
        if existing_jobs:
            log_flow(
                logger,
                "job_store_load_existing",
                api_name=self.api_name,
                existing_job_count=len(existing_jobs),
            )

    def _ensure_log_file_exists(self):
        """Ensure the log file exists with proper structure"""
        if not self.log_file.exists():
            self._write_log_file(
                {"jobs": {}, "_metadata": {"created_at": time.time(), "api_name": self.api_name}}
            )

    def _read_log_file(self) -> Dict:
        """Read the entire log file"""
        try:
            with open(self.log_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            # Corrupted or missing file, recreate
            default_data = {
                "jobs": {},
                "_metadata": {"created_at": time.time(), "api_name": self.api_name},
            }
            self._write_log_file(default_data)
            return default_data

    def _write_log_file(self, data: Dict):
        """Write the entire log file atomically"""
        # Atomic write: write to temp file first, then rename
        temp_path = self.log_file.with_suffix(".tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        # Atomic rename
        temp_path.replace(self.log_file)

    def save_job(self, job_id: str, job_data: Dict) -> bool:
        """
        Save job to log file

        Args:
            job_id: Job identifier
            job_data: Job data dictionary

        Returns:
            True if successful, False otherwise
        """
        try:
            with self._lock:
                # Read current log
                log_data = self._read_log_file()

                # Add metadata
                job_data_with_meta = {
                    **job_data,
                    "_saved_at": time.time(),
                    "_job_id": job_id,
                }

                # Update job in log
                log_data["jobs"][job_id] = job_data_with_meta
                log_data["_metadata"]["last_updated"] = time.time()

                # Write back to file
                self._write_log_file(log_data)

            return True

        except Exception as e:
            print(f"❌ Error saving job {job_id}: {e}")
            return False

    def load_job(self, job_id: str) -> Optional[Dict]:
        """
        Load job from log file

        Args:
            job_id: Job identifier

        Returns:
            Job data dictionary or None if not found
        """
        try:
            with self._lock:
                log_data = self._read_log_file()

                job_data = log_data["jobs"].get(job_id)

                if not job_data:
                    return None

                # Remove internal metadata
                job_copy = job_data.copy()
                job_copy.pop("_saved_at", None)
                job_copy.pop("_job_id", None)

                return job_copy

        except Exception as e:
            print(f"❌ Error loading job {job_id}: {e}")
            return None

    def delete_job(self, job_id: str) -> bool:
        """
        Delete job from log file

        Args:
            job_id: Job identifier

        Returns:
            True if successful, False otherwise
        """
        try:
            with self._lock:
                log_data = self._read_log_file()

                if job_id in log_data["jobs"]:
                    del log_data["jobs"][job_id]
                    log_data["_metadata"]["last_updated"] = time.time()
                    self._write_log_file(log_data)
                    return True

                return False

        except Exception as e:
            print(f"❌ Error deleting job {job_id}: {e}")
            return False

    def list_all_jobs(self) -> List[str]:
        """
        List all job IDs

        Returns:
            List of job IDs
        """
        try:
            with self._lock:
                log_data = self._read_log_file()
                return list(log_data["jobs"].keys())

        except Exception as e:
            print(f"❌ Error listing jobs: {e}")
            return []

    def get_all_jobs(self) -> Dict[str, Dict]:
        """
        Load all jobs from log file

        Returns:
            Dictionary mapping job_id -> job_data
        """
        try:
            with self._lock:
                log_data = self._read_log_file()

                jobs = {}
                for job_id, job_data in log_data["jobs"].items():
                    # Remove internal metadata
                    job_copy = job_data.copy()
                    job_copy.pop("_saved_at", None)
                    job_copy.pop("_job_id", None)
                    jobs[job_id] = job_copy

                return jobs

        except Exception as e:
            print(f"❌ Error getting all jobs: {e}")
            return {}

    def cleanup_old_jobs(self, max_age_hours: int = 24) -> int:
        """
        Delete jobs older than specified age

        Args:
            max_age_hours: Maximum age in hours

        Returns:
            Number of jobs deleted
        """
        deleted_count = 0
        max_age_seconds = max_age_hours * 3600
        current_time = time.time()

        try:
            with self._lock:
                log_data = self._read_log_file()

                jobs_to_delete = []

                for job_id, job_data in log_data["jobs"].items():
                    saved_at = job_data.get("_saved_at", 0)

                    if current_time - saved_at > max_age_seconds:
                        jobs_to_delete.append(job_id)

                # Delete old jobs
                for job_id in jobs_to_delete:
                    del log_data["jobs"][job_id]
                    deleted_count += 1

                if deleted_count > 0:
                    log_data["_metadata"]["last_updated"] = time.time()
                    self._write_log_file(log_data)

        except Exception as e:
            print(f"❌ Error cleaning up jobs: {e}")

        if deleted_count > 0:
            print(f"🧹 Cleaned up {deleted_count} old jobs from {self.api_name} API log")

        return deleted_count

    def get_stats(self) -> Dict:
        """Get storage statistics"""
        try:
            with self._lock:
                log_data = self._read_log_file()

                total_jobs = len(log_data["jobs"])
                file_size = self.log_file.stat().st_size if self.log_file.exists() else 0

                return {
                    "total_jobs": total_jobs,
                    "total_size_bytes": file_size,
                    "total_size_mb": round(file_size / (1024 * 1024), 2),
                    "storage_dir": str(self.storage_dir.absolute()),
                    "log_file": str(self.log_file.name),
                    "api_name": self.api_name,
                }

        except Exception as e:
            print(f"❌ Error getting stats: {e}")
            return {
                "total_jobs": 0,
                "total_size_bytes": 0,
                "total_size_mb": 0,
                "storage_dir": str(self.storage_dir.absolute()),
                "log_file": str(self.log_file.name),
                "api_name": self.api_name,
            }
