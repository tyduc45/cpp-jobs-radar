"""China postings from employers' public Workday and SmartRecruiters boards."""
import re
from urllib.error import HTTPError

NVIDIA_SITE = "https://nvidia.wd5.myworkdayjobs.com"
NVIDIA_API = NVIDIA_SITE + "/wday/cxs/nvidia/NVIDIAExternalCareerSite"
CHINA_FACET = "2fcb99c455831013ea529fe151e3323c"


def detail(fetch, url):
    try:
        return fetch(url)
    except HTTPError as exc:
        if exc.code in (404, 410):  # Posting withdrawn between list and detail reads.
            return None
        raise


def nvidia(fetch):
    seen = set()
    for keyword in ("intern", "compiler", "CUDA", "HPC", "Linux", "driver"):
        query = {"appliedFacets": {"locationHierarchy1": [CHINA_FACET]},
                 "limit": 5, "offset": 0, "searchText": keyword}
        rows = fetch(NVIDIA_API + "/jobs", payload=query)["jobPostings"]
        if not isinstance(rows, list):
            raise ValueError("Invalid NVIDIA job search response")
        for row in rows:
            path = row["externalPath"]
            if not path.startswith("/job/") or path in seen:
                continue
            seen.add(path)
            response = detail(fetch, NVIDIA_API + path)
            if response is None:
                continue
            job = response["jobPostingInfo"]
            if not job.get("canApply") or not job.get("jobDescription"):
                continue
            locations = [job["location"], *(job.get("additionalLocations") or [])]
            yield dict(raw_id=job["jobReqId"], title=job["title"], description=job["jobDescription"],
                       url=job["externalUrl"], location="; ".join(locations),
                       employment_type=job.get("timeType", ""), posted_at=job.get("startDate", ""))


def ubisoft(fetch):
    api = "https://api.smartrecruiters.com/v1/companies/Ubisoft2/postings"
    rows = fetch(api + "?country=cn&limit=100")["content"]
    if not isinstance(rows, list):
        raise ValueError("Invalid Ubisoft job search response")
    for row in rows:
        # Art and marketing JDs often mention the engine as an everyday tool.
        if not re.search(r"programmer|engineer|developer|technical artist|程序|研发|开发|技术美术", row["name"], re.I):
            continue
        response = detail(fetch, api + "/" + row["id"])
        if response is None or not response.get("active"):
            continue
        location = response["location"]
        if location["country"].lower() != "cn":
            continue
        sections = response["jobAd"]["sections"]
        if not all(sections.get(key, {}).get("text") for key in ("jobDescription", "qualifications")):
            continue
        description = " ".join(section["text"] for section in sections.values() if section.get("text"))
        yield dict(raw_id=response["id"], title=response["name"], description=description,
                   url=response["postingUrl"], location=location["fullLocation"], explicit_countries=["CN"],
                   employment_type=response.get("typeOfEmployment", {}).get("label", ""),
                   posted_at=response.get("releasedDate", ""))
