"""Pure batch planning for workbook migration.

Plans are ephemeral orchestration state. They deliberately hold filenames only
long enough to match workbook dependencies and never enter conversion reports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import PurePath


class FileStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    RETRYABLE = "retryable"
    CONVERTED = "converted"
    CONVERTED_WITH_REVIEW = "converted_with_review"
    MANUAL_MIGRATION_REQUIRED = "manual_migration_required"
    FAILED = "failed"


@dataclass
class WorkbookJob:
    job_id: str
    source_name: str
    source_sha256: str
    external_targets: tuple[str, ...] = ()
    status: FileStatus = FileStatus.PENDING
    attempt: int = 0
    destination_id: str | None = None
    dependencies: set[str] = field(default_factory=set)
    dependency_targets: dict[str, str] = field(default_factory=dict)
    unresolved_count: int = 0
    cyclic: bool = False

    @property
    def idempotency_key(self) -> str:
        return f"workbook:{self.source_sha256}"

    def begin_attempt(self) -> None:
        if self.status not in {FileStatus.PENDING, FileStatus.READY, FileStatus.RETRYABLE}:
            raise ValueError("This workbook is not ready for another attempt.")
        self.attempt += 1
        self.status = FileStatus.RUNNING

    def retry(self) -> None:
        if self.status not in {FileStatus.RUNNING, FileStatus.FAILED}:
            raise ValueError("Only a running or failed workbook can be retried.")
        self.status = FileStatus.RETRYABLE


@dataclass
class BatchPlan:
    jobs: dict[str, WorkbookJob]

    def destination_links(self, job_id: str) -> dict[str, str]:
        """External workbook filenames mapped to destination Drive IDs."""
        job = self.jobs[job_id]
        result: dict[str, str] = {}
        for target, dependency in sorted(job.dependency_targets.items()):
            destination = self.jobs[dependency].destination_id
            if destination is not None:
                result[target] = destination
        return result

    def summary(self) -> dict:
        """Content-free batch state suitable for an operational API."""
        counts: dict[str, int] = {}
        for job in self.jobs.values():
            counts[job.status] = counts.get(job.status, 0) + 1
        return {
            "workbooks": len(self.jobs),
            "statuses": counts,
            "unresolvedLinks": sum(job.unresolved_count for job in self.jobs.values()),
            "cyclicWorkbooks": sum(job.cyclic for job in self.jobs.values()),
        }


def _normalise_filename(name: str) -> str:
    return PurePath(name.replace("\\", "/")).name.casefold()


def plan(jobs: list[WorkbookJob]) -> BatchPlan:
    by_name: dict[str, str] = {}
    for job in jobs:
        key = _normalise_filename(job.source_name)
        if key in by_name:
            raise ValueError("Workbook filenames must be unique within one batch.")
        by_name[key] = job.job_id
    result = BatchPlan({job.job_id: job for job in jobs})
    for job in jobs:
        for target in job.external_targets:
            dependency = by_name.get(_normalise_filename(target))
            if dependency is None:
                job.unresolved_count += 1
            else:
                job.dependencies.add(dependency)
                job.dependency_targets[target] = dependency
        job.status = FileStatus.READY
    _mark_cycles(result)
    return result


def _mark_cycles(batch: BatchPlan) -> None:
    visiting: list[str] = []
    visited: set[str] = set()

    def visit(job_id: str) -> None:
        if job_id in visiting:
            for member in visiting[visiting.index(job_id) :]:
                batch.jobs[member].cyclic = True
            return
        if job_id in visited:
            return
        visiting.append(job_id)
        for dependency in batch.jobs[job_id].dependencies:
            visit(dependency)
        visiting.pop()
        visited.add(job_id)

    for job_id in batch.jobs:
        visit(job_id)
