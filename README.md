# WAIQ Technology Radar

Radar automatizado de noticias sobre Web3, IA y Quantum orientado a gobernanza, regulación, ética, impacto social, competitividad y convergencia tecnológica.

Genera diariamente:
- **Email** con 5-8 noticias relevantes + propuesta de artículo de opinión
- **Publicación en Hugo/GitHub** con archivos .md bilingües (ES/EN) + imágenes
- **Email de diagnóstico** con log detallado de todas las llamadas API

---

## Estructura del proyecto

```
waiq-radar/
├── config.yaml                  # Configuración editable (queries, filtros, LLM, etc.)
├── .env.example                 # Variables de entorno (API keys)
├── .gitignore
├── requirements.txt             # Dependencias Python
├── run.py                       # Script principal (pipeline por fases)
├── README.md                    # Esta guía
│
├── src/
│   ├── __init__.py
│   ├── config_loader.py         # Carga config.yaml + .env
│   ├── search.py                # Búsqueda web (DuckDuckGo/Serper/Tavily/SearXNG)
│   ├── llm.py                   # Abstracción LLM (OpenAI/Anthropic/Google)
│   ├── filter_and_compose.py    # Filtrado WAIQ + redacción + artículo opinión
│   ├── email_sender.py          # Envío de emails por SMTP
│   └── publisher.py             # Publicación en GitHub (Hugo .md + imágenes)
│
├── data/                        # (generado) Datos intermedios por fecha
│   └── 2026-03-13/
│       ├── 1_search_results.json   # Resultados brutos de búsqueda
│       ├── 2_filtered_news.json    # Noticias filtradas por el LLM
│       ├── 3_verified_news.json    # Noticias verificadas contra URLs
│       ├── 4_composed.json         # Ángulo + opinión + noticias finales
│       ├── email_preview.txt       # (dry-run) Preview del email
│       └── tool_log.json           # Log acumulado de herramientas
│
├── .github/
│   └── workflows/
│       └── radar.yml            # GitHub Action (ejecución diaria automática)
│
└── logs/                        # (generado) Logs de cada ejecución
    ├── radar_2026-03-13.log
    └── tool_log_2026-03-13.json
```

---

## Guía paso a paso

### Requisitos previos

- Python 3.10+
- Una API key de LLM (OpenAI, Anthropic o Google)
- (Opcional) Una API key de búsqueda web — DuckDuckGo funciona sin key, o Serper/Tavily
- Una cuenta de email con SMTP (Gmail con App Password es lo más sencillo)
- Un token de GitHub con permisos `repo` (para publicar en waiq-multi)

---

## OPCIÓN A: Ejecución local

### Paso 1: Clonar e instalar

```bash
git clone https://github.com/TU_USUARIO/waiq-radar.git
cd waiq-radar
python -m venv .venv
source .venv/bin/activate        # En Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Paso 2: Obtener API keys

#### LLM (elige uno):

| Proveedor | Cómo obtenerla | Precio orientativo |
|-----------|---------------|-------------------|
| **OpenAI** | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) | ~$0.01-0.03 por ejecución con gpt-4o |
| **Anthropic** | [console.anthropic.com](https://console.anthropic.com) | ~$0.01-0.04 por ejecución con Claude Sonnet |
| **Google** | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) | Gratis hasta cierto límite con Gemini Flash |

#### Búsqueda web (elige uno):

| Proveedor | Cómo obtenerla | Precio orientativo |
|-----------|---------------|-------------------|
| **DuckDuckGo** | No necesita API key (por defecto) | Gratis, sin límite oficial |
| **Serper** | [serper.dev](https://serper.dev) — regístrate y obtén API key | 2.500 búsquedas gratis, luego ~$0.001/búsqueda |
| **Tavily** | [tavily.com](https://tavily.com) — regístrate y obtén API key | 1.000 búsquedas gratis/mes |
| **SearXNG** | Instancia propia ([docs](https://docs.searxng.org)) | Gratis (self-hosted) |

#### Email (Gmail con App Password):

1. Ve a [myaccount.google.com](https://myaccount.google.com)
2. Seguridad → Verificación en 2 pasos (actívala si no está)
3. Seguridad → Contraseñas de aplicación
4. Crea una para "Correo" → te dará algo como `abcd efgh ijkl mnop`
5. Esa es tu `SMTP_PASSWORD` (sin espacios: `abcdefghijklmnop`)

#### Token de GitHub:

1. Ve a [github.com/settings/tokens](https://github.com/settings/tokens)
2. "Generate new token (classic)"
3. Scopes: marca `repo` (acceso completo a repositorios)
4. Copia el token `ghp_...`

### Paso 3: Configurar variables de entorno

```bash
cp .env.example .env
```

Edita `.env` con tus keys:

```env
OPENAI_API_KEY=sk-proj-...
# SERPER_API_KEY=...          # Solo si cambias search.provider a "serper"
SMTP_USERNAME=tu@gmail.com
SMTP_PASSWORD=abcdefghijklmnop
GITHUB_TOKEN=ghp_...
```

### Paso 4: Revisar config.yaml

Abre `config.yaml` y verifica:

- `llm.provider` y `llm.model` coinciden con tu API key
- `search.provider` — por defecto `duckduckgo` (sin API key). Cámbialo si prefieres Serper/Tavily
- `email.to` es la dirección donde quieres recibir el radar
- `github.repo` apunta a tu repositorio Hugo

### Paso 5: Probar fase a fase

Lo recomendado es ejecutar fase por fase la primera vez:

```bash
# 1. Solo búsqueda (no consume LLM)
python run.py --phase search
# Revisa data/{fecha}/1_search_results.json

# 2. Filtrado con LLM (lee los resultados de búsqueda)
python run.py --phase filter
# Revisa data/{fecha}/2_filtered_news.json

# 3. Verificación de URLs (si verify_urls: true)
python run.py --phase verify
# Revisa data/{fecha}/3_verified_news.json

# 4. Componer ángulo + artículo (LLM)
python run.py --phase compose
# Revisa data/{fecha}/4_composed.json

# 5. Preview del email (dry-run)
python run.py --phase email --dry-run
# Revisa data/{fecha}/email_preview.txt

# 6. Publicar en GitHub
python run.py --phase publish

# 7. Enviar diagnóstico
python run.py --phase diagnostic
```

Combinar fases:

```bash
python run.py --phase search,filter         # Búsqueda + filtrado
python run.py --phase compose-diagnostic    # Desde compose hasta el final
python run.py                                # Pipeline completo
python run.py --dry-run                      # Completo sin enviar/publicar
```

### Paso 6: Datos intermedios

Cada fase guarda su resultado en `data/{fecha}/` como JSON:

| Archivo | Genera | Consume |
|---------|--------|--------|
| `1_search_results.json` | search | filter |
| `2_filtered_news.json` | filter | verify, compose |
| `3_verified_news.json` | verify | compose |
| `4_composed.json` | compose | email, publish, diagnostic |
| `email_preview.txt` | email (dry-run) | — |
| `tool_log.json` | todas | diagnostic |

Puedes **editar manualmente** cualquier JSON antes de ejecutar la siguiente fase. Por ejemplo, eliminar una noticia de `2_filtered_news.json` antes de ejecutar `--phase compose`.

### Paso 7: Ejecución completa

```bash
python run.py
```

Recibirás dos emails y se publicará en GitHub.

### Paso 7: Programar ejecución diaria (local)

#### En Linux/Mac (crontab):

```bash
crontab -e
```

Añade esta línea (ajusta la ruta):

```
0 7 * * * cd /ruta/a/waiq-radar && /ruta/a/.venv/bin/python run.py >> /ruta/a/logs/cron.log 2>&1
```

#### En Windows (Task Scheduler):

1. Abre "Programador de tareas"
2. Crear tarea básica → nombre: "WAIQ Radar"
3. Desencadenador: Diariamente a las 08:00
4. Acción: Iniciar programa
   - Programa: `C:\ruta\.venv\Scripts\python.exe`
   - Argumentos: `run.py`
   - Directorio: `C:\ruta\waiq-radar`

---

## OPCIÓN B: GitHub Action (recomendada)

### Paso 1: Crear repositorio para el radar

```bash
# Crea un repo privado nuevo en GitHub (ej: waiq-radar)
gh repo create waiq-radar --private --clone
cd waiq-radar

# Copia todos los archivos del proyecto aquí
cp -r /ruta/al/paquete/* .
git add -A
git commit -m "Initial radar setup"
git push origin main
```

O directamente desde la UI de GitHub: crea un repo privado y sube los archivos.

### Paso 2: Configurar secrets

Ve a tu repositorio → Settings → Secrets and variables → Actions → New repository secret.

Crea estos secrets (los mismos valores que en `.env`):

| Secret name | Valor |
|------------|-------|
| `OPENAI_API_KEY` | Tu API key de OpenAI (o `ANTHROPIC_API_KEY` / `GOOGLE_API_KEY`) |
| `SERPER_API_KEY` | (Opcional) Solo si usas Serper en vez de DuckDuckGo |
| `SMTP_USERNAME` | Tu email (ej: `tu@gmail.com`) |
| `SMTP_PASSWORD` | App Password de Gmail |
| `WAIQ_GITHUB_TOKEN` | Token de GitHub con scope `repo` |

**Nota**: El secret se llama `WAIQ_GITHUB_TOKEN` (no `GITHUB_TOKEN`) porque `GITHUB_TOKEN` es un nombre reservado por GitHub Actions.

### Paso 3: Ajustar workflow si usas otro proveedor

Si usas Anthropic o Google en vez de OpenAI, edita `.github/workflows/radar.yml`:

```yaml
env:
  # Comenta la línea de OpenAI y descomenta la que corresponda:
  # OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
  ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

Y asegúrate de que `config.yaml` tenga el provider correcto:

```yaml
llm:
  provider: "anthropic"
  model: "claude-sonnet-4-20250514"
```

### Paso 4: Probar manualmente

1. Ve a tu repositorio → Actions → "WAIQ Technology Radar"
2. Click en "Run workflow"
3. Opcionalmente marca "dry_run: true" para la primera prueba
4. Click en "Run workflow"

Verás la ejecución en tiempo real. Al terminar, descarga los logs desde "Artifacts".

### Paso 5: Verificar ejecución automática

El workflow se ejecutará automáticamente cada día a las 8:00 AM CET. Puedes verificar en la pestaña Actions que se ejecuta correctamente.

---

## Flujo de ejecución detallado

```
┌───────────────────────────────────────────────────────────────┐
│  run.py --phase search                                    │
│  └─ search.py → Tavily/Serper/DuckDuckGo/SearXNG        │
│     └─ ~24 queries (18 EN + 6 ES)                       │
│     └─ → data/{fecha}/1_search_results.json             │
├───────────────────────────────────────────────────────────────┤
│  run.py --phase filter                                    │
│  └─ filter_and_compose.py → LLM                          │
│     └─ Lee: 1_search_results.json                       │
│     └─ → data/{fecha}/2_filtered_news.json              │
├───────────────────────────────────────────────────────────────┤
│  run.py --phase verify  (opcional)                        │
│  └─ fetch URLs + LLM verificación                        │
│     └─ Lee: 2_filtered_news.json                        │
│     └─ → data/{fecha}/3_verified_news.json              │
├───────────────────────────────────────────────────────────────┤
│  run.py --phase compose                                   │
│  └─ LLM: ángulo editorial + artículo opinión ES/EN      │
│     └─ Lee: 3_verified o 2_filtered                      │
│     └─ → data/{fecha}/4_composed.json                   │
├───────────────────────────────────────────────────────────────┤
│  run.py --phase email                                     │
│  └─ Lee: 4_composed.json → SMTP                          │
├───────────────────────────────────────────────────────────────┤
│  run.py --phase publish                                   │
│  └─ Lee: 4_composed.json → git clone + .md + push         │
├───────────────────────────────────────────────────────────────┤
│  run.py --phase diagnostic                                │
│  └─ Lee: tool_log.json → SMTP                             │
└───────────────────────────────────────────────────────────────┘

Cada fase es independiente. Los datos intermedios en data/{fecha}/
permiten reejecutar cualquier fase sin repetir las anteriores.
```

## Llamadas API por ejecución (estimación)

| Componente | Llamadas | Coste estimado |
|-----------|----------|---------------|
| Búsqueda web (DuckDuckGo) | ~24 | gratis |
| LLM - Filtrado | 1 | ~$0.005-0.02 |
| LLM - Verificación URLs | 5-8 | ~$0.01-0.05 |
| LLM - Ángulo editorial | 1 | ~$0.002 |
| LLM - Artículo opinión | 1 | ~$0.01-0.03 |
| Fetch URLs (verificación) | 5-8 | gratis |
| Fetch og:image | 5-8 | gratis |
| SMTP (email) | 2 | gratis |
| Git clone + push | 1 | gratis |
| **TOTAL** | **~50** | **~$0.05-0.15/día** |

## Personalización

### Cambiar queries de búsqueda

Edita `config.yaml` → `search.queries_en` y `search.queries_es`.

### Cambiar criterios de filtrado

Edita `config.yaml` → `filter.criteria`. Puedes añadir, quitar o modificar criterios.

### Cambiar ángulos editoriales

Edita `config.yaml` → `editorial_angles`.

### Desactivar la verificación de URLs

Si quieres ejecuciones más rápidas (y baratas), pon `verify_urls: false` en `config.yaml`. El resumen se basará solo en los snippets de búsqueda.

### Cambiar proveedor de LLM

Cambia `llm.provider` y `llm.model` en `config.yaml`. Asegúrate de tener la API key correspondiente en `.env`.

### Cambiar repositorio de publicación

Edita `config.yaml` → `github.repo` y las rutas en `github.paths`.

---

## Troubleshooting

| Problema | Solución |
|----------|---------|
| `401 Unauthorized` en búsqueda | Si usas Serper/Tavily, verifica la API key en `.env`. O cambia a `duckduckgo` (sin key) |
| DDG devuelve pocos resultados | DuckDuckGo puede ser más restrictivo. Sube `max_results_per_query` o cambia a Serper |
| `401` en LLM | Verifica la API key del proveedor en `.env` |
| Email no llega | Verifica App Password de Gmail. Revisa la carpeta de spam |
| Push a GitHub falla | Verifica `GITHUB_TOKEN` con scope `repo`. Comprueba que el repo existe |
| `json.JSONDecodeError` | El LLM devolvió formato incorrecto. Reintenta o sube `temperature` |
| Imágenes no se descargan | Normal (muchos sitios bloquean). Se usa URL externa como fallback |
| GitHub Action no se ejecuta | Verifica que los secrets estén configurados en Settings → Secrets |
