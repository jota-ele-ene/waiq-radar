"""
Módulo de búsqueda web. Soporta Serper, Tavily y SearXNG.
"""

import httpx
import logging
from datetime import datetime, timedelta
from typing import List, Dict

logger = logging.getLogger("waiq-radar.search")


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
    provider = config["search"]["provider"]
    queries = config["search"]["queries_en"] + config["search"]["queries_es"]
    max_results = config["search"]["max_results_per_query"]
    all_results: List[SearchResult] = []
    seen_urls = set()

    for i, query in enumerate(queries):
        logger.info(f"[{i+1}/{len(queries)}] Buscando: {query}")
        try:
            if provider == "serper":
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
    """Búsqueda con instancia SearXNG local"""
    base_url = config["search"]["api_key"]  # En SearXNG, usamos la URL como "key"

    resp = httpx.get(
        f"{base_url}/search",
        params={
            "q": query,
            "format": "json",
            "categories": "general,news",
            "time_range": "week",
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
            date=item.get("publishedDate", ""),
        ))
    return results
