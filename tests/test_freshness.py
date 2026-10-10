import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import radar
from freshness import is_current, visible_until
from test_radar import job, result, SOURCE


class FreshnessTests(unittest.TestCase):
    def test_missing_from_one_complete_feed_closes_and_reappearance_keeps_receipt(self):
        state = {"jobs": {}}
        original = job()
        radar.merge_results(state, [result([original])], "first")
        state["jobs"][original["id"]]["notified_at"] = "sent"
        radar.merge_results(state, [result([])], "closed")
        saved = state["jobs"][original["id"]]
        self.assertFalse(saved["active"])
        self.assertEqual(saved["closed_at"], "closed")
        self.assertEqual(state["last_closed_count"], 1)
        radar.merge_results(state, [result([])], "still-closed")
        self.assertEqual(saved["closed_at"], "closed")
        self.assertEqual(state["last_closed_count"], 0)
        self.assertEqual(radar.merge_results(state, [result([original])], "back"), 0)
        saved = state["jobs"][original["id"]]
        self.assertTrue(saved["active"])
        self.assertIsNone(saved["closed_at"])
        self.assertEqual((saved["first_seen"], saved["notified_at"]), ("first", "sent"))

    def test_failed_source_stays_unclosed_but_is_hidden_at_exact_ttl(self):
        now = datetime(2026, 10, 10, tzinfo=timezone.utc)
        state = {"jobs": {}}
        radar.merge_results(state, [result([job()])], now.isoformat())
        radar.merge_results(state, [result([], ok=False)], (now + timedelta(days=4)).isoformat())
        saved = state["jobs"][job()["id"]]
        self.assertTrue(saved["active"])
        self.assertEqual(saved["misses"], 0)
        self.assertTrue(is_current(saved, {}, now + timedelta(hours=71, minutes=59)))
        self.assertFalse(is_current(saved, {}, now + timedelta(hours=72)))
        self.assertEqual(saved["last_seen"], now.isoformat())
        radar.merge_results(state, [result([job()])], (now + timedelta(days=4)).isoformat())
        self.assertTrue(is_current(state["jobs"][job()["id"]], {}, now + timedelta(days=4)))

    def test_independent_sources_do_not_close_each_other_on_failure(self):
        a, b = job(), {**job("https://example.com/b"), "source_id": "lever:b"}
        state = {"jobs": {}}
        radar.merge_results(state, [result([a]), {"id": "lever:b", "ok": True, "jobs": [b]}], "first")
        radar.merge_results(state, [result([]), {"id": "lever:b", "ok": False}], "second")
        self.assertFalse(state["jobs"][a["id"]]["active"])
        self.assertTrue(state["jobs"][b["id"]]["active"])

    def test_deadlines_disabled_sources_and_invalid_verification(self):
        now = datetime(2026, 10, 10, tzinfo=timezone.utc)
        record = {**job(), "active": True, "last_seen": now.isoformat()}
        config = {"sources": [SOURCE], "max_unverified_hours": 48}
        self.assertEqual(visible_until(record, config), now + timedelta(hours=48))
        self.assertFalse(is_current(record, {"sources": []}, now))
        self.assertFalse(is_current(record, {"sources": [{**SOURCE, "enabled": False}]}, now))
        for value in (None, "bad", "2026-10-10"):
            self.assertFalse(is_current({**record, "last_seen": value}, config, now))
        self.assertFalse(is_current({**record, "application_deadline": "2026-10-10T11:00:00+11:00"}, config, now))
        self.assertTrue(is_current({**record, "application_deadline": "2026-10-11T00:00:00Z"}, config, now))
        # Do not invent a timezone for ambiguous source dates.
        self.assertTrue(is_current({**record, "application_deadline": "2026-10-01"}, config, now))

    def test_export_digest_and_smtp_all_exclude_closed_stale_expired_jobs(self):
        now = datetime.now(timezone.utc)
        current = {**job(), "active": True, "first_seen": now.isoformat(), "last_seen": now.isoformat()}
        records = [current]
        for suffix, changes in [
            ("closed", {"active": False}),
            ("stale", {"last_seen": (now - timedelta(hours=73)).isoformat()}),
            ("expired", {"application_deadline": (now - timedelta(hours=1)).isoformat()}),
        ]:
            records.append({**current, "id": suffix, "url": f"https://example.com/{suffix}", **changes})
        config = {"timezone": "Australia/Sydney", "site_url": "https://example.com"}
        with tempfile.TemporaryDirectory() as directory, patch("builtins.print"):
            root = Path(directory)
            path = root / "state.json"
            radar.write_json(path, {"jobs": {r["id"]: r for r in records}})
            radar.export_site(config, path, root / "jobs.json")
            exported = radar.read_json(root / "jobs.json")
            self.assertEqual([r["id"] for r in exported["jobs"]], [current["id"]])
            self.assertTrue(exported["jobs"][0]["visible_until"])
            self.assertEqual(exported["freshness"]["closed_total"], 1)
            self.assertEqual(exported["freshness"]["hidden_unverified"], 2)
            message = radar.build_digest(records, config, "test@example.com", "recipient@example.com")
            plain = message.get_body(preferencelist=("plain",)).get_content()
            html = message.get_body(preferencelist=("html",)).get_content()
            csv = list(message.iter_attachments())[0].get_payload(decode=True).decode("utf-8-sig")
            for record in records[1:]:
                for body in (plain, html, csv):
                    self.assertNotIn(record["url"], body)
            with self.assertRaises(ValueError):
                radar.build_digest(records[1:], config, "test@example.com", "recipient@example.com")
            env = {"SMTP_HOST": "example.com", "SMTP_PORT": "465", "SMTP_USER": "test@example.com",
                   "SMTP_PASSWORD": "dummy", "MAIL_TO": "recipient@example.com"}
            with patch.dict(os.environ, env), patch("radar.smtplib.SMTP_SSL") as smtp:
                smtp.return_value.send_message.return_value = {}
                radar.notify(config, path)
                saved = radar.read_json(path)["jobs"]
                self.assertTrue(saved[current["id"]]["notified_at"])
                self.assertTrue(all(not saved[r["id"]].get("notified_at") for r in records[1:]))

    def test_greenhouse_rejects_incomplete_or_duplicate_snapshot(self):
        for payload in [{"jobs": [], "meta": {"total": 2}}, {"jobs": [{"id": 1}, {"id": 1}]}]:
            with self.subTest(payload=payload), patch("radar.fetch_json", return_value=payload):
                with self.assertRaises(ValueError):
                    radar.fetch_source(SOURCE)

    def test_lever_rejects_overlapping_pages(self):
        rows = [{"id": str(i), "text": "C++ Intern", "descriptionPlain": "C++ work",
                 "hostedUrl": f"https://example.com/{i}"} for i in range(100)]
        with patch("radar.fetch_json", side_effect=[rows, [rows[-1]]]), patch("radar.time.sleep"):
            with self.assertRaises(ValueError):
                radar.fetch_source({"type": "lever", "board": "demo", "company": "Demo"})

    def test_crawl_failure_retains_records_and_returns_failure(self):
        with tempfile.TemporaryDirectory() as directory, patch("builtins.print"):
            path = Path(directory) / "state.json"
            state = {"jobs": {}}
            radar.merge_results(state, [result([job()])], datetime.now(timezone.utc).isoformat())
            radar.write_json(path, state)
            with patch("radar.fetch_source", side_effect=ValueError("incomplete snapshot")):
                self.assertEqual(radar.crawl({"sources": [SOURCE]}, path), 1)
            saved = radar.read_json(path)
            self.assertTrue(saved["jobs"][job()["id"]]["active"])
            self.assertFalse(saved["sources"][0]["ok"])
