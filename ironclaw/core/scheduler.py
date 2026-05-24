"""
ironclaw.core.scheduler
~~~~~~~~~~~~~~~~~~~~~~~
Native Cron Jobs integration using APScheduler.
"""

from __future__ import annotations

import logging
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from ironclaw.core.orchestrator import Orchestrator

logger = logging.getLogger(__name__)

class CronScheduler:
    """Wrapper around AsyncIOScheduler for executing agent tasks periodically."""

    def __init__(self, orchestrator: Orchestrator) -> None:
        self.orchestrator = orchestrator
        self.scheduler = AsyncIOScheduler()

    def start(self) -> None:
        if not self.scheduler.running:
            self.scheduler.start()
            logger.info("CronScheduler started")

    def stop(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("CronScheduler stopped")

    def add_job(self, agent_id: str, message: str, cron_expr: str, job_id: str | None = None) -> str:
        """
        Schedule a recurring message to be sent to an agent.
        `cron_expr` should be a standard 5-part cron string, e.g. "*/5 * * * *".
        """
        async def _run_job():
            try:
                logger.info(f"Running scheduled job for agent {agent_id}")
                await self.orchestrator.run(agent_id, message)
            except Exception as e:
                logger.error(f"Scheduled job failed for agent {agent_id}: {e}")

        job = self.scheduler.add_job(
            _run_job,
            CronTrigger.from_crontab(cron_expr),
            id=job_id,
            replace_existing=True
        )
        logger.info(f"Scheduled job {job.id} for agent {agent_id} with cron {cron_expr}")
        return job.id

    def remove_job(self, job_id: str) -> None:
        self.scheduler.remove_job(job_id)

    def list_jobs(self) -> list[dict[str, Any]]:
        return [
            {
                "id": job.id,
                "next_run_time": str(job.next_run_time) if job.next_run_time else None,
                "cron_expr": str(job.trigger),
            }
            for job in self.scheduler.get_jobs()
        ]
