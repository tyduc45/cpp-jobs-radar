import unittest
from unittest.mock import patch

import radar
import employer_feeds


class EmployerTests(unittest.TestCase):
    def test_nvidia_search_deduplicates_and_screens_full_description(self):
        row = {"externalPath": "/job/test"}
        calls = []

        def fetch(url, payload=None):
            if payload:
                return {"jobPostings": [row]}
            calls.append(url)
            return {"jobPostingInfo": {"canApply": True, "jobReqId": "test", "title": "Compiler Intern",
                    "externalUrl": "https://example.org/job/test", "location": "China, Shanghai",
                    "jobDescription": "Develop LLVM. US citizenship required."}}

        source = {"type": "nvidia", "board": "china", "company": "NVIDIA", "china_only": True}
        with patch("radar.fetch_json", side_effect=fetch):
            result = radar.fetch_source(source)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["excluded"], 1)
        self.assertFalse(result["complete"])

    def test_ubisoft_requires_qualifications(self):
        listing = {"content": [{"id": "1", "name": "Game Developer"}]}
        incomplete = {"active": True, "jobAd": {"sections": {"jobDescription": {"text": "Linux"}}},
                      "location": {"country": "cn"}}
        with patch("radar.fetch_json", side_effect=[listing, incomplete]) as fetch:
            self.assertEqual(list(employer_feeds.ubisoft(fetch)), [])

    def test_china_offices_and_plural_new_grads(self):
        source = {"type": "lever", "board": "weride", "company": "文远知行", "china_only": True}
        args = (source, "1", "New Grads 2026 - Software Engineer", "Build C++ systems", "https://example.org/1")
        self.assertIsNone(radar.make_job(*args, "San Jose, CA"))
        self.assertEqual(radar.make_job(*args, "China")["priority"], "P0")
