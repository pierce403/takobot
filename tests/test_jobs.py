from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from takobot.jobs import (
    add_job_from_natural_text,
    claim_due_jobs,
    format_jobs_report,
    get_job,
    list_jobs,
    looks_like_natural_job_request,
    mark_job_manual_trigger,
    parse_natural_job_request,
    record_job_error,
    remove_job,
)


class TestJobs(unittest.TestCase):
    def test_parse_natural_job_request_daily(self) -> None:
        parsed = parse_natural_job_request("every day at 3pm explore ai news")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual("daily", parsed.schedule.kind)
        self.assertEqual(15, parsed.schedule.hour)
        self.assertEqual(0, parsed.schedule.minute)
        self.assertEqual("explore ai news", parsed.action)

    def test_parse_natural_job_request_weekday_variants(self) -> None:
        parsed = parse_natural_job_request("at 09:30 every weekday run doctor")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual("weekly", parsed.schedule.kind)
        self.assertEqual((0, 1, 2, 3, 4), parsed.schedule.weekdays)
        self.assertEqual("run doctor", parsed.action)

    def test_natural_job_detection_is_bounded(self) -> None:
        self.assertTrue(looks_like_natural_job_request("every day at 3pm run doctor"))
        self.assertFalse(looks_like_natural_job_request("can you explain what a cron job is"))

    def test_add_list_report_and_remove_job(self) -> None:
        with TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / "state"
            ok, summary, created = add_job_from_natural_text(state_dir, "every day at 3pm run doctor")
            self.assertTrue(ok)
            self.assertIn("job created:", summary)
            self.assertIsNotNone(created)
            assert created is not None

            jobs = list_jobs(state_dir)
            self.assertEqual(1, len(jobs))
            self.assertEqual(created.job_id, jobs[0].job_id)

            report = format_jobs_report(jobs)
            self.assertIn("jobs: 1 scheduled", report)
            self.assertIn(created.job_id, report)

            looked_up = get_job(state_dir, created.job_id)
            self.assertIsNotNone(looked_up)
            self.assertEqual(created.job_id, looked_up.job_id if looked_up else "")

            self.assertTrue(remove_job(state_dir, created.job_id))
            self.assertEqual([], list_jobs(state_dir))

    def test_claim_due_jobs_runs_once_per_slot(self) -> None:
        with TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / "state"
            ok, _summary, created = add_job_from_natural_text(state_dir, "every day at 3pm run doctor")
            self.assertTrue(ok)
            assert created is not None

            local_tz = datetime.now().astimezone().tzinfo
            assert local_tz is not None
            first_tick = datetime(2026, 2, 19, 15, 1, tzinfo=local_tz)
            second_day = first_tick + timedelta(days=1)

            first_due = claim_due_jobs(state_dir, now=first_tick)
            self.assertEqual([created.job_id], [job.job_id for job in first_due])

            duplicate_due = claim_due_jobs(state_dir, now=first_tick)
            self.assertEqual([], duplicate_due)

            next_day_due = claim_due_jobs(state_dir, now=second_day)
            self.assertEqual([created.job_id], [job.job_id for job in next_day_due])

    def test_manual_trigger_and_error_recording(self) -> None:
        with TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / "state"
            ok, _summary, created = add_job_from_natural_text(state_dir, "every monday at 14:00 run doctor")
            self.assertTrue(ok)
            assert created is not None

            triggered = mark_job_manual_trigger(state_dir, created.job_id)
            self.assertIsNotNone(triggered)
            assert triggered is not None
            self.assertEqual(1, triggered.run_count)

            self.assertTrue(record_job_error(state_dir, created.job_id, "queue overflow"))
            refreshed = get_job(state_dir, created.job_id)
            self.assertIsNotNone(refreshed)
            assert refreshed is not None
            self.assertEqual("queue overflow", refreshed.last_error)


if __name__ == "__main__":
    unittest.main()
