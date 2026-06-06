"""
news_fetcher.py
Fetches and scores news from multiple sources:
  1. Google News RSS — company specific news
  2. RBI RSS feed — monetary policy, rate decisions
  3. PIB (Press Information Bureau) — government policy
  4. BSE announcements — already in data_collector
  5. Economic Times RSS — market news
  6. Moneycontrol RSS — sector news

Sentiment scoring:
  BULLISH keywords → +ve score
  BEARISH keywords → -ve score
"""

import asyncio, re, logging, time
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import httpx

log = logging.getLogger("news_fetcher")

# Cache
_NEWS_CACHE: Dict[str, dict] = {}
_NEWS_TS: Dict[str, float]   = {}
NEWS_TTL = 20 * 60  # 20 min cache

def _cache_get(k): return _NEWS_CACHE[k] if k in _NEWS_CACHE and time.time()-_NEWS_TS.get(k,0)<NEWS_TTL else None
def _cache_set(k,v): _NEWS_CACHE[k]=v; _NEWS_TS[k]=time.time()

# Sentiment keywords
BULL_WORDS = [
    "profit","growth","record","high","surge","rally","beat","strong","positive",
    "order","contract","win","award","approved","cleared","launch","expand",
    "upgrade","buy","target","bullish","outperform","dividend","bonus","buyback",
    "revenue increase","margin expansion","export","capex","investment",
    "rate cut","stimulus","boost","recovery","uptick","gain","rise","soar",
]
BEAR_WORDS = [
    "loss","decline","fall","drop","crash","weak","miss","disappoint","concern",
    "risk","warning","penalty","fine","probe","investigation","fraud","default",
    "debt","cut","layoff","closure","suspend","ban","reject","cancel","resign",
    "rate hike","inflation","recession","slowdown","downturn","sell","reduce",
    "underperform","downgrade","negative","poor","below expectation",
]
GOVT_BULL = [
    "infrastructure","make in india","production linked","PLI","capex",
    "allocation","budget increase","subsidy","tax relief","export promotion",
    "defence spending","railway budget","digital india","startup",
]
GOVT_BEAR = [
    "tax increase","cess","windfall tax","price cap","ban","restriction",
    "import duty","regulation","compliance","penalty","probe",
]

def score_text(text: str) -> dict:
    """Score news text for sentiment. Returns score -10 to +10."""
    t = text.lower()
    bull = sum(1 for w in BULL_WORDS if w in t)
    bear = sum(1 for w in BEAR_WORDS if w in t)
    gb   = sum(1 for w in GOVT_BULL  if w in t)
    gb2  = sum(1 for w in GOVT_BEAR  if w in t)
    raw  = (bull + gb) - (bear + gb2)
    score = max(-10, min(10, raw))
    sentiment = "bullish" if score > 1 else "bearish" if score < -1 else "neutral"
    return {"score": score, "sentiment": sentiment, "bull_words": bull, "bear_words": bear}

def parse_rss(xml: str, limit=10) -> List[dict]:
    """Simple RSS XML parser — no external deps."""
    items = []
    # Find all <item> blocks
    raw_items = re.findall(r'<item>(.*?)</item>', xml, re.DOTALL)
    for raw in raw_items[:limit]:
        title = re.search(r'<title[^>]*>(.*?)</title>', raw, re.DOTALL)
        desc  = re.search(r'<description[^>]*>(.*?)</description>', raw, re.DOTALL)
        link  = re.search(r'<link[^>]*>(https?://[^<]+)</link>', raw)
        pub   = re.search(r'<pubDate[^>]*>(.*?)</pubDate>', raw, re.DOTALL)

        title_txt = re.sub(r'<[^>]+>','', title.group(1) if title else '').strip()
        desc_txt  = re.sub(r'<[^>]+>','', desc.group(1)  if desc  else '').strip()[:200]
        link_txt  = link.group(1).strip() if link else ''
        pub_txt   = pub.group(1).strip()  if pub  else ''

        if title_txt:
            full_text = title_txt + ' ' + desc_txt
            s = score_text(full_text)
            items.append({
                "title":     title_txt,
                "summary":   desc_txt,
                "link":      link_txt,
                "published": pub_txt,
                "sentiment": s["sentiment"],
                "score":     s["score"],
            })
    return items

async def _fetch_rss(url: str, referer="https://www.google.com") -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; BSEAlpha/1.0)",
        "Accept":     "application/rss+xml, application/xml, text/xml, */*",
        "Referer":    referer,
    }
    try:
        async with httpx.AsyncClient(timeout=10, verify=False) as c:
            r = await c.get(url, headers=headers, follow_redirects=True)
            if r.status_code == 200:
                return r.text
    except Exception as e:
        log.debug(f"RSS fetch failed {url[:50]}: {e}")
    return ""

# ── Company News ─────────────────────────────────────────────────────────────
async def fetch_company_news(symbol: str, company_name: str) -> List[dict]:
    """Fetch company-specific news from Google News RSS."""
    ck = f"news_{symbol}"
    cached = _cache_get(ck)
    if cached: return cached

    # Google News RSS for company
    query = company_name.replace(' ', '+')
    url = f"https://news.google.com/rss/search?q={query}+stock+BSE+NSE&hl=en-IN&gl=IN&ceid=IN:en"
    xml = await _fetch_rss(url)
    news = parse_rss(xml, limit=8) if xml else []
    _cache_set(ck, news)
    return news

# ── RBI News ─────────────────────────────────────────────────────────────────
async def fetch_rbi_news() -> List[dict]:
    """RBI press releases — rate decisions, policy."""
    ck = "news_rbi"
    cached = _cache_get(ck)
    if cached: return cached

    # RBI RSS feed
    xml = await _fetch_rss("https://rbi.org.in/scripts/rss.aspx", "https://rbi.org.in")
    news = parse_rss(xml, limit=5) if xml else []

    # Fallback: Google News for RBI
    if not news:
        xml2 = await _fetch_rss(
            "https://news.google.com/rss/search?q=RBI+repo+rate+monetary+policy+India&hl=en-IN&gl=IN&ceid=IN:en"
        )
        news = parse_rss(xml2, limit=5) if xml2 else []

    _cache_set(ck, news)
    return news

# ── Government Policy News ────────────────────────────────────────────────────
async def fetch_govt_news() -> List[dict]:
    """Government/Finance Ministry/Budget news."""
    ck = "news_govt"
    cached = _cache_get(ck)
    if cached: return cached

    url = "https://news.google.com/rss/search?q=India+government+budget+policy+infrastructure+2025&hl=en-IN&gl=IN&ceid=IN:en"
    xml = await _fetch_rss(url)
    news = parse_rss(xml, limit=6) if xml else []
    _cache_set(ck, news)
    return news

# ── Sector News ───────────────────────────────────────────────────────────────
SECTOR_QUERIES = {
    "IT":         "India+IT+sector+Infosys+TCS+technology",
    "Telecom":    "India+telecom+5G+BSNL+Jio+Airtel",
    "Industrial": "India+industrial+manufacturing+capex",
    "Chemicals":  "India+chemicals+exports+specialty",
    "Consumer":   "India+FMCG+consumer+demand+rural",
    "Defence":    "India+defence+HAL+BEL+order",
    "Auto":       "India+automobile+EV+sales",
    "Finance":    "India+NBFC+housing+finance+RBI",
    "Fintech":    "India+fintech+payments+digital",
    "Logistics":  "India+logistics+supply+chain",
    "Metals":     "India+steel+metal+commodity",
    "Textiles":   "India+textile+export+cotton",
    "Infra":      "India+infrastructure+roads+metro",
    "Services":   "India+services+exports+GDP",
}

async def fetch_sector_news(sector: str) -> List[dict]:
    """Fetch sector-specific news."""
    ck = f"news_sector_{sector}"
    cached = _cache_get(ck)
    if cached: return cached

    query = SECTOR_QUERIES.get(sector, f"India+{sector}+sector+stock")
    url = f"https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"
    xml = await _fetch_rss(url)
    news = parse_rss(xml, limit=5) if xml else []
    _cache_set(ck, news)
    return news

# ── Market News ───────────────────────────────────────────────────────────────
async def fetch_market_news() -> List[dict]:
    """General market news — Sensex, Nifty, FII."""
    ck = "news_market"
    cached = _cache_get(ck)
    if cached: return cached

    url = "https://news.google.com/rss/search?q=Sensex+Nifty+BSE+NSE+smallcap+midcap+India+stock&hl=en-IN&gl=IN&ceid=IN:en"
    xml = await _fetch_rss(url)
    news = parse_rss(xml, limit=8) if xml else []
    _cache_set(ck, news)
    return news

# ── Aggregate news score for a company ───────────────────────────────────────
async def get_news_score(symbol: str, company_name: str, sector: str) -> dict:
    """
    Get aggregated news sentiment score for a company.
    Combines: company news + sector news + RBI/govt news
    Returns score -10 to +10 and top news items.
    """
    company_task = asyncio.create_task(fetch_company_news(symbol, company_name))
    sector_task  = asyncio.create_task(fetch_sector_news(sector))

    company_news, sector_news = await asyncio.gather(company_task, sector_task, return_exceptions=True)
    if isinstance(company_news, Exception): company_news = []
    if isinstance(sector_news,  Exception): sector_news  = []

    all_news = company_news + sector_news
    if not all_news:
        return {"score": 0, "sentiment": "neutral", "news": [], "top_news": []}

    scores = [n["score"] for n in all_news if n.get("score") is not None]
    avg = sum(scores)/len(scores) if scores else 0

    # Top 3 most impactful news
    sorted_news = sorted(all_news, key=lambda x: abs(x.get("score",0)), reverse=True)

    return {
        "score":     round(avg, 1),
        "sentiment": "bullish" if avg > 0.5 else "bearish" if avg < -0.5 else "neutral",
        "total":     len(all_news),
        "bull_count": sum(1 for n in all_news if n["sentiment"]=="bullish"),
        "bear_count": sum(1 for n in all_news if n["sentiment"]=="bearish"),
        "top_news":  sorted_news[:4],
        "all_news":  all_news[:8],
    }

# ── Fetch all shared news (RBI + Govt + Market) ───────────────────────────────
async def fetch_shared_news() -> dict:
    """Fetch RBI + Govt + Market news — shared across all companies."""
    ck = "shared_news"
    cached = _cache_get(ck)
    if cached: return cached

    rbi_t   = asyncio.create_task(fetch_rbi_news())
    govt_t  = asyncio.create_task(fetch_govt_news())
    mkt_t   = asyncio.create_task(fetch_market_news())

    rbi, govt, mkt = await asyncio.gather(rbi_t, govt_t, mkt_t, return_exceptions=True)
    if isinstance(rbi,  Exception): rbi  = []
    if isinstance(govt, Exception): govt = []
    if isinstance(mkt,  Exception): mkt  = []

    all_news = rbi + govt + mkt
    macro_score = sum(n.get("score",0) for n in all_news)/len(all_news) if all_news else 0

    result = {
        "rbi_news":     rbi[:4],
        "govt_news":    govt[:4],
        "market_news":  mkt[:5],
        "macro_score":  round(macro_score, 1),
        "macro_sentiment": "bullish" if macro_score>0.5 else "bearish" if macro_score<-0.5 else "neutral",
    }
    _cache_set(ck, result)
    return result
