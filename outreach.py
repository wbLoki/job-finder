"""Find startups that just raised a seed / pre-seed round, then look up their website, job boards and public emails.

  python outreach.py                  new seed rounds from the last 7 days, with lookups
  python outreach.py --days 14        look further back
  python outreach.py --all            also show rounds already shown on a previous run
  python outreach.py lookup acme.com  careers, job boards and emails for one company (e.g. a LinkedIn poster's)
  python outreach.py linkedin         print LinkedIn post-search links for the last 24h, to open in your browser

Only emails published on the company's own website are listed. The website is guessed from the company
name (acme.com, acme.ai, getacme.com ...) and checked against the page title, so verify it before writing.
Writes data/outreach_latest.csv and remembers shown companies in data/outreach_seen.json.
"""
import csv, email.utils, html, json, os, re, sys, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

sys.stdout.reconfigure(encoding="utf-8")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"}
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

NEWS_QUERIES = [  # (query, language, country)
    ('"seed round"', "en-US", "US"), ('"seed funding"', "en-US", "US"), ('"pre-seed"', "en-US", "US"),
    ('"seed round" OR "pre-seed" Europe startup', "en-GB", "GB"),
    ('"seed" startup Morocco OR Africa OR MENA raises', "en-US", "US"),
    ('"levée de fonds" startup amorçage', "fr", "FR"), ('startup marocaine lève', "fr", "MA"),
]
EXTRA_FEEDS = ["https://www.wamda.com/feed", "https://disruptafrica.com/feed/", "https://techcabal.com/feed/"]

ROUND = re.compile(r"\b(pre-?seed|seed|amorçage|levée de fonds|lève)\b", re.I)
VERB = re.compile(r"\s+(?:raises|raised|secures|secured|closes|closed|lands|bags|nabs|snags|announces|gets|picks up|"
                  r"completes|lève|boucle|réalise|annonce)\b", re.I)
# Science and hardware startups rarely need a React / React Native developer
SKIP = re.compile(r"(bio|therap|pharma|drug|cancer|oncolog|clinical|medical device|diagnos|genom|enzyme|molecul|vaccine|"
                  r"mrna|rna\b|cell|solar|batter|energy|nuclear|fusion|mining|satellite|space|defen[cs]e|military|robot|"
                  r"drone|chip|semiconductor|quantum|materials|carbon|electrode|fund i+\b|venture fund|series [a-z]\b|"
                  r"food|restaurant|franchise|film|beverage|council|foundation|university)", re.I)
NOT_NAMES = re.compile(r"^(startup|start-up|exclusive|the|a|an|this|how|why)$", re.I)


def get(url, timeout=12):
    """(final_url, text) or (None, '') on any failure."""
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout)
        return r.geturl(), r.read(2_000_000).decode("utf-8", "replace")
    except Exception:
        return None, ""


def get_json(url):
    try:
        return json.loads(get(url)[1] or "null")
    except ValueError:
        return None


def text_of(page):
    page = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", page)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", page)))


# ---------- 1. funding news ----------

def news_items(days):
    urls = [("https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": f"{q} when:{days}d", "hl": hl, "gl": gl, "ceid": f"{gl}:{hl.split('-')[0]}"})) for q, hl, gl in NEWS_QUERIES]
    out = []
    with ThreadPoolExecutor(8) as pool:
        for xml in pool.map(lambda u: get(u, 20)[1], urls + EXTRA_FEEDS):
            try:
                items = ET.fromstring(xml).iter("item") if xml else []
                out += [(i.findtext("title") or "", i.findtext("link") or "", i.findtext("pubDate") or "") for i in items]
            except ET.ParseError:
                pass
    return out


def company_name(title):
    title = re.sub(r"\s+[-–|]\s+[^-–|]+$", "", html.unescape(title)).strip()  # drop " - Source"
    m = VERB.search(title)
    if not m:
        return None
    pre = re.sub(r"^(exclusive|breaking)\s*:\s*", "", title[:m.start()], flags=re.I)
    pre = re.sub(r"^.*[’']s\s+", "", pre)                                   # "London's Griffin"
    pre = re.sub(r"^.*\b(start-?up|company|platform|maker|provider|firm)\s+", "", pre, flags=re.I)
    words = [w for w in pre.split() if not w.lower().endswith("-based")]
    name = []
    for w in reversed(words):                                              # trailing capitalised words
        if w[:1].isupper() or w[:1].isdigit():
            name.insert(0, w)
        else:
            break
    name = " ".join(name).strip(" ,:;\"'")
    if not name or len(name) > 30 or NOT_NAMES.match(name) or len(name.split()) > 3:
        return None
    return name


def rounds(days):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    found = {}
    for title, link, pub in news_items(days):
        if not ROUND.search(title) or SKIP.search(title):
            continue
        try:
            when = email.utils.parsedate_to_datetime(pub)
        except (TypeError, ValueError):
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if when < since:
            continue
        name = company_name(title)
        if name and name.lower() not in found:
            found[name.lower()] = {"date": when.strftime("%Y-%m-%d"), "company": name,
                                   "news": re.sub(r"\s+[-–|]\s+[^-–|]+$", "", html.unescape(title))[:110], "link": link}
    return list(found.values())


# ---------- 2. company lookup ----------

def guess_site(name):
    slug = re.sub(r"[^a-z0-9]", "", name.lower())
    if len(slug) < 3:
        return None
    for host in [f"{slug}.com", f"{slug}.ai", f"{slug}.io", f"{slug}.co", f"get{slug}.com", f"{slug}.app",
                 f"try{slug}.com", f"{slug}hq.com", f"{slug}.tech", f"{slug}.fr", f"{slug}.ma"]:
        url, page = get(f"https://{host}", 8)
        if not page:
            continue
        head = page[:6000].lower()
        title = re.search(r"<title[^>]*>(.*?)</title>", head, re.S)
        if re.search(r"domain (is )?for sale|buy this domain|parked|hugedomains|dan\.com|sedo", head):
            continue
        if slug in re.sub(r"[^a-z0-9]", "", title.group(1) if title else "") or slug in re.sub(r"[^a-z0-9]", "", head[:2500]):
            final = urllib.parse.urlparse(url).hostname or host
            if slug[:5] in final.replace("-", ""):  # not redirected to some other company
                return final
    return None


ATS_LINK = re.compile(r"https?://(?:job-boards\.|boards\.)?(?:greenhouse\.io|jobs\.lever\.co|jobs\.ashbyhq\.com|"
                      r"apply\.workable\.com|[\w-]+\.recruitee\.com|[\w-]+\.teamtailor\.com|wellfound\.com/company|"
                      r"[\w-]+\.welcometothejungle\.com|[\w-]+\.notion\.site|jobs\.gem\.com|[\w-]+\.breezy\.hr)[^\s\"'<>]*", re.I)
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Case-sensitive on purpose: "John Smith, Co-founder" yes, "factory" (fa-cto-ry) no
PERSON = re.compile(r"\b([A-Z][a-zà-ÿ]+(?: [A-Z][a-zà-ÿ'-]+){1,2})\s*(?:[,–—|(-]|is (?:the |our )?)?\s*"
                    r"((?:[Cc]o-?)?[Ff]ounder|CEO|CTO)\b")
NOT_PERSON = re.compile(r"\b(Our|The|Meet|About|With|Team|Group|Director|Head|Chief|Officer|Read|Learn|Company|"
                        r"Founder|Founders|Inc|Ltd|Capital|Ventures|Partners)\b")
GENERIC_EMAIL = re.compile(r"^(abuse|privacy|legal|security|press|media|pr|\w*sales|support|help|billing|partnerships?|"
                           r"contractor|customerservice|noreply|no-reply|dpo|gdpr|compliance|account|feedback|email|"
                           r"webmaster|inquiries|general)@")


def ats_jobs(slug):
    """Open roles on Greenhouse / Lever / Ashby / Workable boards named after the company."""
    jobs = []
    d = get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs") or {}
    jobs += [("Greenhouse", j["title"], j["absolute_url"]) for j in d.get("jobs", [])]
    d = get_json(f"https://api.lever.co/v0/postings/{slug}?mode=json")
    jobs += [("Lever", j["text"], j["hostedUrl"]) for j in d] if isinstance(d, list) else []
    d = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}") or {}
    jobs += [("Ashby", j["title"], j.get("jobUrl", "")) for j in d.get("jobs", [])]
    d = get_json(f"https://apply.workable.com/api/v1/widget/accounts/{slug}") or {}
    jobs += [("Workable", j["title"], j.get("url", "")) for j in d.get("jobs", [])]
    return jobs


def lookup(domain, name=None):
    domain = re.sub(r"^https?://", "", domain).strip("/").split("/")[0]
    root = ".".join(domain.split(".")[-2:])
    base = f"https://{domain}"
    _, home = get(base)
    pages = {base: home}
    links = set(re.findall(r'href="([^"#?]+)"', home))
    wanted = [l for l in links if re.search(r"career|jobs|join|team|about|contact|company|hiring", l, re.I)]
    for path in ["/careers", "/jobs", "/about", "/team", "/contact"] + wanted[:8]:
        url = urllib.parse.urljoin(base + "/", path)
        if urllib.parse.urlparse(url).hostname and root in urllib.parse.urlparse(url).hostname and url not in pages:
            pages[url] = ""
    with ThreadPoolExecutor(8) as pool:
        for url, (final, page) in zip(list(pages)[1:], pool.map(get, list(pages)[1:])):
            pages[url] = page if final and root in (urllib.parse.urlparse(final).hostname or "") else ""

    allhtml = " ".join(pages.values())
    emails = sorted({e for e in (x.lower().rstrip(".") for x in EMAIL.findall(urllib.parse.unquote(allhtml)))
                     if (e.endswith("@" + root) or e.endswith("." + root)) and not GENERIC_EMAIL.match(e)})
    # Board root only (jobs.ashbyhq.com/acme), not every job link
    boards = sorted({"/".join(m.replace("\\", "").split("/")[:4]).rstrip("/.") for m in ATS_LINK.findall(allhtml)})[:2]
    people = []
    for p in pages.values():
        for who, role in PERSON.findall(text_of(p)):
            if not NOT_PERSON.search(who) and who not in " ".join(people):
                people.append(f"{who} ({role})")
    stack = [s for s, pat in [("Next.js", r"__NEXT_DATA__|/_next/"), ("React", r"data-reactroot|react-dom|/_next/"),
                              ("Vue/Nuxt", r"__NUXT__|data-v-[0-9a-f]{6}"), ("Webflow", r"webflow"), ("Framer", r"framerusercontent"),
                              ("iOS app", r"apps\.apple\.com"), ("Android app", r"play\.google\.com/store")]
             if re.search(pat, allhtml)]
    slug = re.sub(r"[^a-z0-9]", "", (name or domain.split(".")[0]).lower())
    jobs = ats_jobs(slug)
    careers = [u for u, p in pages.items() if p and re.search(r"career|jobs|join", u, re.I)]
    return {"site": domain, "emails": emails[:6], "people": people[:4], "stack": stack, "boards": boards,
            "careers": careers[:1], "jobs": jobs}


def eng_titles(jobs):
    return [t for _, t, _ in jobs if re.search(r"engineer|developer|front|full.?stack|mobile|react|software|founding", t, re.I)]


# ---------- 3. LinkedIn links ----------

LINKEDIN_QUERIES = ["recrute développeur react", "recrute développeur react native", "on recrute développeur front",
                    "we are hiring react developer remote", "hiring react native developer", "hiring frontend engineer remote",
                    "founding engineer react hiring"]


def linkedin_links():
    print("Open these in your browser (posts from the last 24h, newest first). Skip posts with 100+ reactions.\n")
    for q in LINKEDIN_QUERIES:
        url = ("https://www.linkedin.com/search/results/content/?keywords=" + urllib.parse.quote(q)
               + "&datePosted=%22past-24h%22&sortBy=%22date_posted%22")
        print(f"{q}\n  {url}")
    print("\nFound a good post? Run:  python outreach.py lookup <company website>")


# ---------- main ----------

def show_lookup(r, indent="    "):
    eng = eng_titles(r["jobs"])
    bits = [r["site"], ", ".join(r["stack"])]
    if r["jobs"]:
        bits.append(f"{len(r['jobs'])} jobs ({len(eng)} eng{': ' + '; '.join(eng[:3]) if eng else ''})")
    print(indent + " | ".join(b for b in bits if b))
    if r["careers"] or r["boards"]:
        print(f"{indent}careers: {' '.join(r['careers'] + r['boards'])}")
    if r["emails"] or r["people"]:
        print(f"{indent}contacts: {', '.join(r['people'] + r['emails'])}")


def main():
    args = sys.argv[1:]
    if args[:1] == ["linkedin"]:
        return linkedin_links()
    if args[:1] == ["lookup"] and len(args) > 1:
        return show_lookup(lookup(args[1]), indent="")

    days = int(args[args.index("--days") + 1]) if "--days" in args else 7
    seen_path = os.path.join(DATA, "outreach_seen.json")
    try:
        with open(seen_path, encoding="utf-8") as f:
            seen = set(json.load(f))
    except (OSError, ValueError):
        seen = set()

    found = rounds(days)
    new = [r for r in found if "--all" in args or r["company"].lower() not in seen]
    print(f"{len(found)} software-ish seed rounds in the last {days} days, {len(new)} to look up\n")

    def enrich(r):
        site = guess_site(r["company"])
        return {**r, **(lookup(site, r["company"]) if site else {"site": "", "emails": [], "people": [], "stack": [],
                                                                  "boards": [], "careers": [], "jobs": []})}

    with ThreadPoolExecutor(8) as pool:
        rows = list(pool.map(enrich, new))
    # Companies with open engineering roles or a found site first
    web = lambda r: any(s in r["stack"] for s in ("React", "Next.js", "iOS app", "Android app"))
    rows.sort(key=lambda r: (not r["site"], not eng_titles(r["jobs"]), not web(r), r["date"]))
    for r in [r for r in rows if r["site"]]:
        print(f"{r['date']} {r['company']}: {r['news']}")
        show_lookup(r)
    missing = [r["company"] for r in rows if not r["site"]]
    if missing:
        print(f"\nsite not found ({len(missing)}): {', '.join(missing)}")
    print("\nnews links: data/outreach_latest.csv")

    os.makedirs(DATA, exist_ok=True)
    with open(os.path.join(DATA, "outreach_latest.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "company", "news", "site", "stack", "eng_jobs", "careers", "emails", "people", "news_link"])
        for r in rows:
            w.writerow([r["date"], r["company"], r["news"], r["site"], ", ".join(r["stack"]), "; ".join(eng_titles(r["jobs"])),
                        " ".join(r["careers"] + r["boards"]), ", ".join(r["emails"]), ", ".join(r["people"]), r["link"]])
    with open(seen_path, "w", encoding="utf-8") as f:
        json.dump(sorted(seen | {r["company"].lower() for r in found}), f)


if __name__ == "__main__":
    main()
