"""Internet and public-database tools. Everything fetched is untrusted DATA."""
import datetime as dt
import ipaddress
import json
import os
import re
import socket
import threading
import time
import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, quote, unquote, urlparse

import requests

UA = "Mozilla/5.0 (compatible; OrionAssistant/1.0; personal use)"
_cache, _clock = {}, threading.Lock()
MAX_BYTES = 1_500_000


# ---------- safe fetching ----------
def safe_url(url):
    """Only public http(s) addresses: never localhost, the home network or cloud metadata."""
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise ValueError("only http and https links are allowed")
    try:
        infos = socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == "https" else 80))
    except socket.gaierror:
        raise ValueError(f"cannot find {p.hostname}")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise ValueError("that address is on a private network, so I will not open it")
    return url


def _get(url, params=None, headers=None, method="GET", data=None, timeout=8):
    """Network layer (tests replace this). Follows redirects by hand so every hop is checked."""
    h = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.8"}
    h.update(headers or {})
    for _ in range(5):
        safe_url(url)
        r = requests.request(method, url, params=params, headers=h, data=data, timeout=timeout,
                             allow_redirects=False, stream=True)
        if r.is_redirect and r.headers.get("location"):
            url = requests.compat.urljoin(url, r.headers["location"])
            params, method, data = None, "GET", None
            r.close()
            continue
        body = b""
        for chunk in r.iter_content(65536):
            body += chunk
            if len(body) > MAX_BYTES:
                break
        r.close()
        return r.status_code, r.headers.get("content-type", ""), body, url
    raise ValueError("too many redirects")


def fetch(url, params=None, headers=None, method="GET", data=None, ttl=600):
    key = (method, url, json.dumps(params, sort_keys=True, default=str), str(data))
    with _clock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
    try:
        out = _get(url, params, headers, method, data)
    except requests.RequestException as e:
        raise RuntimeError(f"network problem ({type(e).__name__}); the internet may be unreachable")
    if out[0] >= 400:
        raise RuntimeError(f"HTTP {out[0]} from {urlparse(url).hostname}")
    with _clock:
        if len(_cache) > 200:
            _cache.clear()
        _cache[key] = (time.time(), out)
    return out


def getj(url, params=None, headers=None, ttl=600):
    return json.loads(fetch(url, params, headers, ttl=ttl)[2].decode("utf-8", "replace"))


# ---------- reading pages ----------
def html_to_text(html, limit=6000):
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
        title = (soup.title.string or "").strip() if soup.title and soup.title.string else ""
        for t in soup(["script", "style", "nav", "footer", "header", "aside", "form", "noscript", "svg", "iframe"]):
            t.decompose()
        root = soup.find("article") or soup.find("main") or soup.body or soup
        text = root.get_text("\n")
    except ImportError:
        title = (re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I) or [None, ""])[1].strip()
        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", "\n", text)
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in text.splitlines()]
    body = "\n".join(ln for ln in lines if len(ln) > 2)
    return title, re.sub(r"\n{3,}", "\n\n", body)[:limit]


def read_page(url, max_chars=6000):
    status, ctype, body, final = fetch(url, ttl=300)
    text = body.decode("utf-8", "replace")
    max_chars = max(500, min(int(max_chars), 12000))
    if "json" in ctype:
        return {"url": final, "type": "json", "text": text[:max_chars]}
    if "html" in ctype or text.lstrip().startswith("<"):
        title, body_text = html_to_text(text, max_chars)
        return {"url": final, "title": title, "text": body_text}
    return {"url": final, "text": text[:max_chars]}


# ---------- search ----------
def _ddg_target(href):
    if "uddg=" in href:
        return unquote(parse_qs(urlparse(href if href.startswith("http") else "https:" + href).query)["uddg"][0])
    return href


def parse_ddg(html, n):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    out = []
    for r in soup.select(".result"):
        a = r.select_one("a.result__a")
        if not a or "result--ad" in (r.get("class") or []):
            continue
        sn = r.select_one(".result__snippet")
        out.append({"title": a.get_text(" ", strip=True), "url": _ddg_target(a.get("href", "")),
                    "snippet": sn.get_text(" ", strip=True) if sn else ""})
        if len(out) >= n:
            break
    return out


def web_search(query, n=5):
    n = max(1, min(int(n), 8))
    errs = []
    if os.getenv("TAVILY_API_KEY"):
        try:
            _, _, body, _ = fetch("https://api.tavily.com/search", method="POST", ttl=600,
                                  headers={"Content-Type": "application/json"},
                                  data=json.dumps({"api_key": os.getenv("TAVILY_API_KEY"), "query": query,
                                                   "max_results": n, "include_answer": True}))
            d = json.loads(body)
            return {"answer": d.get("answer"), "results": [{"title": r["title"], "url": r["url"],
                    "snippet": r.get("content", "")[:400]} for r in d.get("results", [])][:n]}
        except Exception as e:
            errs.append(f"tavily: {e}")
    if os.getenv("BRAVE_API_KEY"):
        try:
            d = getj("https://api.search.brave.com/res/v1/web/search", {"q": query, "count": n},
                     {"X-Subscription-Token": os.getenv("BRAVE_API_KEY"), "Accept": "application/json"})
            return {"results": [{"title": r["title"], "url": r["url"], "snippet": re.sub("<[^>]+>", "", r.get("description", ""))}
                                for r in d.get("web", {}).get("results", [])][:n]}
        except Exception as e:
            errs.append(f"brave: {e}")
    try:
        _, _, body, _ = fetch("https://html.duckduckgo.com/html/", method="POST", ttl=600, data={"q": query},
                              headers={"Content-Type": "application/x-www-form-urlencoded"})
        res = parse_ddg(body.decode("utf-8", "replace"), n)
        if res:
            return {"results": res}
        errs.append("duckduckgo returned nothing")
    except Exception as e:
        errs.append(f"duckduckgo: {e}")
    try:                                         # last resort: Wikipedia's own search
        d = getj("https://en.wikipedia.org/w/api.php", {"action": "query", "list": "search", "srsearch": query,
                 "format": "json", "srlimit": n})
        res = [{"title": r["title"], "url": "https://en.wikipedia.org/wiki/" + quote(r["title"].replace(" ", "_")),
                "snippet": re.sub("<[^>]+>", "", r["snippet"])} for r in d["query"]["search"]]
        if res:
            return {"results": res, "note": "web search was unavailable; these are Wikipedia results"}
    except Exception as e:
        errs.append(f"wikipedia: {e}")
    raise RuntimeError("search failed: " + "; ".join(errs[-3:]))


# ---------- reference databases ----------
def wikipedia(topic, full=False):
    d = getj("https://en.wikipedia.org/w/api.php", {
        "action": "query", "format": "json", "generator": "search", "gsrsearch": topic, "gsrlimit": 1,
        "prop": "extracts|info", "inprop": "url", "explaintext": 1, "redirects": 1,
        **({"exchars": 6000} if full else {"exintro": 1, "exchars": 1800})})
    pages = (d.get("query") or {}).get("pages") or {}
    if not pages:
        return {"error": f"nothing on Wikipedia for '{topic}'"}
    p = sorted(pages.values(), key=lambda x: x.get("index", 0))[0]
    return {"title": p.get("title"), "url": p.get("fullurl"), "text": (p.get("extract") or "").strip()}


def define(word):
    try:
        d = getj("https://api.dictionaryapi.dev/api/v2/entries/en/" + quote(word.strip().lower()), ttl=86400)
    except RuntimeError:
        return {"error": f"no dictionary entry for '{word}'"}
    out = []
    for ent in d[:1]:
        for m in ent.get("meanings", [])[:3]:
            out.append({"part_of_speech": m.get("partOfSpeech"),
                        "meanings": [x["definition"] for x in m.get("definitions", [])[:2]]})
    return {"word": word, "phonetic": d[0].get("phonetic", ""), "entries": out}


def arxiv(query, n=4):
    _, _, body, _ = fetch("https://export.arxiv.org/api/query", {"search_query": "all:" + query, "max_results": max(1, min(int(n), 8)),
                                                               "sortBy": "relevance"}, ttl=3600)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    out = []
    for e in ET.fromstring(body).findall("a:entry", ns):
        g = lambda t: (e.findtext(f"a:{t}", "", ns) or "").strip()
        out.append({"title": re.sub(r"\s+", " ", g("title")), "published": g("published")[:10], "url": g("id"),
                    "summary": re.sub(r"\s+", " ", g("summary"))[:500]})
    return {"papers": out}


def exchange(amount, from_currency, to_currency):
    d = getj("https://api.frankfurter.app/latest", {"amount": amount, "from": from_currency.upper(), "to": to_currency.upper()}, ttl=3600)
    return {"amount": amount, "from": from_currency.upper(), "to": to_currency.upper(), "rates": d.get("rates"), "date": d.get("date")}


def parse_news(xml_bytes, n):
    out = []
    for it in ET.fromstring(xml_bytes).iter("item"):
        t = it.findtext("title", "")
        src = it.findtext("source", "")
        out.append({"title": t, "source": src, "published": it.findtext("pubDate", ""), "url": it.findtext("link", "")})
        if len(out) >= n:
            break
    return out


def news(topic="", n=6):
    n = max(1, min(int(n), 10))
    url = "https://news.google.com/rss/search" if topic else "https://news.google.com/rss"
    params = {"q": topic + " when:3d", "hl": "en-US", "gl": "US", "ceid": "US:en"} if topic else {"hl": "en-US", "gl": "US", "ceid": "US:en"}
    _, _, body, _ = fetch(url, params, ttl=300)
    return {"headlines": parse_news(body, n), "fetched": dt.datetime.now().strftime("%I:%M %p")}


# ---------- weather ----------
WMO = {0: "clear sky", 1: "mostly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "freezing fog",
       51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 56: "freezing drizzle", 57: "freezing drizzle",
       61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain", 67: "freezing rain",
       71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains", 80: "light showers", 81: "showers",
       82: "violent showers", 85: "snow showers", 86: "heavy snow showers", 95: "thunderstorm",
       96: "thunderstorm with hail", 99: "thunderstorm with heavy hail"}


def _pick_place(results, tail):
    if tail:
        t = tail.lower()
        for r in results:
            if t in (r.get("admin1", "") or "").lower() or t == (r.get("country_code", "") or "").lower() \
                    or t in (r.get("country", "") or "").lower() or t in (r.get("admin1", "") or "").lower()[:2]:
                return r
    return results[0]


_US = {"ca": "California", "ny": "New York", "tx": "Texas", "fl": "Florida", "wa": "Washington", "il": "Illinois"}


def make_weather(units, home):
    def weather(place=""):
        place = (place or home or "").strip()
        if not place:
            return {"error": "no place given and no home city set; ask the user where"}
        name, _, tail = place.partition(",")
        tail = tail.strip()
        tail = _US.get(tail.lower(), tail)
        g = getj("https://geocoding-api.open-meteo.com/v1/search", {"name": name.strip(), "count": 8, "language": "en"}, ttl=86400)
        if not g.get("results"):
            return {"error": f"I could not find a place called '{place}'"}
        loc = _pick_place(g["results"], tail)
        imp = units != "metric"
        f = getj("https://api.open-meteo.com/v1/forecast", {
            "latitude": loc["latitude"], "longitude": loc["longitude"], "timezone": "auto", "forecast_days": 3,
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m,precipitation",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "temperature_unit": "fahrenheit" if imp else "celsius", "wind_speed_unit": "mph" if imp else "kmh"}, ttl=600)
        c, d = f["current"], f["daily"]
        deg, spd = ("°F", "mph") if imp else ("°C", "km/h")
        return {"place": ", ".join(x for x in (loc["name"], loc.get("admin1"), loc.get("country")) if x),
                "now": {"temperature": f"{c['temperature_2m']}{deg}", "feels_like": f"{c['apparent_temperature']}{deg}",
                        "conditions": WMO.get(c["weather_code"], "unknown"), "humidity": f"{c['relative_humidity_2m']}%",
                        "wind": f"{c['wind_speed_10m']} {spd}", "rain_now": c.get("precipitation")},
                "next_days": [{"date": d["time"][i], "conditions": WMO.get(d["weather_code"][i], "unknown"),
                               "high": f"{d['temperature_2m_max'][i]}{deg}", "low": f"{d['temperature_2m_min'][i]}{deg}",
                               "chance_of_rain": f"{d['precipitation_probability_max'][i]}%"} for i in range(len(d["time"]))],
                "source": "Open-Meteo"}
    return weather


def register(agent):
    tcfg = (agent.cfg.get("tools") or {})
    agent.register("web_search", web_search,
                   "web_search(query: str, n: int=5) - search the internet; returns titles, links, snippets. Then read_page the best one for detail")
    agent.register("read_page", read_page,
                   "read_page(url: str, max_chars: int=6000) - read a web page or public JSON API as text (public sites only)")
    agent.register("wikipedia", wikipedia,
                   "wikipedia(topic: str, full: bool=False) - encyclopedia summary of a topic (full=True for a long extract)")
    agent.register("weather", make_weather(tcfg.get("units", "imperial"), agent.cfg.get("home_city", "")),
                   "weather(place: str) - live weather and 3-day forecast, e.g. 'Malibu, CA' (blank = home city)")
    agent.register("news", news, "news(topic: str='', n: int=6) - current headlines (blank topic = top stories)")
    agent.register("arxiv", arxiv, "arxiv(query: str, n: int=4) - recent scientific papers and abstracts")
    agent.register("define", define, "define(word: str) - dictionary definition and pronunciation")
    agent.register("exchange", exchange, "exchange(amount: float, from_currency: str, to_currency: str) - live currency conversion")
