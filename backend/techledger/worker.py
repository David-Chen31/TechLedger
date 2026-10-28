"""Single bounded source synchronization worker."""

import logging
import time

from sqlalchemy import update

from techledger.db import SessionLocal
from techledger.models import ResearchRun, RunEvent, SyncJob, utcnow
from techledger.service import process_one_job
from techledger.research import process_one_research

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def recover_interrupted_jobs() -> None:
    with SessionLocal() as db:
        db.execute(
            update(SyncJob)
            .where(SyncJob.status == "running")
            .values(
                status="failed",
                error_code="worker_interrupted",
                error_message="Worker 已重启，请重新发起同步",
                finished_at=utcnow(),
            )
        )
        interrupted = db.query(ResearchRun).filter(ResearchRun.status == "running").all()
        for run in interrupted:
            run.status = "failed"
            run.error_code = "worker_interrupted"
            run.finished_at = utcnow()
            db.add(RunEvent(run_id=run.id, stage="failed", detail_json='{"code":"worker_interrupted"}'))
        db.commit()


def main() -> None:
    recover_interrupted_jobs()
    logger.info("TechLedger sync worker started")
    while True:
        with SessionLocal() as db:
            job = process_one_job(db)
            if job is not None:
                logger.info("Sync job %s finished: %s (%s)", job.id, job.status, job.error_code)
            research = process_one_research(db)
            if research is not None:
                logger.info("Research %s finished: %s", research.id, research.status)
        if job is None and research is None:
            time.sleep(1)


if __name__ == "__main__":
    main()
