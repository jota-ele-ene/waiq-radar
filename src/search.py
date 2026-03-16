"""
Módulo de búsqueda web. Soporta DuckDuckGo (sin API key), Serper, Tavily y SearXNG.
"""

import httpx
import logging
import time
from datetime import datetime, timedelta
from typing import List, Dict

logger = logging.getLogger("waiq-radar.search")

# DuckDuckGo rate-limit protection
DDG_DELAY_BETWEEN_QUERIES = 2.0  # seconds between queries to avoid blocks


class SearchResult:
    def __init__(self, title: str, url: str, snippet: str, date: str = ""):
        self.title = title
        self.url = url
        self.snippet = snippet
        self.date = date

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "date": self.date,
        }


def search_all(config: dict, tool_log: list) -> List[SearchResult]:
    """Ejecuta todas las queries configuradas y devuelve resultados agregados."""
    logger.info(f"[CONFIG] search config completo: {config.get('search')}")

    provider = config["search"]["provider"]
    queries = config["search"]["queries_en"] + config["search"]["queries_es"]
    max_results = config["search"]["max_results_per_query"]
    all_results: List[SearchResult] = []
    seen_urls = set()

    for i, query in enumerate(queries):
        logger.info(f"[{i+1}/{len(queries)}] Buscando: {query}")
        try:
            if provider == "duckduckgo":
                results = _search_duckduckgo(query, max_results, config)
            elif provider == "serper":
                results = _search_serper(query, max_results, config)
            elif provider == "tavily":
                results = _search_tavily(query, max_results, config)
            elif provider == "searxng":
                results = _search_searxng(query, max_results, config)
            else:
                raise ValueError(f"Proveedor de búsqueda no soportado: {provider}")

            tool_log.append({
                "step": len(tool_log) + 1,
                "tool": f"search_web ({provider})",
                "model": "N/A",
                "action": f"Query: {query}",
                "result": f"OK — {len(results)} resultados"
            })

            # Deduplicar por URL
            for r in results:
                if r.url not in seen_urls:
                    seen_urls.add(r.url)
                    all_results.append(r)

        except Exception as e:
            logger.error(f"Error buscando '{query}': {e}")
            tool_log.append({
                "step": len(tool_log) + 1,
                "tool": f"search_web ({provider})",
                "model": "N/A",
                "action": f"Query: {query}",
                "result": f"ERROR — {str(e)}"
            })

    logger.info(f"Total resultados únicos: {len(all_results)}")
    return all_results


def _search_duckduckgo(query: str, max_results: int, config: dict) -> List[SearchResult]:
    """Búsqueda con DuckDuckGo (sin API key). Usa text() + news() combinados."""
    from duckduckgo_search import DDGS

    recency = config["search"].get("recency_days", 2)
    # Map recency_days to DDG timelimit: d=day, w=week, m=month
    if recency <= 1:
        timelimit = "d"
    elif recency <= 7:
        timelimit = "w"
    else:
        timelimit = "m"

    results = []
    seen_urls = set()

    # --- News search (better for recent articles) ---
    try:
        ddgs = DDGS(timeout=20)
        news_results = ddgs.news(
            keywords=query,
            region="wt-wt",
            safesearch="off",
            timelimit=timelimit,
            max_results=max_results,
        )
        for item in news_results:
            url = item.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                results.append(SearchResult(
                    title=item.get("title", ""),
                    url=url,
                    snippet=item.get("body", "")[:500],
                    date=item.get("date", ""),
                ))
    except Exception as e:
        logger.warning(f"DDG news search failed for '{query}': {e}")

    # Small delay to avoid rate limiting
    time.sleep(DDG_DELAY_BETWEEN_QUERIES)

    # --- Text search (broader coverage) ---
    try:
        ddgs = DDGS(timeout=20)
        text_results = ddgs.text(
            keywords=query,
            region="wt-wt",
            safesearch="off",
            timelimit=timelimit,
            max_results=max_results,
        )
        for item in text_results:
            url = item.get("href", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                results.append(SearchResult(
                    title=item.get("title", ""),
                    url=url,
                    snippet=item.get("body", "")[:500],
                    date="",
                ))
    except Exception as e:
        logger.warning(f"DDG text search failed for '{query}': {e}")

    # Delay between queries to be respectful
    time.sleep(DDG_DELAY_BETWEEN_QUERIES)

    return results[:max_results * 2]  # Allow more since we combine two sources


def _search_serper(query: str, max_results: int, config: dict) -> List[SearchResult]:
    """Búsqueda con Serper.dev (Google Search API)"""
    api_key = config["search"]["api_key"]
    recency = config["search"].get("recency_days", 2)

    resp = httpx.post(
        "https://google.serper.dev/search",
        headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
        json={
            "q": query,
            "num": max_results,
            "tbs": f"qdr:d{recency}",  # Últimos N días
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    results = []
    for item in data.get("organic", [])[:max_results]:
        results.append(SearchResult(
            title=item.get("title", ""),
            url=item.get("link", ""),
            snippet=item.get("snippet", ""),
            date=item.get("date", ""),
        ))
    return results


def _search_tavily(query: str, max_results: int, config: dict) -> List[SearchResult]:
    """Búsqueda con Tavily AI Search"""
    api_key = config["search"]["api_key"]
    recency = config["search"].get("recency_days", 2)

    resp = httpx.post(
        "https://api.tavily.com/search",
        json={
            "api_key": api_key,
            "query": query,
            "max_results": max_results,
            "search_depth": "advanced",
            "include_answer": False,
            "days": recency,
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    results = []
    for item in data.get("results", [])[:max_results]:
        results.append(SearchResult(
            title=item.get("title", ""),
            url=item.get("url", ""),
            snippet=item.get("content", "")[:500],
            date=item.get("published_date", ""),
        ))
    return results


def _search_searxng(query: str, max_results: int, config: dict) -> List[SearchResult]:
    """
    Búsqueda con instancia SearXNG — paridad con Tavily search_depth: advanced.
    Hace DOS llamadas (general + news) y fusiona, igual que Tavily combina fuentes.
    """
    raw_base_url = config["search"].get("api_key", "")
    logger.info(f"[SearXNG] raw_base_url desde config.search.api_key = '{raw_base_url}'")

    base_url = raw_base_url.strip()
    if not base_url:
        raise ValueError("[SearXNG] base_url vacío. Revisa config.search.api_key")
    if not (base_url.startswith("http://") or base_url.startswith("https://")):
        raise ValueError(f"[SearXNG] base_url inválido: '{base_url}'. Debe empezar por http:// o https://")
    base_url = base_url.rstrip("/")

    # ── Mapeo recency_days → time_range (igual que DuckDuckGo y Tavily usan "days") ──
    recency = config["search"].get("recency_days", 7)
    if recency <= 1:
        time_range = "day"
    elif recency <= 7:
        time_range = "week"
    else:
        time_range = "month"

    # ── Motores explícitos: esto es lo que marca la diferencia vs Tavily ──
    # SearXNG sin engines explícitos delega en los defaults del servidor (a menudo solo DDG)
    general_engines = "google,bing,brave,duckduckgo"
    news_engines    = "google news,bing news,brave"

    seen_urls: set = set()
    results: List[SearchResult] = []

    def _fetch(categories: str, engines: str) -> List[SearchResult]:
        """Llamada individual a la API JSON de SearXNG."""
        try:
            resp = httpx.get(
                f"{base_url}/search",
                params={
                    "q":          query,
                    "format":     "json",
                    "categories": categories,
                    "engines":    engines,
                    "time_range": time_range,
                    "language":   "auto",
                    "pageno":     1,
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

            combined = data.get("results", [])

            # Rescatar infoboxes (respuestas autoritativas que SearXNG segrega)
            for box in data.get("infoboxes", []):
                for url_entry in box.get("urls", []):
                    combined.append({
                        "title":         box.get("infobox", ""),
                        "url":           url_entry.get("url", ""),
                        "content":       box.get("content", ""),
                        "publishedDate": "",
                    })

            return combined

        except Exception as e:
            logger.warning(f"[SearXNG] Llamada fallida (categories={categories}): {e}")
            return []    
    
   
    # ── Llamada 1: noticias recientes (equivale al topic:"news" de Tavily) ──
    news_raw = _fetch("news", news_engines)
    for item in news_raw:
        url = item.get("url", "").strip()
        snippet = (item.get("content", "") or item.get("snippet", "")).strip()
        if url and url not in seen_urls and len(snippet) >= 50:
            seen_urls.add(url)
            results.append(SearchResult(
                title=item.get("title", "").strip(),
                url=url,
                snippet=snippet[:500],
                date=item.get("publishedDate", "") or item.get("published", ""),
            ))

    # ── Llamada 2: búsqueda general (cubre lo que Tavily llama search_depth:"advanced") ──
    general_raw = _fetch("general", general_engines)
    for item in general_raw:
        url = item.get("url", "").strip()
        snippet = (item.get("content", "") or item.get("snippet", "")).strip()
        if url and url not in seen_urls and len(snippet) >= 50:
            seen_urls.add(url)
            results.append(SearchResult(
                title=item.get("title", "").strip(),
                url=url,
                snippet=snippet[:500],
                date=item.get("publishedDate", "") or item.get("published", ""),
            ))

    # ── Infoboxes: SearXNG a veces pone el mejor resultado aquí y el código original lo pierde ──
    for raw in [news_raw, general_raw]:
        # SearXNG devuelve infoboxes en data["infoboxes"], no en data["results"]
        # pero por si algún motor lo mete en results con type="infobox":
        pass  # ya cubierto arriba — ver nota sobre settings.yml más abajo

    logger.info(
        f"[SearXNG] '{query}' → {len(results)} únicos "
        f"(news: {len(news_raw)}, general: {len(general_raw)})"
    )
    return results[:max_results * 2]  # mismo criterio que DuckDuckGo en el código original
