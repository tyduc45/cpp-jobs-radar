"""Read a bounded sample of Tencent's public search and full job descriptions."""
from urllib.parse import urlencode

KEYWORDS = ("C++", "引擎", "CUDA", "HPC", "Linux", "驱动", "编译器")
API = "https://careers.tencent.com/tencentcareer/api/post/"


def query(fetch, endpoint, **params):
    response = fetch(API + endpoint + "?" + urlencode({**params, "language": "zh-cn"}))
    if response.get("Code") != 200 or not isinstance(response.get("Data"), dict):
        raise ValueError("Invalid Tencent Careers response")
    return response["Data"]


def postings(fetch):
    seen = set()
    for keyword in KEYWORDS:
        rows = query(fetch, "Query", keyword=keyword, pageIndex=1, pageSize=5)["Posts"]
        if not isinstance(rows, list):
            raise ValueError("Invalid Tencent search results")
        for row in rows:
            key = str(row["PostId"])
            if not key.isascii() or not key.isdigit() or key in seen or row.get("IsValid") is not True or row.get("CountryName") != "中国":
                continue
            seen.add(key)
            detail = query(fetch, "ByPostId", postId=key)
            if str(detail.get("PostId")) != key or not detail.get("Requirement") or not detail.get("Responsibility"):
                continue
            yield detail
