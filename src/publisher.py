"""
Publicación en GitHub: genera archivos .md Hugo, descarga imágenes y hace commit+push.
"""

import os
import re
import logging
import subprocess
import httpx
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime
from bs4 import BeautifulSoup

logger = logging.getLogger("waiq-radar.publisher")


def publish_to_github(
    news: List[dict],
    opinion: dict,
    config: dict,
    date_str: str,
    date_iso: str,
    tool_log: list,
) -> dict:
    """
    Clona el repo, genera archivos, descarga imágenes y hace push.
    Retorna estadísticas {files_created, images_ok, images_total}.
    """
    gh_conf = config["github"]
    repo_url = f"https://x-access-token:{gh_conf['token']}@github.com/{gh_conf['repo']}.git"
    work_dir = Path("/tmp/waiq-radar-publish")

    stats = {"files_created": 0, "images_ok": 0, "images_total": 0}

    # 1. Clonar repo
    logger.info(f"Clonando {gh_conf['repo']}...")
    if work_dir.exists():
        subprocess.run(["rm", "-rf", str(work_dir)], check=True)

    result = subprocess.run(
        ["git", "clone", "--depth", "1", repo_url, str(work_dir)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        logger.error(f"Error clonando: {result.stderr}")
        tool_log.append({
            "step": len(tool_log) + 1,
            "tool": "git clone",
            "model": "N/A",
            "action": f"Clonar {gh_conf['repo']}",
            "result": f"ERROR — {result.stderr[:200]}",
        })
        return stats

    tool_log.append({
        "step": len(tool_log) + 1,
        "tool": "git clone",
        "model": "N/A",
        "action": f"Clonar {gh_conf['repo']}",
        "result": "OK",
    })

    # Configurar git
    subprocess.run(["git", "config", "user.email", "hi@jln.bz"], cwd=work_dir)
    subprocess.run(["git", "config", "user.name", "WAIQ Radar"], cwd=work_dir)

    es_dir = work_dir / gh_conf["paths"]["article_es"]
    en_dir = work_dir / gh_conf["paths"]["article_en"]
    img_dir = work_dir / gh_conf["paths"]["images"]
    es_dir.mkdir(parents=True, exist_ok=True)
    en_dir.mkdir(parents=True, exist_ok=True)
    img_dir.mkdir(parents=True, exist_ok=True)

    # 2. Generar archivos de noticias
    for item in news:
        slug = _slugify(item.get("title_en", item.get("title_es", "untitled")))
        filename = f"{date_iso}-{slug}.md"

        # Descargar imagen
        img_path = _download_og_image(item.get("url", ""), slug, date_iso, img_dir, tool_log)
        if img_path:
            stats["images_ok"] += 1
        stats["images_total"] += 1

        image_ref = f"/images/upload/{date_iso}-{slug}.jpg" if img_path else None

        # ES
        _write_article(
            path=es_dir / filename,
            title=item.get("title_es", ""),
            topics=item.get("topics", []),
            areas=item.get("areas", []),
            date=f"{date_iso}T08:00:00.000+01:00",
            description=item.get("description_es", ""),
            button_label=item.get("button_label_es", f"Leer en {item.get('source', '')}"),
            button_url=item.get("url", ""),
            image=image_ref or item.get("url", ""),
            body=item.get("description_es", ""),
        )
        stats["files_created"] += 1

        # EN
        _write_article(
            path=en_dir / filename,
            title=item.get("title_en", ""),
            topics=item.get("topics", []),
            areas=item.get("areas", []),
            date=f"{date_iso}T08:00:00.000+01:00",
            description=item.get("description_en", ""),
            button_label=item.get("button_label_en", f"Read in {item.get('source', '')}"),
            button_url=item.get("url", ""),
            image=image_ref or item.get("url", ""),
            body=item.get("description_en", ""),
        )
        stats["files_created"] += 1

    # 3. Generar artículo de opinión
    opinion_slug = _slugify(opinion.get("title_en", "opinion"))
    opinion_filename = f"{date_iso}-{opinion_slug}.md"

    # ES
    _write_article(
        path=es_dir / opinion_filename,
        title=opinion.get("title_es", ""),
        topics=opinion.get("topics", ["ai", "quantum", "web3"]),
        areas=opinion.get("areas", ["technology", "regulation"]),
        date=f"{date_iso}T08:00:00.000+01:00",
        description=opinion.get("description_es", ""),
        button_label="Leer artículo",
        button_url=None,
        image=None,
        body=opinion.get("body_es", ""),
    )
    stats["files_created"] += 1

    # EN
    _write_article(
        path=en_dir / opinion_filename,
        title=opinion.get("title_en", ""),
        topics=opinion.get("topics", ["ai", "quantum", "web3"]),
        areas=opinion.get("areas", ["technology", "regulation"]),
        date=f"{date_iso}T08:00:00.000+01:00",
        description=opinion.get("description_en", ""),
        button_label="Read article",
        button_url=None,
        image=None,
        body=opinion.get("body_en", ""),
    )
    stats["files_created"] += 1

    tool_log.append({
        "step": len(tool_log) + 1,
        "tool": "file_generation",
        "model": "N/A",
        "action": f"Generar {stats['files_created']} archivos .md",
        "result": f"OK — {stats['files_created']} archivos",
    })

    # 4. Commit y push
    subprocess.run(["git", "add", "-A"], cwd=work_dir, check=True)

    commit_msg = gh_conf["commit_message_template"].format(date=date_str)
    commit_result = subprocess.run(
        ["git", "commit", "-m", commit_msg],
        cwd=work_dir, capture_output=True, text=True,
    )

    if "nothing to commit" in commit_result.stdout:
        logger.warning("Nada que commitear (¿archivos duplicados?)")
        tool_log.append({
            "step": len(tool_log) + 1,
            "tool": "git commit+push",
            "model": "N/A",
            "action": commit_msg,
            "result": "SKIP — nothing to commit",
        })
        return stats

    push_result = subprocess.run(
        ["git", "push", "origin", gh_conf["branch"]],
        cwd=work_dir, capture_output=True, text=True,
    )

    if push_result.returncode == 0:
        logger.info(f"Push exitoso: {commit_msg}")
        tool_log.append({
            "step": len(tool_log) + 1,
            "tool": "git commit+push",
            "model": "N/A",
            "action": commit_msg,
            "result": f"OK — {stats['files_created']} archivos + {stats['images_ok']} imágenes",
        })
    else:
        logger.error(f"Error en push: {push_result.stderr}")
        tool_log.append({
            "step": len(tool_log) + 1,
            "tool": "git commit+push",
            "model": "N/A",
            "action": commit_msg,
            "result": f"ERROR — {push_result.stderr[:200]}",
        })

    return stats


def _write_article(
    path: Path,
    title: str,
    topics: list,
    areas: list,
    date: str,
    description: str,
    button_label: str,
    button_url: Optional[str],
    image: Optional[str],
    body: str,
):
    """Escribe un archivo .md con front matter YAML para Hugo."""
    lines = ["---"]
    lines.append(f'title: "{_escape_yaml(title)}"')
    lines.append("topics:")
    for t in topics:
        lines.append(f"  - {t}")
    lines.append("areas:")
    for a in areas:
        lines.append(f"  - {a}")
    lines.append(f"date: {date}")
    lines.append("description: >-")
    lines.append(f"  {description}")
    lines.append('draft: "false"')
    lines.append('featured: "true"')
    lines.append(f"button_label: {button_label}")
    if button_url:
        lines.append(f"button_url: {button_url}")
    if image:
        lines.append(f"image: {image}")
    lines.append("---")
    lines.append(body)
    lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
    logger.debug(f"Escrito: {path.name}")


def _download_og_image(
    page_url: str,
    slug: str,
    date_iso: str,
    img_dir: Path,
    tool_log: list,
) -> Optional[Path]:
    """Intenta descargar la imagen og:image de una URL."""
    try:
        resp = httpx.get(
            page_url,
            headers={"User-Agent": "Mozilla/5.0 (WAIQ Radar)"},
            follow_redirects=True,
            timeout=15,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        og_tag = soup.find("meta", property="og:image")
        if not og_tag or not og_tag.get("content"):
            tool_log.append({
                "step": len(tool_log) + 1,
                "tool": "fetch_og_image",
                "model": "N/A",
                "action": f"og:image de {page_url[:60]}",
                "result": "SKIP — no og:image encontrado",
            })
            return None

        img_url = og_tag["content"]

        # Determinar extensión
        ext = "jpg"
        if ".png" in img_url.lower():
            ext = "png"
        elif ".webp" in img_url.lower():
            ext = "webp"

        filename = f"{date_iso}-{slug}.{ext}"
        filepath = img_dir / filename

        img_resp = httpx.get(
            img_url,
            headers={"User-Agent": "Mozilla/5.0 (WAIQ Radar)"},
            follow_redirects=True,
            timeout=15,
        )
        img_resp.raise_for_status()

        if len(img_resp.content) < 1000:
            tool_log.append({
                "step": len(tool_log) + 1,
                "tool": "fetch_og_image",
                "model": "N/A",
                "action": f"Descargar {img_url[:60]}",
                "result": f"SKIP — archivo demasiado pequeño ({len(img_resp.content)}b)",
            })
            return None

        filepath.write_bytes(img_resp.content)

        tool_log.append({
            "step": len(tool_log) + 1,
            "tool": "fetch_og_image",
            "model": "N/A",
            "action": f"Descargar {img_url[:60]}",
            "result": f"OK — {len(img_resp.content)} bytes → {filename}",
        })
        return filepath

    except Exception as e:
        tool_log.append({
            "step": len(tool_log) + 1,
            "tool": "fetch_og_image",
            "model": "N/A",
            "action": f"og:image de {page_url[:60]}",
            "result": f"ERROR — {str(e)[:100]}",
        })
        return None


def _slugify(text: str) -> str:
    """Convierte texto en slug URL-friendly."""
    text = text.lower().strip()
    text = re.sub(r'[áàä]', 'a', text)
    text = re.sub(r'[éèë]', 'e', text)
    text = re.sub(r'[íìï]', 'i', text)
    text = re.sub(r'[óòö]', 'o', text)
    text = re.sub(r'[úùü]', 'u', text)
    text = re.sub(r'[ñ]', 'n', text)
    text = re.sub(r'[^a-z0-9\s-]', '', text)
    text = re.sub(r'[\s]+', '-', text)
    text = re.sub(r'-+', '-', text)
    return text[:80].strip('-')


def _escape_yaml(text: str) -> str:
    """Escapa comillas en strings YAML."""
    return text.replace('"', '\\"')
