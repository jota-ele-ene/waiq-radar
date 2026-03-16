"""
Filtrado de noticias WAIQ y composición del radar (email + artículo de opinión).
"""

import json
import logging
import httpx
from typing import List, Dict, Optional
from datetime import datetime
from bs4 import BeautifulSoup

from .llm import LLMClient
from .search import SearchResult

logger = logging.getLogger("waiq-radar.filter")

# ─── Prompts ──────────────────────────────────────────────────────────────────

FILTER_SYSTEM = """You are a technology news curator for WAIQ Technology, 
a think-tank focused on Web3, AI, and Quantum convergence.

{waiq_context}

Your task is to analyze search results and select the most relevant news items.
"""

FILTER_USER = """Below are {count} search results from various sources.

Select the top {max_news} most relevant news items for the WAIQ radar.

A news item is relevant if it meets at least {min_criteria} of these criteria:
{criteria_text}

For EACH selected item, provide:
- title_es: Title in Spanish
- title_en: Title in English
- source: Source name (e.g., "El País", "CNBC")
- url: Original URL
- description_es: 2-3 sentence summary in Spanish explaining WAIQ relevance
- description_en: 2-3 sentence summary in English
- topics: Array of ["ai", "web3", "quantum"] (which apply)
- areas: Array from ["business", "legal", "regulation", "innovation", "technology", "ethical"]
- angles: Which WAIQ angles apply (from: {angles})
- button_label_es: "Leer en [Source]"
- button_label_en: "Read in [Source]"
- criteria_met: Which criteria numbers this item meets

Respond as JSON: {{"news": [...]}}

SEARCH RESULTS:
{results_text}
"""

VERIFY_SYSTEM = """You are a fact-checker. Given an article URL's actual content, 
verify and improve the summary that was written based only on search snippets.
Correct any inaccuracies. Keep the same format."""

VERIFY_USER = """Original summary (ES): {desc_es}

Actual page content:
{page_content}

Return corrected JSON: {{"description_es": "...", "description_en": "..."}}
Only fix factual errors. Keep the same length and style. If the original is accurate, return it unchanged."""

OPINION_SYSTEM = """You are a senior technology analyst writing for WAIQ Technology.

{waiq_context}

Write a thoughtful opinion article connecting today's news with the WAIQ vision.
The tone should be reflective, accessible to non-technical readers, and oriented
toward generating debate about the impact of these technologies.
Reference the WEF 3C framework (Combine, Converge, Compound) when relevant."""

OPINION_USER = """Today's date: {date}
Selected editorial angle(s): {angles}

Today's news items:
{news_summary}

Write the opinion article in BOTH Spanish and English.

Respond as JSON:
{{
  "title_es": "...",
  "title_en": "...",
  "description_es": "One-sentence summary in Spanish",
  "description_en": "One-sentence summary in English",
  "body_es": "Full 3-4 paragraph article in Spanish with sources as markdown links",
  "body_en": "Full 3-4 paragraph article in English with sources as markdown links",
  "topics": ["ai", "web3", "quantum"],
  "areas": ["technology", "regulation", ...]
}}"""

ANGLE_SYSTEM = """You are an editor choosing the best editorial angle for today's opinion piece."""

ANGLE_USER = """Available angles: {angles}

Today's top news:
{news_summary}

Choose 1-3 angles that best connect these stories into a coherent opinion piece.
Respond as JSON: {{"angles": ["angle1", "angle2"], "rationale": "Brief explanation"}}"""


# ─── Funciones ────────────────────────────────────────────────────────────────

def _build_results_table(results: List[SearchResult]) -> str:
    lines = []
    lines.append("| FUENTE | Fecha de publicación | URL |")
    lines.append("| --- | --- | --- |")
    for r in results:
        fuente = getattr(r, "source", "") or "N/A"
        fecha = getattr(r, "date", "") or "N/A"
        url = r.url or "N/A"
        fuente = str(fuente).replace("|", "\|")
        fecha = str(fecha).replace("|", "\|")
        url = str(url).replace("|", "\|")
        lines.append(f"| {fuente} | {fecha} | {url} |")
    return "\n".join(lines)


def _build_filtered_table(news: List[dict]) -> str:
    lines = []
    lines.append("| FUENTE | Fecha de publicación | URL |")
    lines.append("| --- | --- | --- |")
    for item in news:
        fuente = item.get("source", "N/A") or "N/A"
        fecha = item.get("date", "N/A") or "N/A"
        url = item.get("url", "N/A") or "N/A"
        fuente = str(fuente).replace("|", "\|")
        fecha = str(fecha).replace("|", "\|")
        url = str(url).replace("|", "\|")
        lines.append(f"| {fuente} | {fecha} | {url} |")
    return "\n".join(lines)

def filter_news(
    results: List[SearchResult],
    config: dict,
    llm: LLMClient,
) -> List[dict]:
    """Filtra y selecciona las noticias más relevantes usando el LLM."""

    criteria_text = "\n".join(
        f"  {i+1}. {c}" for i, c in enumerate(config["filter"]["criteria"])
    )
    angles = ", ".join(config["editorial_angles"])

    results_text = ""
    for i, r in enumerate(results):
        results_text += (
            f"\n[{i+1}] {r.title}\n"
            f"    URL: {r.url}\n"
            f"    Snippet: {r.snippet}\n"
            f"    Date: {r.date}\n"
        )

    # Tabla Markdown con las noticias de entrada (solo log)
    input_table = _build_results_table(results)
    logger.info("TABLA DE NOTICIAS DE ENTRADA:\n%s", input_table)

    user_prompt = FILTER_USER.format(
        count=len(results),
        max_news=config["filter"]["max_news"],
        min_criteria=config["filter"]["min_criteria"],
        criteria_text=criteria_text,
        angles=angles,
        results_text=results_text,
    )

    system_prompt = FILTER_SYSTEM.format(waiq_context=config["waiq_context"])

    data = llm.complete_json(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        action_desc=f"Filtrar {len(results)} resultados → top {config['filter']['max_news']}",
    )

    news = data.get("news", [])

    # Tabla Markdown con las noticias filtradas (solo log)
    filtered_table = _build_filtered_table(news)
    logger.info("TABLA DE NOTICIAS FILTRADAS:\n%s", filtered_table)

    return news


def verify_news_urls(
    news: List[dict],
    config: dict,
    llm: LLMClient,
    tool_log: list,
) -> List[dict]:
    """Verifica cada URL seleccionada leyendo el contenido real de la página."""
    if not config.get("verify_urls", False):
        logger.info("Verificación de URLs desactivada, saltando.")
        return news

    logger.info(f"Verificando {len(news)} URLs...")
    verified = []

    for item in news:
        url = item.get("url", "")
        try:
            resp = httpx.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (WAIQ Radar)"},
                follow_redirects=True,
                timeout=15,
            )
            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "html.parser")

            # Extraer texto principal (limitado a 2000 chars)
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            page_text = soup.get_text(separator="\n", strip=True)[:2000]

            tool_log.append({
                "step": len(tool_log) + 1,
                "tool": "fetch_url (verify)",
                "model": "N/A",
                "action": f"Verificar: {url[:80]}",
                "result": f"OK — {len(page_text)} chars extraídos",
            })

            # Pedir al LLM que verifique/corrija
            corrections = llm.complete_json(
                system_prompt=VERIFY_SYSTEM,
                user_prompt=VERIFY_USER.format(
                    desc_es=item.get("description_es", ""),
                    page_content=page_text,
                ),
                action_desc=f"Verificar resumen vs contenido real: {item.get('source', '')}",
            )

            if corrections.get("description_es"):
                item["description_es"] = corrections["description_es"]
            if corrections.get("description_en"):
                item["description_en"] = corrections["description_en"]

        except Exception as e:
            logger.warning(f"No se pudo verificar {url}: {e}")
            tool_log.append({
                "step": len(tool_log) + 1,
                "tool": "fetch_url (verify)",
                "model": "N/A",
                "action": f"Verificar: {url[:80]}",
                "result": f"ERROR — {str(e)}",
            })

        verified.append(item)

    return verified


def choose_editorial_angle(
    news: List[dict],
    config: dict,
    llm: LLMClient,
) -> List[str]:
    """Elige dinámicamente el/los ángulos editoriales según las noticias."""
    angles = ", ".join(config["editorial_angles"])
    news_summary = _build_news_summary(news)

    data = llm.complete_json(
        system_prompt=ANGLE_SYSTEM,
        user_prompt=ANGLE_USER.format(angles=angles, news_summary=news_summary),
        action_desc="Elegir ángulo(s) editorial(es)",
    )
    chosen = data.get("angles", ["Convergencia de tecnologías"])
    logger.info(f"Ángulos elegidos: {chosen}")
    return chosen


def compose_opinion_article(
    news: List[dict],
    angles: List[str],
    config: dict,
    llm: LLMClient,
    date_str: str,
) -> dict:
    """Genera el artículo de opinión en ES y EN."""
    news_summary = _build_news_summary(news)
    angles_str = " / ".join(angles)

    data = llm.complete_json(
        system_prompt=OPINION_SYSTEM.format(waiq_context=config["waiq_context"]),
        user_prompt=OPINION_USER.format(
            date=date_str,
            angles=angles_str,
            news_summary=news_summary,
        ),
        action_desc=f"Generar artículo de opinión ({angles_str})",
    )
    return data


def _build_news_summary(news: List[dict]) -> str:
    """Construye resumen textual de noticias para inyectar en prompts."""
    lines = []
    for i, item in enumerate(news):
        lines.append(
            f"{i+1}. {item.get('title_es', item.get('title_en', 'N/A'))}\n"
            f"   Fuente: {item.get('source', 'N/A')}\n"
            f"   URL: {item.get('url', 'N/A')}\n"
            f"   {item.get('description_es', item.get('description_en', 'N/A'))}\n"
            f"   Ángulos: {', '.join(item.get('angles', []))}\n"
        )
    return "\n".join(lines)
