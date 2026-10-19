"""Welcome to the Jungle: queries the same public Algolia index the WTTJ website uses."""
import json
import re
import threading
import time
import urllib.error
import urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"
INDEX = "wttj_jobs_production_en"
INDEX_NEWEST = "wttj_jobs_production_en_published_at_desc"
EXPERIENCE_VALUES = [0, 0.5, 1, 2, 3, 4, 5, 7, 10, 15]

_cred = {"app": None, "key": None, "at": 0}
_lock = threading.Lock()


def _credentials(force=False):
    """Read the public, search-only Algolia credentials WTTJ ships to every browser."""
    with _lock:
        if force or not _cred["key"] or time.time() - _cred["at"] > 6 * 3600:
            req = urllib.request.Request("https://www.welcometothejungle.com/api/env", headers={"User-Agent": UA})
            env = urllib.request.urlopen(req, timeout=20).read().decode()
            _cred["app"] = re.search(r'"PUBLIC_ALGOLIA_APPLICATION_ID"\s*:\s*"([^"]+)"', env).group(1)
            _cred["key"] = re.search(r'"PUBLIC_ALGOLIA_API_KEY_CLIENT"\s*:\s*"([^"]+)"', env).group(1)
            _cred["at"] = time.time()
        return _cred["app"], _cred["key"]


def _query(body, index=INDEX, retry=True):
    app, key = _credentials()
    req = urllib.request.Request(
        f"https://{app}-dsn.algolia.net/1/indexes/{index}/query",
        data=json.dumps(body).encode(),
        headers={
            "X-Algolia-Application-Id": app,
            "X-Algolia-API-Key": key,
            "Content-Type": "application/json",
            "Referer": "https://www.welcometothejungle.com/",
            "User-Agent": UA,
        },
    )
    try:
        return json.load(urllib.request.urlopen(req, timeout=20))
    except urllib.error.HTTPError as e:
        if retry and e.code in (401, 403):
            _credentials(force=True)
            return _query(body, index, retry=False)
        raise


def _label(ref):
    """'tech-engineering-3NjUy' -> 'Tech Engineering'"""
    return re.sub(r"-[A-Za-z0-9]{5}$", "", ref).replace("-", " ").title().replace(" And ", " & ")


def meta():
    d = _query({"query": "", "hitsPerPage": 0, "maxValuesPerFacet": 300,
                "facets": ["offices.country_code", "new_profession.category_reference", "contract_type", "remote", "language"]})
    f = d.get("facets", {})
    return {
        "total": d.get("nbHits", 0),
        "countries": sorted(f.get("offices.country_code", {}).items(), key=lambda kv: -kv[1]),
        "categories": [(k, _label(k), n) for k, n in sorted(f.get("new_profession.category_reference", {}).items(), key=lambda kv: -kv[1])],
        "contracts": f.get("contract_type", {}),
        "remote": f.get("remote", {}),
        "languages": sorted(f.get("language", {}).items(), key=lambda kv: -kv[1]),
    }


def cities(country):
    d = _query({"query": "", "hitsPerPage": 0, "maxValuesPerFacet": 300, "facets": ["offices.city"],
                "facetFilters": [[f"offices.country_code:{country}"]]})
    return sorted(d.get("facets", {}).get("offices.city", {}).items(), key=lambda kv: -kv[1])


def _esc(v):
    return '"' + str(v).replace('"', '\\"') + '"'


def _filters(p):
    filters = []
    if p.get("country"):
        filters.append(f"offices.country_code:{_esc(p['country'])}")
    if p.get("city"):
        filters.append(f"offices.city:{_esc(p['city'])}")
    if p.get("category"):
        filters.append(f"new_profession.category_reference:{_esc(p['category'])}")
    if p.get("language"):
        filters.append(f"language:{_esc(p['language'])}")

    contracts = [c for c in p.get("contracts", []) if c]
    if contracts:
        filters.append("(" + " OR ".join(f"contract_type:{_esc(c)}" for c in contracts) + ")")

    remote = [r for r in p.get("remote", []) if r]
    if remote:
        filters.append("(" + " OR ".join(f"remote:{_esc(r)}" for r in remote) + ")")

    if p.get("max_exp") is not None:
        # Algolia can't OR numeric and facet filters, so match the experience facet's discrete values instead.
        ok = [f'experience_level_minimum:"{float(v)}"' for v in EXPERIENCE_VALUES if v <= p["max_exp"]]
        if p.get("include_unspecified_exp", True):
            ok.append("has_experience_level_minimum:false")
        filters.append("(" + " OR ".join(ok) + ")" if ok else "has_experience_level_minimum:false")

    if p.get("posted_days"):
        filters.append(f"published_at_timestamp >= {int(time.time() - p['posted_days'] * 86400)}")
    if p.get("after_ts"):
        filters.append(f"published_at_timestamp > {int(p['after_ts'])}")
    return " AND ".join(filters)


def _body(p, **extra):
    body = {"query": p.get("q", ""), "filters": _filters(p), "attributesToHighlight": [], **extra}
    if p.get("title_only") and p.get("q"):
        body["restrictSearchableAttributes"] = ["name"]
    return body


def _index(p):
    return INDEX_NEWEST if p.get("sort") == "newest" else INDEX


def newest(p):
    """Publish timestamp of the newest job matching the filters."""
    d = _query(_body(p, hitsPerPage=1, attributesToRetrieve=["published_at_timestamp"]), INDEX_NEWEST)
    hits = d.get("hits") or []
    return hits[0].get("published_at_timestamp") if hits else None


def count_newer(p, ts):
    return _query(_body({**p, "after_ts": ts}, hitsPerPage=0)).get("nbHits", 0)


def search(p, page=0, per_page=30):
    body = _body(p, hitsPerPage=per_page, page=page,
                 attributesToRetrieve=["name", "slug", "organization", "offices", "contract_type", "remote",
                                       "experience_level_minimum", "published_at", "published_at_timestamp",
                                       "salary_minimum", "salary_maximum",
                                       "salary_currency", "salary_period", "new_profession", "summary", "language"])
    d = _query(body, _index(p))
    return {"total": d.get("nbHits", 0), "pages": d.get("nbPages", 0), "hits": [_normalize(h) for h in d.get("hits", [])]}


def _normalize(h):
    org = h.get("organization") or {}
    offices = h.get("offices") or []
    places = []
    for o in offices:
        s = ", ".join(x for x in (o.get("city"), o.get("country")) if x)
        if s and s not in places:
            places.append(s)
    salary = ""
    if h.get("salary_minimum") or h.get("salary_maximum"):
        lo, hi = h.get("salary_minimum"), h.get("salary_maximum")
        rng = f"{int(lo):,}" if lo else ""
        if hi and hi != lo:
            rng += f" – {int(hi):,}" if rng else f"up to {int(hi):,}"
        salary = f"{rng} {h.get('salary_currency') or ''}/{(h.get('salary_period') or '').replace('ly', '')}".strip()
    exp = h.get("experience_level_minimum")
    prof = h.get("new_profession") or {}
    logo = (org.get("logo") or {}).get("url") if isinstance(org.get("logo"), dict) else org.get("logo")
    return {
        "source": "wttj",
        "id": h.get("objectID"),
        "title": h.get("name"),
        "company": org.get("name"),
        "logo": logo,
        "location": " · ".join(places[:3]) + (f" +{len(places) - 3}" if len(places) > 3 else ""),
        "contract": h.get("contract_type"),
        "remote": h.get("remote"),
        "experience": None if exp is None else float(exp),
        "category": prof.get("category_name") or "",
        "role": prof.get("pivot_name") or "",
        "salary": salary,
        "published": h.get("published_at"),
        "published_ts": h.get("published_at_timestamp"),
        "summary": (h.get("summary") or "")[:300],
        "url": f"https://www.welcometothejungle.com/en/companies/{org.get('slug')}/jobs/{h.get('slug')}",
    }
