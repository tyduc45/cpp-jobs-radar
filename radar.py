"""Public C++ job feeds, durable discovery state, SMTP digest and static export.

Python 3.12+, standard library only. Never executes or renders remote HTML.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import io
import json
import os
import re
import smtplib
import ssl
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formatdate
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from classify import COUNTRIES, classify
from eligibility import SCREENING_VERSION, screen_job, passes_screening, is_visible
from freshness import is_current, visible_until, DEFAULT_MAX_UNVERIFIED_HOURS

ROOT = Path(__file__).resolve().parent
CPP = re.compile(r"(?<![A-Za-z0-9_])(?:c\s*\+\s*\+|c＋＋|cpp\b|c\s+plus\s+plus)(?![A-Za-z_])", re.I)
USER_AGENT = "CppJobsRadar/1.0 (+https://github.com/tyduc45/cpp-jobs-radar)"


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1
        if tag in ("p", "li", "br", "div"):
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.hidden = max(0, self.hidden - 1)
        self.parts.append(" ")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain(value):
    parser = PlainText()
    parser.feed(html.unescape(str(value or "")))
    return re.sub(r"\s+", " ", " ".join(parser.parts)).strip()


def canonical_url(value):
    parts = urlsplit(str(value or ""))
    if parts.scheme not in ("http", "https") or not parts.netloc or parts.username:
        raise ValueError("Invalid public job URL")
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in ("gh_src", "source", "ref", "lever-source")]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), urlencode(sorted(query)), ""))


def fetch_json(url):
    for attempt in range(3):
        try:
            request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            with urlopen(request, timeout=45) as response:
                return json.load(response)
        except (HTTPError, URLError, TimeoutError) as exc:
            if isinstance(exc, HTTPError) and exc.code not in (429, 500, 502, 503, 504):
                raise
            if attempt == 2:
                raise
            delay = min(30, 2 ** (attempt + 1))
            if isinstance(exc, HTTPError):
                retry = exc.headers.get("Retry-After", "")
                if retry.isdigit():
                    delay = min(60, int(retry))
            time.sleep(delay)


def source_id(source):
    return f"{source['type']}:{source['board']}"


def make_job(source, raw_id, title, description, url, location="", **extra):
    title, description = plain(title), plain(description)
    match = CPP.search(title) or CPP.search(description)
    if not match:
        return None
    url = canonical_url(url)
    excerpt_match = CPP.search(description)
    excerpt = description[max(0, excerpt_match.start() - 90):excerpt_match.end() + 220] if excerpt_match else title
    attributes = classify(title, plain(location), description, extra.get("employment_type", ""),
                          extra.pop("workplace_hint", ""), extra.pop("explicit_countries", None))
    return {
        "id": hashlib.sha256(url.encode()).hexdigest()[:24],
        "source_id": source_id(source), "source_job_id": str(raw_id),
        "company": source["company"], "title": title, "url": url,
        "location": plain(location) or "未注明地点", "excerpt": excerpt,
        "match": "title" if CPP.search(title) else "description", **extra, **attributes,
        "screening": screen_job(title, description),
    }


def fetch_source(source):
    kind, board = source["type"], source["board"]
    jobs, total = [], 0
    if kind == "greenhouse":
        response = fetch_json(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true")
        rows = response["jobs"]
        if not isinstance(rows, list):
            raise ValueError("Invalid Greenhouse jobs response")
        if response.get("meta", {}).get("total", len(rows)) != len(rows):
            raise ValueError("Incomplete Greenhouse snapshot; refusing to expire jobs")
        if len({row["id"] for row in rows}) != len(rows):
            raise ValueError("Duplicate Greenhouse IDs; refusing incomplete snapshot")
        for row in rows:
            total += 1
            location = (row.get("location") or {}).get("name", "")
            metadata = row.get("metadata") or []
            employment = " ".join(str(m.get("value") or "") for m in metadata if re.search(r"employment|commitment|job type", m.get("name", ""), re.I))
            workplace = " ".join(str(m.get("value") or "") for m in metadata if re.search(r"workplace|work (?:type|model|arrangement)|remote", m.get("name", ""), re.I))
            job = make_job(source, row["id"], row["title"], row.get("content", ""), row["absolute_url"], location,
                           department=", ".join(d["name"] for d in row.get("departments", [])),
                           posted_at=row.get("first_published", ""), updated_at=row.get("updated_at", ""),
                           application_deadline=row.get("application_deadline", ""),
                           remote=bool(re.search(r"\bremote\b", location, re.I)), employment_type=employment,
                           workplace_hint=workplace, salary="")
            if job:
                jobs.append(job)
    elif kind == "lever":
        offset, page_size = 0, 100
        seen_pages = set()
        seen_ids = set()
        while True:
            host = "api.eu.lever.co" if source.get("region") == "eu" else "api.lever.co"
            rows = fetch_json(f"https://{host}/v0/postings/{board}?mode=json&skip={offset}&limit={page_size}")
            if not isinstance(rows, list):
                raise ValueError("Invalid Lever jobs response")
            fingerprint = tuple(row["id"] for row in rows)
            if rows and fingerprint in seen_pages:
                raise ValueError("Lever pagination repeated; refusing incomplete snapshot")
            seen_pages.add(fingerprint)
            if len(set(fingerprint)) != len(fingerprint) or seen_ids.intersection(fingerprint):
                raise ValueError("Overlapping Lever pages; refusing incomplete snapshot")
            seen_ids.update(fingerprint)
            for row in rows:
                total += 1
                cat = row.get("categories") or {}
                description = " ".join([row.get("descriptionPlain", row.get("description", "")),
                    row.get("additionalPlain", row.get("additional", ""))] +
                    [str(v.get("content", "")) for v in row.get("lists", [])])
                job = make_job(source, row["id"], row["text"], description, row["hostedUrl"],
                    "; ".join(cat.get("allLocations") or [cat.get("location", "")]),
                    department=cat.get("team", ""), posted_at="", updated_at="",
                    remote=row.get("workplaceType") == "remote", workplace_hint=row.get("workplaceType", ""),
                    employment_type=cat.get("commitment", ""), salary="")
                if job:
                    jobs.append(job)
            if len(rows) < page_size:
                break
            offset += page_size
            if offset > 20000:
                raise ValueError("Lever pagination limit reached")
            time.sleep(0.35)
    elif kind == "ashby":
        rows = fetch_json(f"https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true")["jobs"]
        if not isinstance(rows, list):
            raise ValueError("Invalid Ashby jobs response")
        for row in rows:
            if row.get("isListed") is False:
                continue
            total += 1
            locations = [row.get("location", "")] + [x.get("location", "") for x in row.get("secondaryLocations", [])]
            job = make_job(source, row.get("id", row["jobUrl"]), row["title"],
                row.get("descriptionPlain", row.get("descriptionHtml", "")), row["jobUrl"], "; ".join(filter(None, locations)),
                department=row.get("department", ""), posted_at=row.get("publishedAt", ""), updated_at="",
                remote=row.get("isRemote", False), workplace_hint=row.get("workplaceType") or ("remote" if row.get("isRemote") else ""),
                explicit_countries=[(row.get("address") or {}).get("postalAddress", {}).get("addressCountry", "")] +
                    [(x.get("address") or {}).get("addressCountry", "") for x in row.get("secondaryLocations", [])],
                employment_type=row.get("employmentType", ""),
                salary=plain((row.get("compensation") or {}).get("scrapeableCompensationSalarySummary", "")))
            if job:
                jobs.append(job)
    else:
        raise ValueError(f"Unknown source type: {kind}")
    return {"id": source_id(source), "company": source["company"], "ok": True, "scanned": total,
            "matched": len(jobs), "eligible": sum(passes_screening(j) for j in jobs),
            "excluded": sum(j["screening"]["excluded"] for j in jobs), "jobs": jobs}


def read_json(path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def merge_results(state, results, now):
    """Failures never expire jobs. Only complete successful snapshots count."""
    jobs = state.setdefault("jobs", {})
    fresh = closed = 0
    for result in results:
        if not result["ok"]:
            continue
        seen = set()
        for job in result["jobs"]:
            key = job["id"]
            seen.add(key)
            old = jobs.get(key, {})
            if not old and passes_screening(job):
                fresh += 1
            jobs[key] = {**old, **job, "first_seen": old.get("first_seen", now), "last_seen": now,
                         "active": True, "misses": 0, "closed_at": None, "closure_reason": None,
                         "notified_at": old.get("notified_at")}
        for key, job in jobs.items():
            if job["source_id"] == result["id"] and key not in seen:
                job["misses"] = job.get("misses", 0) + 1
                if job.get("active", False):
                    job["active"] = False
                    job["closed_at"] = now
                    job["closure_reason"] = "absent_from_complete_feed"
                    closed += 1
    state.update(version=1, last_attempt=now,
                 sources=[{k: v for k, v in r.items() if k != "jobs"} for r in results],
                 last_new_count=fresh, last_closed_count=closed)
    if any(r["ok"] for r in results):
        state["last_success"] = now
    return fresh


def crawl(config, state_path):
    sources = [s for s in config["sources"] if s.get("enabled", True)]
    results = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        tasks = {pool.submit(fetch_source, source): source for source in sources}
        for task in as_completed(tasks):
            source = tasks[task]
            try:
                result = task.result()
                print(f"OK {source['company']}: {result['eligible']} visible, {result['excluded']} restricted / {result['matched']} C++ / {result['scanned']} jobs", flush=True)
            except Exception as exc:
                result = {"id": source_id(source), "company": source["company"], "ok": False,
                          "scanned": 0, "matched": 0, "error": f"{type(exc).__name__}: {exc}"[:240]}
                print(f"WARNING {source['company']}: {result['error']}", flush=True)
            results.append(result)
    state = read_json(state_path, {"version": 1, "jobs": {}})
    now = datetime.now(timezone.utc).isoformat()
    count = merge_results(state, sorted(results, key=lambda r: r["company"]), now)
    write_json(state_path, state)
    print(f"Discovered {count} new jobs; {sum(r['ok'] for r in results)}/{len(results)} sources succeeded.")
    print(f"Removed {state['last_closed_count']} jobs absent from complete feeds.")
    return 0 if any(r["ok"] for r in results) else 1


def export_site(config, state_path, output):
    state = read_json(state_path, {"jobs": {}})
    now = datetime.now(timezone.utc)
    jobs = [{**{k: v for k, v in job.items() if k not in ("notified_at", "misses", "source_job_id", "screening")},
             "visible_until": visible_until(job, config).isoformat()}
            for job in state["jobs"].values() if is_current(job, config, now)]
    freshness = {"max_unverified_hours": config.get("max_unverified_hours", DEFAULT_MAX_UNVERIFIED_HOURS),
        "closed_this_run": state.get("last_closed_count", 0),
        "closed_total": sum(not j.get("active", False) for j in state["jobs"].values()),
        "hidden_unverified": sum(is_visible(j) and not is_current(j, config, now) for j in state["jobs"].values())}
    active = [j for j in state["jobs"].values() if j["active"]]
    screening = {"version": SCREENING_VERSION,
        "excluded": sum(bool(j.get("screening", {}).get("excluded")) for j in active),
        "unreviewed": sum(j.get("screening", {}).get("version") != SCREENING_VERSION for j in active)}
    jobs.sort(key=lambda j: (j["first_seen"], j["company"], j["title"]), reverse=True)
    write_json(output, {"generated_at": datetime.now(timezone.utc).isoformat(), "timezone": config["timezone"],
        "last_success": state.get("last_success"), "last_attempt": state.get("last_attempt"),
        "new_count": state.get("last_new_count", 0), "sources": state.get("sources", []), "jobs": jobs,
        "country_labels": {code: entry[0] for code, entry in COUNTRIES.items()}, "screening": screening,
        "freshness": freshness})
    print(f"Exported {len(jobs)} active jobs to {output}")


def build_digest(jobs, config, sender, recipient, now=None):
    # Defense in depth: no caller can accidentally bypass the common JD filter.
    now = now or datetime.now(timezone.utc)
    jobs = [job for job in jobs if is_current(job, config, now)]
    if not jobs:
        raise ValueError("No current, screened, unrestricted jobs to include in an email")
    digest_id = hashlib.sha256("\n".join(sorted(j["id"] for j in jobs)).encode()).hexdigest()[:32]
    message = EmailMessage()
    message["Subject"] = f"[C++ Jobs Radar] 发现 {len(jobs)} 个新岗位"
    message["From"], message["To"] = sender, recipient
    message["Date"] = formatdate(localtime=False)
    message["Message-ID"] = f"<{digest_id}@cpp-jobs-radar.local>"
    website = config["site_url"]
    lines = [f"发现 {len(jobs)} 个新 C++ 相关岗位。完整列表见附件 CSV。", website, ""]
    cards = []
    for job in jobs[:60]:
        lines += [f"{job['title']} | {job['company']} | {job['location']}", job["url"], ""]
        cards.append(f"<li><a href='{html.escape(job['url'], quote=True)}'>{html.escape(job['title'])}</a>"
                     f"<br>{html.escape(job['company'])} · {html.escape(job['location'])}</li>")
    message.set_content("\n".join(lines))
    message.add_alternative(f"<html><body><h1>发现 {len(jobs)} 个新 C++ 相关岗位</h1>"
        f"<p><a href='{html.escape(website, quote=True)}'>打开岗位网页</a> · 全部新岗位见 CSV 附件；正文展示前 60 个。</p>"
        f"<ul>{''.join(cards)}</ul><p>首次抓取包含当前存量；此后按首次发现去重。以原始 JD 为准。</p></body></html>", subtype="html")
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(["岗位", "公司", "地点", "首次发现", "JD"])
    for job in jobs:
        # Prevent spreadsheet formula injection from external job text.
        cells = [job[k] for k in ("title", "company", "location", "first_seen", "url")]
        writer.writerow(["'" + str(c) if str(c).lstrip().startswith(("=", "+", "-", "@")) else c for c in cells])
    message.add_attachment(buffer.getvalue().encode("utf-8-sig"), maintype="text", subtype="csv", filename="new-cpp-jobs.csv")
    return message


def notify(config, state_path):
    state = read_json(state_path, {"jobs": {}})
    now = datetime.now(timezone.utc)
    pending = sorted((j for j in state["jobs"].values() if is_current(j, config, now) and not j.get("notified_at")),
                     key=lambda j: (j["first_seen"], j["company"], j["title"]), reverse=True)
    required = ["SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "MAIL_TO"]
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        print(f"::warning::Email is not configured: {', '.join(missing)}. {len(pending)} jobs remain queued.")
        return 2
    if not pending:
        print("No new jobs: no email sent.")
        return 0
    sender = os.environ.get("MAIL_FROM") or os.environ["SMTP_USER"]
    recipient = os.environ["MAIL_TO"]
    # Use the same cutoff for queue selection, message contents and receipts.
    message = build_digest(pending, config, sender, recipient, now=now)
    port = int(os.environ.get("SMTP_PORT") or "465")
    context = ssl.create_default_context()
    host = os.environ["SMTP_HOST"]
    if port == 465:
        client = smtplib.SMTP_SSL(host, port, context=context, timeout=60)
    else:
        client = smtplib.SMTP(host, port, timeout=60)
    with client:
        if port != 465:
            client.ehlo()
            client.starttls(context=context)
            client.ehlo()
        client.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
        refused = client.send_message(message, from_addr=sender, to_addrs=[recipient])
        if refused:
            raise RuntimeError("SMTP server refused the recipient")
        # Persist immediately after server acceptance, before QUIT may fail.
        now = datetime.now(timezone.utc).isoformat()
        for job in pending:
            job["notified_at"] = now
        state["last_email_sent"] = now
        write_json(state_path, state)
    print(f"SMTP accepted digest with {len(pending)} new jobs.")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("crawl", "build", "notify"))
    parser.add_argument("--config", type=Path, default=ROOT / "sources.json")
    parser.add_argument("--state", type=Path, default=ROOT / "data" / "state.json")
    args = parser.parse_args()
    config = read_json(args.config)
    if args.command == "crawl":
        return crawl(config, args.state)
    if args.command == "notify":
        return notify(config, args.state)
    export_site(config, args.state, ROOT / "site" / "jobs.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
