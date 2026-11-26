import unittest
from unittest.mock import patch
from datetime import datetime, timezone, timedelta

import radar
from seniority import rank_role


class ChinaTests(unittest.TestCase):
    def test_rank(self):
        for title, requirement, rank in [
            ("编译器校招", "", "P0"), ("CUDA 实习生", "", "P0"), ("Linux 开发", "经验不限", "P1"),
            ("驱动开发", "1–3年开发经验", "P1"), ("工程师", "", "P2"), ("工程师", "三年以上工作经验", "P3"),
            ("校园招聘负责人", "", "P4"), ("初级开发", "十年以上开发经验", "P4"),
            ("Compiler Intern", "", "P0"), ("Software Engineer", "5+ years of experience", "P4"),
        ]:
            with self.subTest(title=title, requirement=requirement):
                self.assertEqual(rank_role(title, requirement)[0], rank)

    def test_search_visibility_and_screening(self):
        source = {"type": "tencent", "board": "china", "company": "腾讯"}
        row = {"PostId": "42", "CountryName": "中国", "IsValid": True}
        detail = {"PostId": "42", "RecruitPostName": "编译器实习", "Responsibility": "研发编译器",
                  "Requirement": "熟悉 LLVM", "LocationName": "深圳"}
        search = {"Code": 200, "Data": {"Posts": [row]}}
        with patch("tencent.KEYWORDS", ["编译器", "C++"]), patch("radar.fetch_json", side_effect=[
                search, {"Code": 200, "Data": detail}, search]):
            result = radar.fetch_source(source)
        self.assertEqual(result["matched"], 1)
        self.assertFalse(result["complete"])
        now = datetime.now(timezone.utc)
        state = {}
        radar.merge_results(state, [result], now.isoformat())
        radar.merge_results(state, [{**result, "jobs": []}], (now + timedelta(hours=24)).isoformat())
        job, = state["jobs"].values()
        self.assertEqual((job["priority"], job["countries"], job["last_seen"]), ("P0", ["CN"], now.isoformat()))
        self.assertTrue(job["active"])
        self.assertFalse(radar.is_current(job, {}, now + timedelta(hours=73)))
        detail["Requirement"] = "仅限中国公民"
        with patch("tencent.KEYWORDS", ["编译器"]), patch("radar.fetch_json", side_effect=[
                search, {"Code": 200, "Data": detail}]):
            self.assertEqual(radar.fetch_source(source)["excluded"], 1)
