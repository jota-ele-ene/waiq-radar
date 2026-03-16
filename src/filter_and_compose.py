"""
Filtrado de noticias WAIQ y composición del radar (email + artículo de opinión).

Optimizaciones de coste aplicadas:
  1. Snippets truncados a 150 chars en el prompt de filtrado (era 500)
  2. Modelo ligero (Haiku) para filter_news y choose_editorial_angle
  3. verify_urls limitado a verify_max artículos y 1000 chars de página (era 2000)
  4. max_tokens_opinion independiente para evitar truncado en compose
  5. waiq_context eliminado del system prompt de filtrado (redundante con criteria)
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


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _build_results_table(results: List[SearchResult]) -> str:
    lines = []
    lines.append("| FUENTE | Fecha de publicación | URL |")
    lines.append("| --- | --- | --- |")
    for r in results:
        fuente = getattr(r, "source", "") or "N/A"
        fecha = getattr(r, "date", "") or "N/A"
        url = r.url or "N/A"
        fuente = str(fuente).replace("|", r"\|")
        fecha = str(fecha).replace("|", r"\|")
        url = str(url).replace("|", r"\|")
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
        fuente = str(fuente).replace("|", r"\|")
        fecha = str(fecha).replace("|", r"\|")
        url = str(url).replace("|", r"\|")
        lines.append(f"| {fuente} | {fecha} | {url} |")
    return "\n".join(lines)


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


def _make_filter_llm(config: dict, tool_log: list) -> LLMClient:
    """
    Devuelve un LLMClient usando el modelo ligero definido en config.llm.model_filter.
    Si no está configurado, usa el modelo por defecto (sin coste extra).
    """
    model_override = config["llm"].get("model_filter")
    if model_override:
        logger.info(f"[coste] Usando modelo ligero para filtrado: {model_override}")
    return LLMClient(config, tool_log=tool_log, model_override=model_override)


def _fetch_published_urls(config: dict) -> set:
    """
    Recupera el listado de URLs ya publicadas en WAIQ desde config.filter.api_contents.

    La URL se usa directamente tal como está configurada. Si en el futuro
    hubiera un parámetro waiq_domain apuntando a waiq.technology, bastaría
    con componer la ruta /api/contents/index.json sobre él.

    El JSON puede tener cualquiera de estos formatos:
      - Lista de strings:           ["https://...", ...]
      - Lista de objetos:           [{"url": "https://..."}, ...]
      - Dict con lista como valor:  {"contents": [...], ...}
    """
    api_contents = config["filter"].get("api_contents", "")
    if not api_contents:
        logger.debug("[api_contents] No configurada, se omite el filtrado de publicadas.")
        return set()

    try:
        resp = httpx.get(api_contents, timeout=10, follow_redirects=True)
        resp.raise_for_status()
        data = resp.json()

        # Normalizar estructura del JSON
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            # Tomar la primera clave cuyo valor sea una lista
            items = next((v for v in data.values() if isinstance(v, list)), [])
        else:
            items = []

        urls = set()
        for item in items:
            if isinstance(item, str):
                urls.add(item.strip())
            elif isinstance(item, dict):
                # Aceptar "url", "link" o "canonical" como clave de la URL
                for key in ("url", "link", "canonical"):
                    if key in item:
                        urls.add(str(item[key]).strip())
                        break

        logger.info(
            f"[api_contents] {len(urls)} URLs ya publicadas recuperadas de {api_contents}"
        )
        return urls

    except Exception as e:
        logger.warning(f"[api_contents] No se pudo recuperar el listado publicado: {e}")
        return set()


# ─── Funciones principales ────────────────────────────────────────────────────

def filter_news(
    results: List[SearchResult],
    config: dict,
    llm: LLMClient,
) -> List[dict]:
    """
    Filtra y selecciona las noticias más relevantes usando el LLM.

    Optimizaciones aplicadas:
    - Snippets truncados a 150 chars (era 500) → ~60% menos tokens de entrada
    - Modelo ligero (model_filter) para esta fase → ~95% menos coste
    - waiq_context eliminado del system prompt (redundante con criteria)

    Adicionalmente, excluye antes del prompt las URLs que ya aparecen
    publicadas en https://waiq.technology/api/contents/index.json
    """

    # ── Excluir URLs ya publicadas en WAIQ ────────────────────────────────
    published_urls = _fetch_published_urls(config)
    if published_urls:
        before = len(results)
        results = [r for r in results if r.url not in published_urls]
        removed = before - len(results)
        if removed:
            logger.info(
                f"[api_contents] {removed} resultado(s) excluido(s) por ya estar publicados en WAIQ."
            )
    # ─────────────────────────────────────────────────────────────────────

    criteria_text = "\n".join(
        f"  {i+1}. {c}" for i, c in enumerate(config["filter"]["criteria"])
    )
    angles = ", ".join(config["editorial_angles"])

    # OPT 1: snippets a 150 chars — suficiente para clasificar, no para redactar
    results_text = ""
    for i, r in enumerate(results):
        results_text += (
            f"\n[{i+1}] {r.title}\n"
            f"    URL: {r.url}\n"
            f"    Snippet: {r.snippet[:150]}\n"
            f"    Date: {r.date}\n"
        )

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

    # OPT 5: system prompt sin waiq_context (los criterios ya lo cubren)
    system_prompt = FILTER_SYSTEM

    # OPT 2: modelo ligero para esta fase
    filter_llm = _make_filter_llm(config, llm.tool_log)

    data = filter_llm.complete_json(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        action_desc=f"Filtrar {len(results)} resultados → top {config['filter']['max_news']}",
    )

    news = data.get("news", [])

    filtered_table = _build_filtered_table(news)
    logger.info("TABLA DE NOTICIAS FILTRADAS:\n%s", filtered_table)

    return news


def verify_news_urls(
    news: List[dict],
    config: dict,
    llm: LLMClient,
    tool_log: list,
) -> List[dict]:
    """
    Verifica cada URL seleccionada leyendo el contenido real de la página.

    Optimizaciones aplicadas:
    - Limitado a verify_max artículos (config.verify_max, default=5)
    - Texto de página recortado a 1000 chars (era 2000) → ~50% menos tokens
    - Los artículos no verificados se añaden al final sin modificar
    """
    if not config.get("verify_urls", False):
        logger.info("Verificación de URLs desactivada, saltando.")
        return news

    # OPT 3a: límite de artículos a verificar
    verify_max = config.get("verify_max", 5)
    news_to_verify = news[:verify_max]
    news_skip = news[verify_max:]

    logger.info(
        f"Verificando {len(news_to_verify)}/{len(news)} URLs "
        f"(verify_max={verify_max})..."
    )
    verified = []

    for item in news_to_verify:
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
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()

            # OPT 3b: 1000 chars en lugar de 2000
            page_text = soup.get_text(separator="\n", strip=True)[:1000]

            tool_log.append({
                "step": len(tool_log) + 1,
                "tool": "fetch_url (verify)",
                "model": "N/A",
                "action": f"Verificar: {url[:80]}",
                "result": f"OK — {len(page_text)} chars extraídos",
            })

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

    # Artículos no verificados se pasan tal cual
    return verified + news_skip


def choose_editorial_angle(
    news: List[dict],
    config: dict,
    llm: LLMClient,
) -> List[str]:
    """
    Elige dinámicamente el/los ángulos editoriales según las noticias.

    Optimización: usa modelo ligero (model_filter) — es solo clasificación.
    """
    angles = ", ".join(config["editorial_angles"])
    news_summary = _build_news_summary(news)

    # OPT 2: modelo ligero también para esta fase
    filter_llm = _make_filter_llm(config, llm.tool_log)

    data = filter_llm.complete_json(
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
    """
    Genera el artículo de opinión en ES y EN en una sola llamada.

    Optimización: usa max_tokens_opinion para evitar truncado de JSON largo
    sin afectar al límite de tokens del resto de fases.
    """
    news_summary = _build_news_summary(news)
    angles_str = " / ".join(angles)

    # OPT 4: max_tokens independiente para esta fase
    original_max_tokens = config["llm"].get("max_tokens", 4096)
    config["llm"]["max_tokens"] = config["llm"].get("max_tokens_opinion", 6000)

    try:
        data = llm.complete_json(
            system_prompt=OPINION_SYSTEM.format(waiq_context=config["waiq_context"]),
            user_prompt=OPINION_USER.format(
                date=date_str,
                angles=angles_str,
                news_summary=news_summary,
            ),
            action_desc=f"Generar artículo de opinión ({angles_str})",
        )
    finally:
        # Restaurar siempre, incluso si hay excepción
        config["llm"]["max_tokens"] = original_max_tokens

    return data