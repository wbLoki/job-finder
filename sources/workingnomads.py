"""Working Nomads: downloads the full remote-job list (read-only GET) and filters it locally."""
import collections
import datetime
import html
import json
import re
import threading
import time
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"
REFRESH_SECONDS = 30 * 60
FIELDS = ["id", "title", "slug", "company", "category_name", "description", "position_type", "tags", "locations",
          "pub_date", "salary_range", "experience_level", "apply_url", "expired"]
CONTRACT = {"ft": "full_time", "pt": "part_time", "fr": "freelance"}
LEVELS = {"ENTRY_LEVEL": 0, "MID_LEVEL": 2, "SENIOR_LEVEL": 5}  # rough years of experience per level
WORLDWIDE = {"anywhere", "worldwide"}

_cache = {"jobs": [], "at": 0, "error": None}
_lock = threading.Lock()


def _fetch():
    q = {"size": 10000, "_source": FIELDS, "sort": [{"pub_date": {"order": "desc"}}], "query": {"match_all": {}}}
    url = ("https://www.workingnomads.com/jobsapi/_search?source_content_type=application/json&source="
           + urllib.parse.quote(json.dumps(q)))
    d = json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=60))
    jobs, keys = [], set()
    for hit in d["hits"]["hits"]:
        j = hit["_source"]
        dup = ((j.get("title") or "").strip().lower(), (j.get("company") or "").strip().lower())
        if str(j.get("expired")).lower() == "true" or dup in keys:
            continue
        keys.add(dup)
        text = re.sub(r"<[^>]+>", " ", html.unescape(j.get("description") or ""))
        j["locations"] = [l.strip() for l in (j.get("locations") or []) if l and l.strip()] or ["Anywhere"]
        j["tags"] = j.get("tags") or []
        # Keywords match title, company, category and tags; descriptions mention too many unrelated roles.
        j["_search"] = " ".join([j.get("title") or "", j.get("company") or "", j.get("category_name") or "",
                                 " ".join(j["tags"])]).lower()
        j["_title"] = (j.get("title") or "").lower()
        j["_summary"] = re.sub(r"\s+", " ", text).strip()[:300]
        try:
            j["_ts"] = int(datetime.datetime.fromisoformat(j.get("pub_date") or "").timestamp())
        except ValueError:
            j["_ts"] = 0
        jobs.append(j)
    return jobs


def jobs():
    with _lock:
        if not _cache["jobs"] or time.time() - _cache["at"] > REFRESH_SECONDS:
            try:
                _cache["jobs"], _cache["at"], _cache["error"] = _fetch(), time.time(), None
            except Exception as e:  # keep serving the stale copy if a refresh fails
                _cache["error"] = str(e)
                if not _cache["jobs"]:
                    raise
        return _cache["jobs"]


def meta():
    js = jobs()
    return {
        "total": len(js),
        "categories": collections.Counter(j.get("category_name") or "Other" for j in js).most_common(),
        "locations": collections.Counter(l for j in js for l in j["locations"]).most_common(150),
        "updated": _cache["at"],
    }


def _matches(j, p, terms):
    if terms and not all(t in j["_title" if p.get("title_only") else "_search"] for t in terms):
        return False
    if p.get("wn_category") and (j.get("category_name") or "Other") != p["wn_category"]:
        return False
    if p.get("wn_location"):
        locs = {l.lower() for l in j["locations"]}
        if not (p["wn_location"].lower() in locs or (p.get("include_worldwide", True) and locs & WORLDWIDE)):
            return False
    contracts = [c for c in p.get("contracts", []) if c]
    if contracts and CONTRACT.get(j.get("position_type")) not in contracts:
        return False
    if p.get("max_exp") is not None:
        level = LEVELS.get(j.get("experience_level") or "")
        if level is None:
            if not p.get("include_unspecified_exp", True):
                return False
        elif level > p["max_exp"]:
            return False
    if p.get("posted_days") and j["_ts"] < time.time() - p["posted_days"] * 86400:
        return False
    if p.get("after_ts") and j["_ts"] <= p["after_ts"]:
        return False
    return True


def _find(p):
    # Working Nomads is remote-only, so a filter asking for on-site/hybrid roles excludes it entirely.
    remote = [r for r in p.get("remote", []) if r]
    if remote and "fulltime" not in remote:
        return []
    terms = [t for t in re.split(r"\s+", (p.get("q") or "").lower()) if t]
    found = [j for j in jobs() if _matches(j, p, terms)]
    if p.get("sort") != "newest" and terms:
        found.sort(key=lambda j: -sum(t in (j.get("title") or "").lower() for t in terms))
    return found


def newest(p):
    """Publish timestamp of the newest job matching the filters."""
    return max((j["_ts"] for j in _find(p)), default=None)


def count_newer(p, ts):
    return len(_find({**p, "after_ts": ts}))


def search(p, page=0, per_page=30):
    found = _find(p)
    chunk = found[page * per_page:(page + 1) * per_page]
    return {"total": len(found), "pages": -(-len(found) // per_page), "hits": [_normalize(j) for j in chunk]}


def _normalize(j):
    level = j.get("experience_level") or ""
    return {
        "source": "wn",
        "id": str(j.get("id")),
        "title": j.get("title"),
        "company": j.get("company"),
        "logo": None,
        "location": "Remote · " + ", ".join(j["locations"][:4]) + (f" +{len(j['locations']) - 4}" if len(j["locations"]) > 4 else ""),
        "contract": CONTRACT.get(j.get("position_type"), j.get("position_type")),
        "remote": "fulltime",
        "experience": LEVELS.get(level),
        "experience_label": level.replace("_LEVEL", "").title() if level else "",
        "category": j.get("category_name") or "",
        "role": ", ".join(j["tags"][:4]),
        "salary": j.get("salary_range") or "",
        "published": j.get("pub_date"),
        "published_ts": j["_ts"],
        "summary": j["_summary"],
        "url": f"https://www.workingnomads.com/jobs/{j.get('slug')}",
    }
