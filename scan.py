"""Scan company ATS boards and remote job feeds for TS/React/Node roles open to someone in Morocco.

Prints only matches not seen on a previous run (use --all to print everything).
Personal state lives in data/ (git-ignored):
  data/applied.txt     companies to skip, one per line (substring match)
  data/scan_seen.json  URLs already reported
  data/scan_latest.csv every match from the last run
"""
import csv, email.utils, html, json, os, re, sys, urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

sys.stdout.reconfigure(encoding="utf-8")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) job-finder/1.0"}
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

GREENHOUSE = ["gitlab", "remotecom", "hotjar", "docker", "sourcegraph", "mozilla", "wikimedia", "vercel", "automatticcareers",
              "canonical", "consensys", "kraken", "cloudflare", "elastic", "grafanalabs", "mongodb", "datadog", "toggl",
              "doist", "duckduckgo", "proton", "chainlinklabs", "okx", "binance", "bitpanda", "airtable", "figma",
              "hubspot", "zapier", "twilio", "contentful", "typeform", "jetbrains", "clickhouse", "netlify", "sentry",
              "planetscale", "appwrite", "storyblok", "strapi", "deliveroo", "glovo", "revolut", "wise", "n26", "monzo",
              "taxfix", "personio", "celonis", "miro", "pleo", "mollie", "adyen", "bolt", "workable", "toptal",
              "turing", "andela", "x-team", "10up", "humanmade", "wpengine", "kinsta", "yoast", "invisionapp", "buffer",
              "ghost", "helpscout", "close", "loom", "webflow", "oyster", "deel", "omnipresent", "lemlist",
              "brevo", "doctolib", "alan", "qonto", "swile", "backmarket", "ledger", "sorare", "payfit", "spendesk",
              "malt", "mirakl", "contentsquare", "dataiku", "algolia", "pennylane", "aircall", "agicap", "yousign"]
LEVER = ["Yassir", "proxify", "toptal", "binance", "kraken", "metabase", "jobgether", "weloglobal", "hostinger", "plaid",
         "zoox", "mistral", "dailymotion", "ledger", "swile", "brevo", "qonto", "voodoo", "deezer", "blablacar",
         "contentsquare", "alan", "spendesk", "ankorstore", "pigment", "sorare", "doctolib", "ornikar", "luko", "shift-technology"]
ASHBY = ["supabase", "posthog", "deel", "cal.com", "n8n", "linear", "replit", "raycast", "resend", "clerk", "neon",
         "railway", "render", "sanity", "payload", "trigger.dev", "inngest", "zed", "warp", "mistral", "huggingface",
         "elevenlabs", "synthesia", "photoroom", "dust", "pennylane", "alan", "qonto", "tiime", "lovable", "bolt.new",
         "remote", "oyster", "multiverse", "polar", "dub", "documenso", "formbricks", "twenty", "infisical",
         "stickermule", "toggl"]

TITLE_OK = re.compile(r"(front[ -]?end|full[ -]?stack|back[ -]?end|software engineer|software developer|web developer|"
                      r"mobile|react|typescript|node|javascript|product engineer|ai engineer|application engineer)", re.I)
TITLE_BAD = re.compile(r"(staff|principal|director|manager|head of|\bvp\b|lead|intern|android|ios\b|swift|kotlin|"
                       r"\.net|c#|java\b|golang|\bgo\b|rust|scala|ruby|php|elixir|data engineer|ml |machine learning|"
                       r"security|sre|site reliability|devops|qa|test|embedded|firmware|support|sales|solutions|"
                       r"salesforce|wordpress|shopify|unity|blockchain|solidity|web3|developer relations|documentation|"
                       r"platform|database|reliability|performance|release|finops|grc|operations|business|sdk|"
                       r"forward deployed|sage|angular|python)", re.I)
STACK = re.compile(r"\b(typescript|react|next\.?js|node\.?js|react native|expo)\b", re.I)
LOC_OK = re.compile(r"(anywhere(?! in (?!the world))|worldwide|global|emea|africa|morocco|mena|europe, middle east|^remote$)", re.I)
LOC_BAD = re.compile(r"\b(usa?|united states|us only|canada|north america|latam|latin america|americas|uk only|india|"
                     r"philippines|brazil|australia|apac|asia)\b", re.I)


def fetch(url):
    try:
        return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30).read().decode("utf-8", "replace")
    except Exception as e:
        print("  ! failed", url, e, file=sys.stderr)
        return ""


def fetch_json(url, default):
    try:
        return json.loads(fetch(url) or "null") or default
    except ValueError:
        return default


def _rss_date(s):
    try:
        return email.utils.parsedate_to_datetime(s).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return ""


def strip(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(s or "")))


# Each source returns (source, company, title, location, url, date, description)

def greenhouse(t):
    d = fetch_json(f"https://boards-api.greenhouse.io/v1/boards/{t}/jobs", {})
    return [("Greenhouse", t, j["title"], (j.get("location") or {}).get("name", ""), j["absolute_url"],
             (j.get("updated_at") or "")[:10], "") for j in d.get("jobs", [])]


def lever(t):
    d = fetch_json(f"https://api.lever.co/v0/postings/{t}?mode=json", [])
    out = []
    for j in d if isinstance(d, list) else []:
        c = j.get("categories", {})
        # workplaceType is just "remote", not where you can be, so only the location names count
        loc = " / ".join(filter(None, [c.get("location"), *(c.get("allLocations") or [])]))
        out.append(("Lever", t, j["text"], loc, j["hostedUrl"], "", ""))
    return out


def ashby(t):
    d = fetch_json(f"https://api.ashbyhq.com/posting-api/job-board/{t}", {})
    out = []
    for j in d.get("jobs", []):
        locs = [j.get("location") or ""] + [s.get("location", "") for s in j.get("secondaryLocations") or []]
        if j.get("isRemote") and not j.get("address"):
            locs.append("Remote")
        out.append(("Ashby", t, j["title"], " / ".join(filter(None, locs)), j.get("jobUrl", ""),
                    (j.get("publishedAt") or "")[:10], ""))
    return out


def remotive():
    d = fetch_json("https://remotive.com/api/remote-jobs?category=software-dev", {})
    return [("Remotive", j["company_name"], j["title"], j.get("candidate_required_location", ""), j["url"],
             (j.get("publication_date") or "")[:10], strip(j.get("description")) + " " + " ".join(j.get("tags") or []))
            for j in d.get("jobs", [])]


def remoteok():
    d = fetch_json("https://remoteok.com/api", [])
    return [("RemoteOK", j.get("company", ""), j.get("position", ""), j.get("location", ""), j.get("url", ""),
             (j.get("date") or "")[:10], strip(j.get("description")) + " " + " ".join(j.get("tags") or []))
            for j in d if isinstance(j, dict) and j.get("position")]


def wwr():
    out = []
    for cat in ["remote-full-stack-programming-jobs", "remote-front-end-programming-jobs", "remote-back-end-programming-jobs"]:
        xml = fetch(f"https://weworkremotely.com/categories/{cat}.rss")
        try:
            items = list(ET.fromstring(xml).iter("item")) if xml else []
        except ET.ParseError:
            items = []
        for it in items:
            company, _, role = (it.findtext("title") or "").partition(": ")
            out.append(("WWR", company, role or company, it.findtext("region") or "", it.findtext("link") or "",
                        _rss_date(it.findtext("pubDate")), strip(it.findtext("description"))))
    return out


def himalayas():
    out = []
    for offset in range(0, 400, 20):
        jobs = fetch_json(f"https://himalayas.app/jobs/api?limit=20&offset={offset}", {}).get("jobs", [])
        if not jobs:
            break
        for j in jobs:
            locs = ", ".join(j.get("locationRestrictions") or []) or "Worldwide"
            out.append(("Himalayas", j.get("companyName", ""), j.get("title", ""), locs,
                        j.get("applicationLink") or j.get("guid", ""), str(j.get("pubDate", ""))[:10],
                        strip(j.get("description")) + " " + " ".join(j.get("categories") or [])))
    return out


def location_ok(loc):
    if any(LOC_OK.search(part.strip()) for part in re.split(r"[/;|]", loc)):
        return not LOC_BAD.search(loc) or re.search(r"worldwide|anywhere|global", loc, re.I)
    return False


def matches(job):
    src, company, title, loc, url, date, desc = job
    if not TITLE_OK.search(title) or TITLE_BAD.search(title) or not location_ok(loc):
        return False
    # Company boards have no description to check; the feeds do, so require the stack there
    return not desc or bool(STACK.search(title + " " + desc))


def load_applied():
    try:
        with open(os.path.join(DATA, "applied.txt"), encoding="utf-8") as f:
            return [l.strip().lower() for l in f if l.strip() and not l.startswith("#")]
    except OSError:
        return []


def main():
    show_all = "--all" in sys.argv
    tasks = ([(greenhouse, t) for t in GREENHOUSE] + [(lever, t) for t in LEVER] + [(ashby, t) for t in ASHBY]
             + [(f, None) for f in (remotive, remoteok, wwr, himalayas)])
    with ThreadPoolExecutor(16) as pool:
        jobs = [j for batch in pool.map(lambda t: t[0](t[1]) if t[1] else t[0](), tasks) for j in batch]

    applied = load_applied()
    hits, keys = [], set()
    for j in jobs:
        key = (j[1].lower().strip(), j[2].lower().strip())
        if key in keys or any(a in j[1].lower() for a in applied) or not matches(j):
            continue
        keys.add(key)
        yrs = re.findall(r"(\d+)\+?\s*(?:-\s*\d+\s*)?years?", j[6])
        hits.append({"date": j[5], "source": j[0], "company": j[1], "title": j[2], "location": j[3],
                     "min_years": min(map(int, yrs)) if yrs else "", "url": j[4]})

    os.makedirs(DATA, exist_ok=True)
    seen_path = os.path.join(DATA, "scan_seen.json")
    try:
        with open(seen_path, encoding="utf-8") as f:
            seen = set(json.load(f))
    except (OSError, ValueError):
        seen = set()
    new = [h for h in hits if h["url"] not in seen]

    with open(os.path.join(DATA, "scan_latest.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(hits[0]) if hits else ["url"])
        w.writeheader()
        w.writerows(hits)
    # Keep old URLs too: a board that fails to load once shouldn't make its jobs look new next run.
    # Only matching jobs are stored (a few dozen a week), so the file stays tiny.
    with open(seen_path, "w", encoding="utf-8") as f:
        json.dump(sorted(seen | {h["url"] for h in hits}), f)

    print(f"scanned {len(jobs)} postings, {len(hits)} matches, {len(new)} new")
    for h in sorted(hits if show_all else new, key=lambda h: h["date"], reverse=True):
        print(" | ".join(str(h[k]) for k in ("date", "source", "company", "title", "location", "min_years", "url")))


if __name__ == "__main__":
    main()
