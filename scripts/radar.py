"""
WAIQ Radar — Pipeline principal

Modos (variable RADAR_MODE):
  full          — busca + genera + publica en GitHub + email  [default]
  fetch-only    — busca + genera + email + guarda JSON  (sin GitHub)
  publish-only  — lee JSON (RADAR_JSON_PATH) + publica + email
"""

import os, re, sys, json, time, smtplib, urllib.request
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import anthropic
from github import Github, GithubException

# ─────────────────────────────────────────────────────────────
# CONFIGURACIÓN
# ─────────────────────────────────────────────────────────────

ANTHROPIC_API_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")
GITHUB_TOKEN       = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO        = os.environ.get("GITHUB_REPO", "jota-ele-ene/waiq-multi")
HUGO_BASE_URL      = os.environ.get("HUGO_BASE_URL", "https://waiq.technology")
GMAIL_USER         = os.environ.get("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
EMAIL_RECIPIENTS   = os.environ.get("EMAIL_RECIPIENTS", "")

RADAR_MODE      = os.environ.get("RADAR_MODE", "full").lower()
RADAR_JSON_PATH = os.environ.get("RADAR_JSON_PATH", "")
OUTPUT_DIR      = os.environ.get("OUTPUT_DIR", ".")

MODEL_SEARCH = "claude-sonnet-4-6"
MODEL_WRITE  = "claude-haiku-4-5-20251001"

PRICING = {
    MODEL_SEARCH: {"input": 3.00,  "output": 15.00, "search": 10.00},
    MODEL_WRITE:  {"input": 1.00,  "output": 5.00,  "search":  0.00},
}

REPO_PATH_EN   = "content/en/article"
REPO_PATH_ES   = "content/es/article"
REPO_PATH_IMG  = "static/images/upload/articles"
OPINION_AUTHOR = "WAIQ Radar"

AREAS_VALIDAS = [
    "regulation", "ethical", "legal", "business", "innovation",
    "governance", "social", "technology", "sovereignty", "democracy",
    "use-cases", "research"
]

WAIQ_CONTEXT = (
    "WAIQ (Web3·AI·Quantum): foro Harvard Law 2023. Analiza tecnologías disruptivas "
    "desde perspectivas NO técnicas: gobernanza, regulación, ética, impacto social, "
    "modelos de negocio, soberanía digital, democracia, convergencia tecnológica. "
    "Audiencia: juristas, directivos, innovadores. "
    "EXCLUIR: noticias meramente técnicas (benchmarks, hardware, lanzamientos de modelos)."
)

# ─────────────────────────────────────────────────────────────
# CONTABILIDAD DE COSTES
# ─────────────────────────────────────────────────────────────

cost_log: list[dict] = []

def registrar_coste(llamada, model, usage, n_searches=0):
    p = PRICING.get(model, {"input": 3.00, "output": 15.00, "search": 10.00})
    input_tk  = getattr(usage, "input_tokens",  0)
    output_tk = getattr(usage, "output_tokens", 0)
    cost_in     = (input_tk   / 1_000_000) * p["input"]
    cost_out    = (output_tk  / 1_000_000) * p["output"]
    cost_search = (n_searches / 1_000)     * p["search"]
    cost_total  = cost_in + cost_out + cost_search
    entry = {
        "llamada": llamada, "model": model,
        "input_tokens": input_tk, "output_tokens": output_tk,
        "n_searches": n_searches,
        "cost_input": cost_in, "cost_output": cost_out,
        "cost_search": cost_search, "cost_total": cost_total,
    }
    cost_log.append(entry)
    srch_str = f" + {n_searches} búsq" if n_searches else ""
    print(f"   💰 {llamada}: {input_tk:,}in + {output_tk:,}out{srch_str} = ${cost_total:.4f}")
    return entry

def contar_searches(response):
    return sum(
        1 for b in response.content
        if getattr(b, "type", "") == "tool_use" and getattr(b, "name", "") == "web_search"
    )

def imprimir_resumen_costes():
    total     = sum(e["cost_total"]   for e in cost_log)
    total_in  = sum(e["input_tokens"] for e in cost_log)
    total_out = sum(e["output_tokens"]for e in cost_log)
    total_sr  = sum(e["n_searches"]   for e in cost_log)
    sep = "─" * 62
    print(f"\n{sep}")
    print("📊  INFORME DE COSTES")
    print(sep)
    print(f"  {'LLAMADA':<26} {'MODELO':<12} {'IN':>7} {'OUT':>6} {'SRCH':>5} {'USD':>8}")
    print(sep)
    for e in cost_log:
        m = e["model"].replace("claude-","").replace("-4-5-20251001","4.5").replace("-4-6","4.6")
        print(f"  {e['llamada']:<26} {m:<12} "
              f"{e['input_tokens']:>7,} {e['output_tokens']:>6,} "
              f"{e['n_searches']:>5} {e['cost_total']:>8.4f}")
    print(sep)
    print(f"  {'TOTAL':<26} {'':<12} {total_in:>7,} {total_out:>6,} {total_sr:>5} {total:>8.4f}")
    print(sep)
    print(f"\n  💵  Coste esta ejecución : ${total:.4f} USD")
    print(f"  📅  Coste anual (×104)   : ${total * 104:.2f} USD\n")
    return total

# ─────────────────────────────────────────────────────────────
# 1. BÚSQUEDA
# ─────────────────────────────────────────────────────────────

def buscar_noticias(client):
    print("📡 Buscando noticias WAIQ...")
    desde = (datetime.now(timezone.utc) - timedelta(days=4)).strftime("%Y-%m-%d")
    prompt = (
        f"Eres editor del radar WAIQ. Contexto: {WAIQ_CONTEXT}\n\n"
        f"Busca noticias desde {desde} sobre: regulación/gobernanza IA (EU AI Act, políticas "
        f"nacionales), aspectos legales/éticos/sociales de AI·Web3·Quantum, soberanía digital, "
        f"brecha tecnológica, convergencia WAIQ, modelos de negocio innovadores, democracia+tecnología.\n"
        f"Usa MÁXIMO 5 búsquedas. Prioriza: think tanks, medios especializados, organismos oficiales.\n\n"
        f"Por cada noticia devuelve:\n"
        f"title_en, title_es, description_en (2-3 frases), description_es (2-3 frases),\n"
        f"url, source, source_domain, topic (ai|web3|quantum), extra_topics ([]),\n"
        f"areas (de: {', '.join(AREAS_VALIDAS)}), image_url (o null), date (YYYY-MM-DD)\n\n"
        f"Devuelve SOLO JSON sin backticks:\n"
        f'{{\"noticias\":[{{...}},...]}}\n\nSelecciona 8-10 noticias de calidad.'
    )
    resp = client.messages.create(
        model=MODEL_SEARCH,
        max_tokens=3500,
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}],
        messages=[{"role": "user", "content": prompt}],
    )
    n_searches = contar_searches(resp)
    registrar_coste("buscar_noticias", MODEL_SEARCH, resp.usage, n_searches)
    text  = "".join(b.text for b in resp.content if hasattr(b, "text"))
    text  = re.sub(r"```json|```", "", text).strip()
    match = re.search(r'\{[\s\S]*\}', text)
    if not match:
        raise ValueError("JSON no encontrado en respuesta de búsqueda")
    noticias = json.loads(match.group()).get("noticias", [])
    print(f"   ✓ {len(noticias)} noticias · {n_searches} búsquedas")
    return noticias

# ─────────────────────────────────────────────────────────────
# 2. ARTÍCULO DE OPINIÓN
# ─────────────────────────────────────────────────────────────

def generar_articulo(client, noticias):
    print("✍️  Generando artículo...")
    refs = "\n".join(
        f"[{n.get('topic','').upper()}] {n['title_en']} ({n['source']}): "
        f"{n.get('description_en','')[:110]}"
        for n in noticias
    )
    prompt = (
        f"Eres articulista de WAIQ. Contexto: {WAIQ_CONTEXT}\n\n"
        f"Noticias del radar:\n{refs}\n\n"
        f"Escribe artículo de opinión (600-800 palabras/idioma). "
        f"Tono: analítico, crítico, perspectiva europea. Para juristas y directivos. "
        f"Usa subtítulos. Cita fuentes naturalmente.\n\n"
        f"Devuelve SOLO JSON sin backticks:\n"
        f'{{\"title_en\":\"...\",\"title_es\":\"...\",\"slug\":\"slug-kebab\",'
        f'\"description_en\":\"...(max 155 chars)\",\"description_es\":\"...(max 155 chars)\",'
        f'\"tags_en\":[],\"tags_es\":[],\"areas\":[],\"topics\":[],'
        f'\"body_en\":\"...markdown...\",\"body_es\":\"...markdown...\"}}'
    )
    resp = client.messages.create(
        model=MODEL_WRITE,
        max_tokens=3000,
        messages=[{"role": "user", "content": prompt}],
    )
    registrar_coste("generar_articulo", MODEL_WRITE, resp.usage)
    text  = re.sub(r"```json|```", "", resp.content[0].text).strip()
    match = re.search(r'\{[\s\S]*\}', text)
    if not match:
        raise ValueError("JSON no encontrado en artículo")
    art = json.loads(match.group())
    print(f"   ✓ «{art['title_en']}»")
    return art

# ─────────────────────────────────────────────────────────────
# 3. JSON INTERMEDIO
# ─────────────────────────────────────────────────────────────

def guardar_json(noticias, articulo, fecha):
    payload = {
        "fecha": fecha,
        "generado": datetime.now(timezone.utc).isoformat(),
        "costes": cost_log,
        "noticias": noticias,
        "articulo": articulo,
    }
    p = Path(OUTPUT_DIR) / f"radar_{fecha}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"   ✓ JSON: {p}")
    return str(p)

def cargar_json(path):
    print(f"📂 Cargando {path}...")
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    if "costes" in d:
        cost_log.extend(d["costes"])
    print(f"   ✓ {len(d['noticias'])} noticias · «{d['articulo']['title_en']}»")
    return d["noticias"], d["articulo"], d.get("fecha", datetime.now(timezone.utc).strftime("%Y-%m-%d"))

# ─────────────────────────────────────────────────────────────
# 4. IMÁGENES
# ─────────────────────────────────────────────────────────────

def descargar_imagen(url, slug):
    if not url:
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = r.read()
            ct   = r.headers.get("Content-Type", "image/jpeg")
            ext  = "png" if "png" in ct else "webp" if "webp" in ct else "jpg"
            return f"{slug}.{ext}", data
    except Exception as e:
        print(f"   ⚠ Imagen no descargable ({e})")
        return None

def svg_fallback(title, topic):
    c  = {"ai": "#6366f1", "web3": "#10b981", "quantum": "#f59e0b"}.get(topic, "#6366f1")
    w  = title.split()
    l1, l2 = " ".join(w[:6]), " ".join(w[6:12])
    l2t = (f'<text x="400" y="310" font-family="system-ui" font-size="26" '
           f'font-weight="600" fill="white" text-anchor="middle">{l2}</text>') if l2 else ""
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="800" height="450" viewBox="0 0 800 450">'
        f'<rect width="800" height="450" fill="{c}"/>'
        f'<rect x="0" y="380" width="800" height="70" fill="rgba(0,0,0,0.3)"/>'
        f'<text x="400" y="180" font-family="system-ui" font-size="72" font-weight="bold" '
        f'fill="white" text-anchor="middle" opacity="0.25">#{topic.upper()}</text>'
        f'<text x="400" y="270" font-family="system-ui" font-size="26" font-weight="600" '
        f'fill="white" text-anchor="middle">{l1}</text>{l2t}'
        f'<text x="400" y="420" font-family="system-ui" font-size="18" '
        f'fill="rgba(255,255,255,0.8)" text-anchor="middle">waiq.technology</text></svg>'
    )
    return "svg", svg.encode("utf-8")

def preparar_imagen(noticia, slug):
    r = descargar_imagen(noticia.get("image_url"), slug)
    if r:
        fname, data = r
    else:
        ext, data = svg_fallback(noticia["title_en"], noticia.get("topic", "ai"))
        fname = f"{slug}.{ext}"
    return fname, data, f"{REPO_PATH_IMG}/{fname}"

# ─────────────────────────────────────────────────────────────
# 5. MARKDOWN
# ─────────────────────────────────────────────────────────────

def slugify(t):
    for a, b in [("á","a"),("é","e"),("í","i"),("ó","o"),("ú","u"),("ñ","n"),
                 ("à","a"),("è","e"),("ì","i"),("ò","o"),("ù","u"),("ü","u")]:
        t = t.lower().replace(a, b)
    return re.sub(r"\s+", "-", re.sub(r"[^a-z0-9\s-]", "", t)).strip("-")[:70]

def yml_list(items):
    return "\n".join(f'  - "{i}"' for i in items)

def md_noticia(n, fecha, img_path, lang):
    title  = n["title_en"]       if lang == "en" else n["title_es"]
    desc   = n["description_en"] if lang == "en" else n["description_es"]
    btn    = f"Read in {n['source']}" if lang == "en" else f"Leer en {n['source']}"
    topic  = (n.get("topic") or "ai").lower()
    extras = [t.lower() for t in (n.get("extra_topics") or []) if t.lower() in ["ai","web3","quantum"]]
    topics = list(dict.fromkeys([topic] + extras))
    areas  = n.get("areas") or ["technology"]
    slug   = slugify(n["title_en"])
    base   = REPO_PATH_EN if lang == "en" else REPO_PATH_ES
    img    = f"/{img_path.replace('static/','')}" if img_path else ""
    return f"{base}/{fecha}-{slug}.md", (
        f'---\ntitle: "{title.replace(chr(34),chr(39))}"\n'
        f"date: {fecha}T00:00:00Z\ndraft: false\n"
        f'description: "{desc[:200].replace(chr(34),chr(39))}"\n'
        f"topics:\n{yml_list(topics)}\nareas:\n{yml_list(areas)}\n"
        f'categories:\n  - "Radar"\nsource: "{n.get("source","")}"\n'
        f'url_original: "{n.get("url","")}"\nbutton_label: "{btn}"\n'
        img_line = f'image: "{img}"' if img else '# image: ""'
        f"{img_line}\n---\n\n"
        f"{desc}\n\n**{btn}:** [{n.get('source','')}]({n.get('url','')})\n"
    )

def md_articulo(art, fecha, img_path, lang):
    title  = art["title_en"]       if lang == "en" else art["title_es"]
    desc   = art["description_en"] if lang == "en" else art["description_es"]
    body   = art["body_en"]        if lang == "en" else art["body_es"]
    topics = [t.lower() for t in (art.get("topics") or ["ai"]) if t.lower() in ["ai","web3","quantum"]]
    areas  = art.get("areas") or ["regulation"]
    base   = REPO_PATH_EN if lang == "en" else REPO_PATH_ES
    img    = f"/{img_path.replace('static/','')}" if img_path else ""
    return f"{base}/{fecha}-{art['slug']}.md", (
        f'---\ntitle: "{title.replace(chr(34),chr(39))}"\n'
        f"date: {fecha}T00:00:00Z\ndraft: false\n"
        f'description: "{desc[:200].replace(chr(34),chr(39))}"\n'
        f"topics:\n{yml_list(topics)}\nareas:\n{yml_list(areas)}\n"
        f'categories:\n  - "Radar"\n  - "Opinion"\nauthor: "{OPINION_AUTHOR}"\n'
        img_line = f'image: "{img}"' if img else '# image: ""'
        f"{img_line}\n---\n\n"
        f"{body}\n"
    )

# ─────────────────────────────────────────────────────────────
# 6. CONSTRUIR FICHEROS
# ─────────────────────────────────────────────────────────────

def construir_ficheros(noticias, articulo, fecha):
    txt, bin_ = [], []
    print("📄 Generando ficheros...")
    ext, art_data = svg_fallback(articulo["title_en"], "ai")
    art_img = f"{REPO_PATH_IMG}/{fecha}-opinion-{articulo['slug']}.{ext}"
    bin_.append((art_img, art_data))
    for lang in ["en", "es"]:
        p, c = md_articulo(articulo, fecha, art_img, lang)
        txt.append((p, c))
        print(f"   ✓ Artículo [{lang.upper()}]")
    for n in noticias:
        slug = slugify(n["title_en"])
        _, data, img_path = preparar_imagen(n, f"{fecha}-{slug}")
        bin_.append((img_path, data))
        for lang in ["en", "es"]:
            p, c = md_noticia(n, fecha, img_path, lang)
            txt.append((p, c))
        print(f"   ✓ {slug[:55]}")
    print(f"   Total: {len(txt)} .md + {len(bin_)} imágenes")
    return txt, bin_

# ─────────────────────────────────────────────────────────────
# 7. GITHUB
# ─────────────────────────────────────────────────────────────

def push_github(txt, bin_, fecha):
    print("🐙 Publicando en GitHub...")
    repo = Github(GITHUB_TOKEN).get_repo(GITHUB_REPO)
    msg  = f"Radar {fecha}"
    for path, content in txt + list(bin_):
        try:
            ex = repo.get_contents(path)
            repo.update_file(path, msg, content, ex.sha)
            print(f"   ↻ {path}")
        except GithubException:
            repo.create_file(path, msg, content)
            print(f"   + {path}")
        time.sleep(0.3)
    print(f"   ✓ Commit: «{msg}»")

# ─────────────────────────────────────────────────────────────
# 8. EMAIL
# ─────────────────────────────────────────────────────────────

def enviar_email(noticias, articulo, fecha, publicado, coste):
    if not (GMAIL_USER and GMAIL_APP_PASSWORD and EMAIL_RECIPIENTS):
        print("   ⚠ Email no configurado — omitido")
        return
    print("📧 Enviando email...")
    colors = {"ai": "#6366f1", "web3": "#10b981", "quantum": "#f59e0b"}
    rows = "".join(
        f'<div style="border-left:3px solid {colors.get(n.get("topic","ai"),"#6366f1")};'
        f'padding:12px 16px;margin:10px 0;background:#fafafa;border-radius:0 8px 8px 0;">'
        f'<div style="font-size:11px;color:{colors.get(n.get("topic","ai"),"#6366f1")};'
        f'font-weight:700;letter-spacing:1px;">#{n.get("topic","").upper()} · {n.get("source","")}</div>'
        f'<a href="{n["url"]}" style="font-size:15px;font-weight:700;color:#1a1a2e;text-decoration:none;">{n["title_en"]}</a>'
        f'<p style="font-size:13px;color:#555;margin:5px 0 7px;">{n["description_en"]}</p>'
        f'<a href="{n["url"]}" style="font-size:12px;color:{colors.get(n.get("topic","ai"),"#6366f1")};">Read →</a></div>'
        for n in noticias
    )
    art_url = f"{HUGO_BASE_URL}/article/{fecha}-{articulo['slug']}/"
    preview = re.sub(r"#{1,6}\s|[*_]", "", articulo["body_en"])[:280] + "..."
    badge   = ('<span style="background:#10b981;color:white;padding:2px 8px;border-radius:4px;font-size:11px;">✓ Published</span>'
               if publicado else
               '<span style="background:#f59e0b;color:white;padding:2px 8px;border-radius:4px;font-size:11px;">⏳ Preview</span>')
    art_btn = (f'<a href="{art_url}" style="display:inline-block;background:#6366f1;color:white;'
               f'padding:9px 20px;border-radius:6px;font-size:13px;font-weight:600;text-decoration:none;">'
               f'Read full article →</a>'
               if publicado else '<em style="font-size:13px;color:#888;">Pending GitHub upload</em>')
    html = (
        '<!DOCTYPE html><html><head><meta charset="UTF-8"></head>'
        '<body style="font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',sans-serif;'
        'max-width:660px;margin:0 auto;padding:20px;color:#1a1a2e;">'
        '<div style="background:linear-gradient(135deg,#1a1a2e,#6366f1);padding:28px;'
        'border-radius:12px;color:white;margin-bottom:24px;">'
        f'<div style="font-size:11px;letter-spacing:2px;opacity:0.7;">WAIQ RADAR · {fecha}</div>'
        f'<h1 style="margin:8px 0 4px;font-size:24px;">#WAIQ News Radar</h1>'
        f'<p style="margin:0 0 10px;opacity:0.8;font-size:14px;">{len(noticias)} references · Web3·AI·Quantum</p>'
        f'{badge} <span style="margin-left:8px;font-size:11px;opacity:0.6;">cost: ${coste:.4f}</span>'
        '</div>'
        '<h2 style="font-size:17px;border-bottom:2px solid #f0f0f0;padding-bottom:8px;">📰 Highlights</h2>'
        f'{rows}'
        '<div style="background:#f0f0ff;border-radius:12px;padding:22px;margin:24px 0;">'
        '<div style="font-size:11px;color:#6366f1;font-weight:700;letter-spacing:1px;margin-bottom:8px;">✍️ WAIQ OPINION</div>'
        f'<h3 style="margin:0 0 10px;font-size:17px;">{articulo["title_en"]}</h3>'
        f'<p style="font-size:13px;color:#555;margin:0 0 14px;line-height:1.6;">{preview}</p>'
        f'{art_btn}</div>'
        f'<p style="font-size:11px;color:#bbb;text-align:center;">WAIQ Radar · '
        f'<a href="{HUGO_BASE_URL}" style="color:#bbb;">waiq.technology</a></p>'
        '</body></html>'
    )
    status = "✓ Published" if publicado else "⏳ Preview"
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"#WAIQ Radar {fecha} [{status}] — {articulo['title_en'][:50]}"
    msg["From"] = GMAIL_USER
    msg["To"]   = EMAIL_RECIPIENTS
    msg.attach(MIMEText(html, "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        s.sendmail(GMAIL_USER, [r.strip() for r in EMAIL_RECIPIENTS.split(",")], msg.as_string())
    print("   ✓ Email enviado")

# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

def main():
    print(f"\n🚀 WAIQ Radar [{RADAR_MODE.upper()}]")
    print("=" * 55)
    fecha = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if RADAR_MODE == "fetch-only":
        if not ANTHROPIC_API_KEY: sys.exit("❌ ANTHROPIC_API_KEY requerida")
        client   = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        noticias = buscar_noticias(client)
        if not noticias: sys.exit("⚠️  Sin noticias")
        articulo = generar_articulo(client, noticias)
        coste    = imprimir_resumen_costes()
        guardar_json(noticias, articulo, fecha)
        enviar_email(noticias, articulo, fecha, publicado=False, coste=coste)
        print("✅ fetch-only completado")

    elif RADAR_MODE == "publish-only":
        if not GITHUB_TOKEN:    sys.exit("❌ GITHUB_TOKEN requerido")
        if not RADAR_JSON_PATH: sys.exit("❌ RADAR_JSON_PATH requerido")
        noticias, articulo, fecha = cargar_json(RADAR_JSON_PATH)
        txt, bin_ = construir_ficheros(noticias, articulo, fecha)
        push_github(txt, bin_, fecha)
        coste = imprimir_resumen_costes()
        enviar_email(noticias, articulo, fecha, publicado=True, coste=coste)
        print(f"✅ publish-only completado · commit «Radar {fecha}»")

    else:  # full
        if not ANTHROPIC_API_KEY: sys.exit("❌ ANTHROPIC_API_KEY requerida")
        if not GITHUB_TOKEN:      sys.exit("❌ GITHUB_TOKEN requerido")
        client   = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        noticias = buscar_noticias(client)
        if not noticias: sys.exit("⚠️  Sin noticias")
        articulo = generar_articulo(client, noticias)
        coste    = imprimir_resumen_costes()
        guardar_json(noticias, articulo, fecha)
        txt, bin_ = construir_ficheros(noticias, articulo, fecha)
        push_github(txt, bin_, fecha)
        enviar_email(noticias, articulo, fecha, publicado=True, coste=coste)
        print(f"✅ Pipeline completo · {len(noticias)} noticias · commit «Radar {fecha}»")


if __name__ == "__main__":
    main()