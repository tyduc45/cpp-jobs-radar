import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import radar
from classify import classify, countries_for

SOURCE = {"type": "greenhouse", "board": "demo", "company": "Demo"}


def job(url="https://example.com/jobs/1"):
    return radar.make_job(SOURCE, "1", "C++ Software Engineer", "Use modern C++17", url, "Sydney")


def result(jobs, ok=True):
    return {"id": "greenhouse:demo", "company": "Demo", "ok": ok, "jobs": jobs}


class MatchingTests(unittest.TestCase):
    def test_exact_cpp_variants_not_plain_c_or_csharp(self):
        for text in ["C++17 developer", "C/C++", "Modern c ++", "CPP developer", "C plus plus", "C＋＋"]:
            self.assertIsNotNone(radar.CPP.search(text), text)
        for text in ["C# engineer", "C developer", "Access management", "cppcheck", "SCCP"]:
            self.assertIsNone(radar.CPP.search(text), text)

    def test_url_dedup_and_query_identity(self):
        self.assertEqual(job()["id"], job("https://example.com/jobs/1/?utm_source=feed#apply")["id"])
        self.assertNotEqual(job("https://example.com/?gh_jid=1")["id"], job("https://example.com/?gh_jid=2")["id"])
        with self.assertRaises(ValueError):
            radar.canonical_url("javascript:alert(1)")

    def test_strip_external_html(self):
        self.assertEqual(radar.plain("<script>fake</script><p>C&amp;C++</p>"), "C&C++")


class ClassificationTests(unittest.TestCase):
    def test_intern_wins_over_fulltime(self):
        j = classify("C++ Software Intern", "Sydney", "", "FullTime", "Hybrid")
        self.assertEqual((j["contract"], j["workplace"], j["countries"]), ("intern", "hybrid", ["AU"]))

    def test_no_invention_from_city_or_remote_systems(self):
        j = classify("Engineer", "London", "You will build remote control systems and work with interns.")
        self.assertEqual((j["contract"], j["workplace"]), ("unknown", "unknown"))
        self.assertEqual(countries_for("EMEA / APAC"), [])

    def test_multiple_countries_and_structured_workplace(self):
        self.assertEqual(countries_for("Sydney; Singapore; London"), ["AU", "GB", "SG"])
        self.assertEqual(classify("Engineer", "Paris", "", "FullTime", "OnSite")["workplace"], "onsite")
        self.assertEqual(classify("Software Co-op", "Toronto", "", "Full-time")["contract"], "intern")


class StateTests(unittest.TestCase):
    def test_retry_update_and_reappearance_do_not_create_new_job(self):
        state = {"jobs": {}}
        self.assertEqual(radar.merge_results(state, [result([job()])], "2026-09-26"), 1)
        key = job()["id"]
        state["jobs"][key]["notified_at"] = "sent"
        changed = {**job(), "title": "C++ Engineer II"}
        self.assertEqual(radar.merge_results(state, [result([changed])], "2026-09-27"), 0)
        self.assertEqual(state["jobs"][key]["first_seen"], "2026-09-26")
        self.assertEqual(state["jobs"][key]["notified_at"], "sent")
        for day in range(3):
            radar.merge_results(state, [result([])], str(day))
        self.assertFalse(state["jobs"][key]["active"])
        self.assertEqual(radar.merge_results(state, [result([job()])], "return"), 0)
        self.assertEqual(state["jobs"][key]["notified_at"], "sent")

    def test_failed_source_never_expires_jobs(self):
        state = {"jobs": {}}
        radar.merge_results(state, [result([job()])], "first")
        for day in range(5):
            radar.merge_results(state, [result([], ok=False)], str(day))
        self.assertTrue(state["jobs"][job()["id"]]["active"])
        self.assertEqual(state["jobs"][job()["id"]]["misses"], 0)
        self.assertEqual(state["last_success"], "first")

    def test_ashby_unlisted_jobs_excluded(self):
        rows = {"jobs": [{"isListed": False, "title": "C++ secret"}]}
        with patch("radar.fetch_json", return_value=rows):
            self.assertEqual(radar.fetch_source({"type": "ashby", "board": "demo", "company": "Demo"})["jobs"], [])

    def test_lever_reads_all_pages(self):
        row = {"id": "x", "text": "C++ Intern", "hostedUrl": "https://example.com/jobs/x", "categories": {}}
        pages = [[{**row, "id": str(i), "hostedUrl": f"https://example.com/jobs/{i}"} for i in range(100)], [row]]
        with patch("radar.fetch_json", side_effect=pages), patch("radar.time.sleep"):
            self.assertEqual(radar.fetch_source({"type": "lever", "board": "demo", "company": "Demo"})["scanned"], 101)


class EmailTests(unittest.TestCase):
    def setUp(self):
        # Expected mock failures must not become real GitHub warning annotations.
        quiet = patch("builtins.print")
        quiet.start()
        self.addCleanup(quiet.stop)

    def test_send_failure_retains_pending_then_success_deduplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            state = {"jobs": {}}
            radar.merge_results(state, [result([job()])], "2026-09-27")
            radar.write_json(path, state)
            env = {"SMTP_HOST": "example.com", "SMTP_USER": "test@example.com", "SMTP_PASSWORD": "dummy", "MAIL_TO": "recipient@example.com"}
            config = {"site_url": "https://example.com"}
            with patch.dict(os.environ, {**env, "SMTP_PORT": "465"}), patch("radar.smtplib.SMTP_SSL") as smtp:
                client = smtp.return_value
                client.send_message.side_effect = RuntimeError("mail failure")
                with self.assertRaises(RuntimeError):
                    radar.notify(config, path)
                self.assertIsNone(radar.read_json(path)["jobs"][job()["id"]]["notified_at"])
                client.send_message.side_effect = None
                client.send_message.return_value = {}
                self.assertEqual(radar.notify(config, path), 0)
                self.assertIsNotNone(radar.read_json(path)["jobs"][job()["id"]]["notified_at"])
                client.send_message.reset_mock()
                self.assertEqual(radar.notify(config, path), 0)
                client.send_message.assert_not_called()

    def test_missing_secrets_does_not_mark_sent(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            path = Path(directory) / "state.json"
            state = {"jobs": {}}
            radar.merge_results(state, [result([job()])], "now")
            radar.write_json(path, state)
            self.assertEqual(radar.notify({"site_url": "https://example.com"}, path), 2)
            self.assertIsNone(radar.read_json(path)["jobs"][job()["id"]]["notified_at"])

    def test_digest_has_all_new_jobs_attachment_and_safe_html(self):
        jobs = [{**job(f"https://example.com/{i}"), "first_seen": "today", "title": "<img src=x> C++"} for i in range(75)]
        message = radar.build_digest(jobs, {"site_url": "https://example.com"}, "me@example.com", "you@example.com")
        self.assertIn("&lt;img", message.get_body(preferencelist=("html",)).get_content())
        attachment = list(message.iter_attachments())[0]
        self.assertEqual(len(attachment.get_payload(decode=True).decode("utf-8-sig").splitlines()), 76)


if __name__ == "__main__":
    unittest.main()
