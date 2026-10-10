import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import radar
from eligibility import SCREENING_VERSION, screen_job, is_visible


class RestrictionTests(unittest.TestCase):
    def test_explicit_restrictions_are_excluded(self):
        cases = [
            "Applicant for this intern position must be a (i) U.S. citizen or national, (ii) U.S. lawful permanent resident (e.g., green card holder), (iii) Refugee under 8 U.S.C. § 1157, or (iv) Asylee under 8 U.S.C. § 1158.",
            "Applicant must be a U.S. citizen or be eligible to obtain required authorizations from the U.S. Department of State.",
            "Must be a U.S. Person due to required access to U.S. export-controlled information or facilities.",
            "U.S. citizenship is required, due to program requirements.",
            "Applicants must hold Australian citizenship or permanent residency.",
            "Australian citizens and permanent residents only.",
            "Applicants must be British nationals.",
            "You must be a Japanese national.",
            "Applicants must hold a British passport.",
            "Citizenship: Australian. Experience: C++.",
            "Only EU citizens are eligible for this internship.",
            "This role is restricted to Canadian citizens.",
            "Green card required.",
            "You may be ineligible for this role if you do not hold citizenship of Australia, Japan, New Zealand, Switzerland, the European Union, or a country that is part of NATO.",
            "These checks will include nationality checks as it is a requirement of this position that you be eligible to access ITAR equipment.",
            "Must have the ability to obtain and maintain an Australian Government Security Clearance.",
            "Ability to obtain a U.S. security clearance.",
            "Active Secret security clearance OR ability to obtain and maintain one.",
            "This position requires successfully obtaining and maintaining a Top Secret Security Clearance as a condition of employment.",
            "Eligible to obtain and maintain an active U.S. Secret security clearance PREFERRED QUALIFICATIONS Experience with Linux.",
            "Ability to obtain an Australian Government Negative Vetting 2 security clearance (NV2) PREFERRED QUALIFICATIONS C++.",
            "Must be eligible for a US security clearance. Preferred Qualifications: ROS.",
            "Active U.S. Top Secret or TS/SCI clearance PREFERRED QUALIFICATIONS C++.",
            "Security clearance not required, but must be eligible to obtain and maintain a U.S. TS clearance PREFERRED QUALIFICATIONS C++.",
            "必须具有美国国籍或永久居留权。",
            "本岗位仅限澳大利亚公民或绿卡持有人申请。",
            "Nationalité française requise.",
            "Deutsche Staatsangehörigkeit erforderlich.",
        ]
        for text in cases:
            with self.subTest(text=text):
                self.assertTrue(screen_job("C++ Intern", text)["excluded"])

    def test_neutral_optional_and_negated_mentions_are_kept(self):
        cases = [
            "C++ engineer. All applicants are welcome regardless of citizenship, nationality or permanent residency.",
            "Applicants receive equal consideration without regard to race, national origin, citizenship, gender or age.",
            "U.S. citizenship is not required. International students are welcome.",
            "No citizenship requirement. Visa sponsorship available.",
            "You are not required to be a U.S. citizen.",
            "Security clearance is not required.",
            "No security clearance is required.",
            "An active Secret security clearance is preferred, but not required.",
            "NICE TO HAVE: Active TS/SCI security clearance. C++ experience.",
            "We build security clearance management software with C++.",
            "Engineers must make safety a first-class citizen in every design discussion.",
            "We serve national security customers and follow export control laws.",
            "Applicants must be legally authorized to work in Australia.",
            "Applicants must have a valid passport for international travel.",
            "We support visa sponsorship for qualified candidates.",
            "We do not discriminate on the basis of citizenship status, as required by law.",
            "Depending on your nationality and country of residence, obtaining the required entry visa may be subject to additional requirements, processing delays or other limitations.",
        ]
        for text in cases:
            with self.subTest(text=text):
                self.assertFalse(screen_job("C++ Intern", text)["excluded"])

    def test_eeo_never_cancels_a_real_restriction(self):
        text = "Must be a U.S. citizen. We do not discriminate on the basis of nationality."
        self.assertTrue(screen_job("Engineer", text)["excluded"])

    def test_no_full_description_means_not_screened(self):
        self.assertEqual(screen_job("C++ Engineer", "")["version"], 0)


class DeliveryGateTests(unittest.TestCase):
    def make_job(self, description="C++ software engineering", url="https://example.com/open"):
        return radar.make_job({"company": "Demo", "type": "greenhouse", "board": "demo"},
                              "1", "C++ Intern", description, url, "Sydney")

    def test_existing_restricted_record_removed_immediately_and_keeps_receipt(self):
        state = {"jobs": {}}
        old = self.make_job()
        source = {"ok": True, "id": "greenhouse:demo", "company": "Demo", "jobs": [old]}
        radar.merge_results(state, [source], "first")
        state["jobs"][old["id"]]["notified_at"] = "already-sent"
        restricted = self.make_job("C++ developer. Must be a U.S. citizen.")
        radar.merge_results(state, [{**source, "jobs": [restricted]}], "second")
        saved = state["jobs"][old["id"]]
        self.assertTrue(saved["active"])
        self.assertFalse(is_visible(saved))
        self.assertEqual(saved["notified_at"], "already-sent")
        self.assertEqual(saved["first_seen"], "first")

    def test_legacy_rows_hidden_even_when_their_source_fails(self):
        old = {**self.make_job(), "active": True}
        del old["screening"]
        state = {"jobs": {old["id"]: old}}
        radar.merge_results(state, [{"ok": False, "id": "greenhouse:demo"}], "now")
        self.assertFalse(is_visible(old))
        stale = {**old, "screening": {"version": SCREENING_VERSION - 1, "excluded": False}}
        self.assertFalse(is_visible(stale))

    def test_json_and_digest_and_smtp_share_same_gate(self):
        now = datetime.now(timezone.utc).isoformat()
        allowed = {**self.make_job(), "active": True, "first_seen": now, "last_seen": now}
        blocked = {**self.make_job("Must be a US citizen.", "https://example.com/blocked"),
                   "active": True, "first_seen": "now", "last_seen": "now"}
        legacy = {**allowed, "id": "legacy", "url": "https://example.com/legacy"}
        del legacy["screening"]
        with tempfile.TemporaryDirectory() as directory, patch("builtins.print"):
            root = Path(directory)
            state = {"jobs": {j["id"]: j for j in [allowed, blocked, legacy]}}
            radar.write_json(root / "state.json", state)
            config = {"timezone": "Australia/Sydney", "site_url": "https://example.com"}
            radar.export_site(config, root / "state.json", root / "jobs.json")
            exported = radar.read_json(root / "jobs.json")
            self.assertEqual([j["id"] for j in exported["jobs"]], [allowed["id"]])
            self.assertEqual(exported["screening"]["excluded"], 1)
            self.assertEqual(exported["screening"]["unreviewed"], 1)
            message = radar.build_digest([allowed, blocked, legacy], config, "a@example.com", "b@example.com")
            self.assertNotIn("https://example.com/blocked", message.get_body(preferencelist=("plain",)).get_content())
            csv = list(message.iter_attachments())[0].get_payload(decode=True).decode("utf-8-sig")
            self.assertNotIn("/blocked", csv)
            self.assertNotIn("/legacy", csv)
            env = {"SMTP_HOST": "example.com", "SMTP_PORT": "465", "SMTP_USER": "a@example.com", "SMTP_PASSWORD": "mock", "MAIL_TO": "b@example.com"}
            with patch.dict(os.environ, env), patch("radar.smtplib.SMTP_SSL") as smtp:
                smtp.return_value.send_message.return_value = {}
                self.assertEqual(radar.notify(config, root / "state.json"), 0)
                saved = radar.read_json(root / "state.json")["jobs"]
                self.assertTrue(saved[allowed["id"]]["notified_at"])
                self.assertFalse(saved[blocked["id"]].get("notified_at"))
                self.assertFalse(saved[legacy["id"]].get("notified_at"))


if __name__ == "__main__":
    unittest.main()
