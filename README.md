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
├── run.py                       # Script principal (punto de entrada)
├── README.md                    # Esta guía
│
├── src/
│   ├── __init__.py
│   ├── config_loader.py         # Carga config.yaml + .env
│   ├── search.py                # Búsqueda web (Serper/Tavily/SearXNG)
│   ├── llm.py                   # Abstracción LLM (OpenAI/Anthropic/Google)
│   ├── filter_and_compose.py    # Filtrado WAIQ + redacción + artículo opinión
│   ├── email_sender.py          # Envío de emails por SMTP
│   └── publisher.py             # Publicación en GitHub (Hugo .md + imágenes)
│
├── .github/
│   └── workflows/
│       └── radar.yml            # GitHub Action (ejecución diaria automática)
│
└── logs/                        # (generado) Logs de cada ejecución
    ├── radar_2026-03-13.log
    ├── raw_results_2026-03-13.json
    ├── findings_2026-03-13.json
    └── tool_log_2026-03-13.json
```

---

## Guía paso a paso

### Requisitos previos

- Python 3.10+
- Una API key de LLM (OpenAI, Anthropic o Google)
- Una API key de búsqueda web (Serper o Tavily)
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
SERPER_API_KEY=...
SMTP_USERNAME=tu@gmail.com
SMTP_PASSWORD=abcdefghijklmnop
GITHUB_TOKEN=ghp_...
```

### Paso 4: Revisar config.yaml

Abre `config.yaml` y verifica:

- `llm.provider` y `llm.model` coinciden con tu API key
- `search.provider` coincide con tu API key de búsqueda
- `email.to` es la dirección donde quieres recibir el radar
- `github.repo` apunta a tu repositorio Hugo

### Paso 5: Probar en modo dry-run

```bash
python run.py --dry-run
```

Esto ejecutará búsquedas y generará contenido, pero **no enviará email ni pusheará a GitHub**. Revisa la salida en consola y los archivos en `logs/`:

- `logs/radar_YYYY-MM-DD.log` — log completo de la ejecución
- `logs/raw_results_YYYY-MM-DD.json` — todos los resultados de búsqueda brutos
- `logs/findings_YYYY-MM-DD.json` — noticias seleccionadas y ángulo editorial
- `logs/tool_log_YYYY-MM-DD.json` — log de herramientas (lo que irá en el email de diagnóstico)

### Paso 6: Ejecución real

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
| `SERPER_API_KEY` | Tu API key de Serper (o `TAVILY_API_KEY`) |
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
┌──────────────────────────────────────────────────────────┐
│  run.py                                                  │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  1. BÚSQUEDA WEB                                         │
│     └─ search.py → Serper/Tavily/SearXNG                │
│        └─ ~24 queries (18 EN + 6 ES)                    │
│        └─ ~100-200 resultados brutos                    │
│                                                          │
│  2. FILTRADO CON LLM                                     │
│     └─ filter_and_compose.py → OpenAI/Anthropic/Gemini  │
│        └─ 1 llamada LLM: filtrar → top 5-8 noticias    │
│                                                          │
│  2b. VERIFICACIÓN DE URLs (opcional)                     │
│      └─ fetch cada URL → extraer contenido real         │
│      └─ 1 llamada LLM por URL: verificar resumen       │
│                                                          │
│  3. ÁNGULO EDITORIAL                                     │
│     └─ 1 llamada LLM: elegir ángulo(s) según noticias  │
│                                                          │
│  4. ARTÍCULO DE OPINIÓN                                  │
│     └─ 1 llamada LLM: generar artículo ES/EN           │
│                                                          │
│  5. EMAIL PRINCIPAL                                      │
│     └─ email_sender.py → SMTP                           │
│                                                          │
│  6. PUBLICACIÓN GITHUB                                   │
│     └─ publisher.py → git clone + generate + push       │
│        └─ 18 archivos .md (9 artículos × 2 idiomas)    │
│        └─ N imágenes og:image descargadas               │
│        └─ 1 commit + push                               │
│                                                          │
│  7. EMAIL DIAGNÓSTICO                                    │
│     └─ email_sender.py → SMTP                           │
│        └─ Log completo de todas las llamadas            │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

## Llamadas API por ejecución (estimación)

| Componente | Llamadas | Coste estimado |
|-----------|----------|---------------|
| Búsqueda web (Serper) | ~24 | ~$0.024 |
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
| `401 Unauthorized` en búsqueda | Verifica `SERPER_API_KEY` o `TAVILY_API_KEY` en `.env` |
| `401` en LLM | Verifica la API key del proveedor en `.env` |
| Email no llega | Verifica App Password de Gmail. Revisa la carpeta de spam |
| Push a GitHub falla | Verifica `GITHUB_TOKEN` con scope `repo`. Comprueba que el repo existe |
| `json.JSONDecodeError` | El LLM devolvió formato incorrecto. Reintenta o sube `temperature` |
| Imágenes no se descargan | Normal (muchos sitios bloquean). Se usa URL externa como fallback |
| GitHub Action no se ejecuta | Verifica que los secrets estén configurados en Settings → Secrets |
