# Servidor FastAPI principal — Biwenger Agent
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime

import aiosqlite
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from pydantic import BaseModel
from database import DB_PATH, init_db, get_sync_logs, get_auth, clear_auth
from scraper import run_all_scrapers, do_login
from analyzer import run_analysis
from ai_advisor import generar_todos_los_consejos, obtener_ultimos_consejos, generar_respuesta_chat


class LoginRequest(BaseModel):
    email: str
    password: str


class ChatRequest(BaseModel):
    mensaje: str

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s"
)
logger = logging.getLogger(__name__)

# Estado global de sincronización (simplificado con asyncio.Lock)
sync_state = {
    "running": False,
    "progress": [],
    "last_sync": None,
    "error": None,
}
sync_lock = asyncio.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicializa la base de datos al arrancar."""
    await init_db()
    logger.info("Base de datos lista")
    yield


app = FastAPI(title="Biwenger Agent API", version="1.0.0", lifespan=lifespan)

# CORS: local + frontend desplegado en Render. Origen extra opcional vía
# CORS_ORIGIN (p. ej. para un dominio custom).
_allowed_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "https://biwenger-frontend.onrender.com",
]
_extra_origin = os.environ.get("CORS_ORIGIN")
if _extra_origin:
    _allowed_origins.append(_extra_origin)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ──────────────────────────────────────────────
# Helper para formatear euros
# ──────────────────────────────────────────────
def _rows_to_list(rows) -> list:
    return [dict(r) for r in rows]


# ──────────────────────────────────────────────
# GET /health — liveness probe + keep-alive
# Usado por Fly.io para health checks y por el job de keep-alive externo
# para evitar que la máquina se suspenda por inactividad.
# ──────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"ok": True}


# ──────────────────────────────────────────────
# POST /auth/login
# ──────────────────────────────────────────────
@app.post("/auth/login")
async def auth_login(body: LoginRequest):
    """Autentica con la API de Biwenger y guarda las credenciales."""
    try:
        result = await do_login(body.email, body.password)
        return {
            "ok": True,
            "user_name": result.get("user_name"),
            "user_id": result.get("user_id"),
            "league_id": result.get("league_id"),
        }
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        logger.error(f"Error en login: {e}")
        raise HTTPException(status_code=500, detail=f"Error de conexión: {str(e)}")


# ──────────────────────────────────────────────
# POST /auth/logout
# ──────────────────────────────────────────────
@app.post("/auth/logout")
async def auth_logout():
    """Cierra la sesión eliminando las credenciales de la BD."""
    await clear_auth()
    return {"ok": True}


# ──────────────────────────────────────────────
# GET /auth/status
# ──────────────────────────────────────────────
@app.get("/auth/status")
async def auth_status():
    """Devuelve el estado de la sesión actual."""
    auth = await get_auth()
    if auth and auth.get("token"):
        return {
            "logged_in": True,
            "user_name": auth.get("user_name"),
            "user_id": auth.get("user_id"),
            "league_id": auth.get("league_id"),
            "email": auth.get("email"),
            "created_at": auth.get("created_at"),
        }
    return {"logged_in": False}


# ──────────────────────────────────────────────
# POST /sync — Ejecuta los 10 scrapers
# ──────────────────────────────────────────────
@app.post("/sync")
async def sync_all():
    """Ejecuta los 10 scrapers secuencialmente."""
    global sync_state

    auth = await get_auth()
    if not auth or not auth.get("token"):
        raise HTTPException(status_code=401, detail="No hay sesión activa. Inicia sesión primero.")

    if sync_state["running"]:
        return {"ok": False, "mensaje": "Sincronización ya en curso"}

    async def _do_sync():
        global sync_state
        sync_state["running"] = True
        sync_state["progress"] = []
        sync_state["error"] = None
        try:
            results = await run_all_scrapers()
            for r in results:
                estado = "✓" if r.get("ok") else "✗"
                sync_state["progress"].append({
                    "scraper": r["scraper"],
                    "estado": estado,
                    "mensaje": r.get("error", "OK"),
                    "timestamp": datetime.now().isoformat(),
                })
            sync_state["last_sync"] = datetime.now().isoformat()
        except Exception as e:
            sync_state["error"] = str(e)
            logger.error(f"Error en sincronización: {e}")
        finally:
            sync_state["running"] = False

    # Ejecutar en background para que el cliente pueda hacer polling
    asyncio.create_task(_do_sync())
    return {"ok": True, "mensaje": "Sincronización iniciada"}


# ──────────────────────────────────────────────
# GET /sync/status — Estado de la sincronización (para polling)
# ──────────────────────────────────────────────
@app.get("/sync/status")
async def sync_status():
    return {
        "running": sync_state["running"],
        "progress": sync_state["progress"],
        "last_sync": sync_state["last_sync"],
        "error": sync_state["error"],
    }


# ──────────────────────────────────────────────
# GET /mercado — Jugadores disponibles con scores
# ──────────────────────────────────────────────
@app.get("/mercado")
async def get_mercado():
    auth = await get_auth()
    mi_user_id = auth.get("user_id") if auth else None
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT me.*,
                   COALESCE(j.team_name, me.equipo) AS team_name,
                   COALESCE(j.status, 'ok')         AS status_cf,
                   j.status_info,
                   COALESCE(j.price_increment, 0)   AS price_increment,
                   j.next_match_date,
                   j.next_match_rival
            FROM mercado me
            LEFT JOIN jugadores_mundo j ON me.id = j.id
            WHERE me.user_id IS NULL OR me.user_id != ?
            ORDER BY me.score_oportunidad DESC
        """, (mi_user_id,)) as c:
            rows = await c.fetchall()
    return {"ok": True, "data": _rows_to_list(rows)}


# ──────────────────────────────────────────────
# GET /plantilla — Mi plantilla con ROI
# ──────────────────────────────────────────────
@app.get("/plantilla")
async def get_plantilla():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT m.*,
                   COALESCE(j.team_name, m.equipo) AS team_name,
                   COALESCE(j.status, 'ok')        AS status_cf,
                   j.status_info,
                   COALESCE(j.price_increment, 0)  AS price_increment,
                   j.next_match_date,
                   j.next_match_rival,
                   p.prob_gol,
                   p.prob_asistencia,
                   p.minutos_esperados,
                   p.valoracion_mundial,
                   p.recomendacion      AS proyeccion_recomendacion,
                   p.justificacion      AS proyeccion_justificacion
            FROM mi_plantilla m
            LEFT JOIN jugadores_mundo j ON m.id = j.id
            LEFT JOIN proyecciones_jugador p ON m.id = p.player_id
            ORDER BY m.puntos_totales DESC
        """) as c:
            rows = await c.fetchall()
    return {"ok": True, "data": _rows_to_list(rows)}


# ──────────────────────────────────────────────
# GET /finanzas — Saldo y valor de plantilla
# ──────────────────────────────────────────────
@app.get("/finanzas")
async def get_finanzas():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM finanzas ORDER BY id DESC LIMIT 1"
        ) as c:
            row = await c.fetchone()
    return {"ok": True, "data": dict(row) if row else {}}


# ──────────────────────────────────────────────
# GET /clasificacion — Tabla de la liga
# ──────────────────────────────────────────────
@app.get("/clasificacion")
async def get_clasificacion():
    """Devuelve la clasificación con un saldo estimado por manager calculado como:

        saldo_estimado = 50_000_000 − valor_plantilla
                         + Σ ventas (tipo='VENTA')
                         − Σ compras (tipo='COMPRA' / 'market')
                         (agrupado por usuario_id en movimientos_rivales)

    Para el usuario autenticado se sustituye por el saldo REAL de `finanzas.saldo`.
    """
    PRESUPUESTO_INICIAL = 50_000_000

    auth = await get_auth() or {}
    mi_user_id = auth.get("user_id") or 0

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute("""
            SELECT c.*,
                   COALESCE(SUM(CASE WHEN mr.tipo = 'VENTA'
                                     THEN mr.precio ELSE 0 END), 0) AS total_ventas,
                   COALESCE(SUM(CASE WHEN mr.tipo IN ('COMPRA','market','buy')
                                     THEN mr.precio ELSE 0 END), 0) AS total_compras
            FROM clasificacion c
            LEFT JOIN movimientos_rivales mr ON mr.usuario_id = c.id
            GROUP BY c.id
            ORDER BY c.posicion
        """) as cur:
            rows = await cur.fetchall()

        async with db.execute(
            "SELECT saldo FROM finanzas ORDER BY id DESC LIMIT 1"
        ) as cur:
            fin_row = await cur.fetchone()
            saldo_real = fin_row["saldo"] if fin_row else None

    data = []
    for r in rows:
        d = dict(r)
        ventas = d.pop("total_ventas", 0) or 0
        compras = d.pop("total_compras", 0) or 0
        valor_plantilla = d.get("valor_plantilla", 0) or 0
        d["saldo_estimado"] = PRESUPUESTO_INICIAL - valor_plantilla + ventas - compras
        d["es_estimado"] = True
        # Para el usuario logueado: sustituir por saldo real si está disponible.
        if mi_user_id and d.get("id") == mi_user_id and saldo_real is not None:
            d["saldo_estimado"] = saldo_real
            d["es_estimado"] = False
        data.append(d)

    return {"ok": True, "data": data}


# ──────────────────────────────────────────────
# GET /transfers — Últimos movimientos de la liga
# ──────────────────────────────────────────────
@app.get("/transfers")
async def get_transfers():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM movimientos_rivales ORDER BY id DESC LIMIT 50"
        ) as c:
            rows = await c.fetchall()
    return {"ok": True, "data": _rows_to_list(rows)}


# ──────────────────────────────────────────────
# GET /noticias — Noticias de mi plantilla
# ──────────────────────────────────────────────
@app.get("/noticias")
async def get_noticias():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM noticias_jugadores ORDER BY id DESC LIMIT 30"
        ) as c:
            rows = await c.fetchall()
    return {"ok": True, "data": _rows_to_list(rows)}


# ──────────────────────────────────────────────
# GET /historial-precios — Evolución de precios
# ──────────────────────────────────────────────
@app.get("/historial-precios")
async def get_historial_precios():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT hp.player_id    AS jugador_id,
                   hp.player_name  AS jugador_nombre,
                   hp.fecha,
                   hp.precio,
                   hp.price_increment
            FROM historial_precios hp
            INNER JOIN mi_plantilla mp ON hp.player_id = mp.id
            ORDER BY hp.player_id, hp.fecha
        """) as c:
            rows = await c.fetchall()
    return {"ok": True, "data": _rows_to_list(rows)}


# ──────────────────────────────────────────────
# POST /analizar — Motor de análisis (scores de oportunidad + ROI)
# Llamado automáticamente por el frontend antes de POST /consejos.
# Calcula score_oportunidad en mercado y actualiza métricas de mi_plantilla.
# ──────────────────────────────────────────────
@app.post("/analizar")
async def analizar():
    result = await run_analysis()
    return result


# ──────────────────────────────────────────────
# POST /consejos — Genera los 5 consejos de IA
# ──────────────────────────────────────────────
@app.post("/consejos")
async def generar_consejos():
    result = await generar_todos_los_consejos()
    return result


# ──────────────────────────────────────────────
# GET /consejos — Devuelve los últimos consejos guardados
# ──────────────────────────────────────────────
@app.get("/consejos")
async def get_consejos():
    consejos = await obtener_ultimos_consejos()
    return {"ok": True, "data": consejos}


# ──────────────────────────────────────────────
# POST /chat — Chat libre con el analista IA
# ──────────────────────────────────────────────
@app.post("/chat")
async def chat(req: ChatRequest):
    respuesta = await generar_respuesta_chat(req.mensaje)
    timestamp = datetime.now().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO historial_analisis (jugador_id, jugador_nombre, json_respuesta, tipo_consulta) VALUES (?, ?, ?, ?)",
            (0, req.mensaje[:120], respuesta, "chat")
        )
        await db.commit()
    return {"respuesta": respuesta, "timestamp": timestamp}


# ──────────────────────────────────────────────
# GET /logs — Últimos logs de sincronización
# ──────────────────────────────────────────────
@app.get("/logs")
async def get_logs():
    logs = await get_sync_logs(100)
    return {"ok": True, "data": logs}


# ──────────────────────────────────────────────
# GET /test-gemini  →  lista modelos disponibles
# ──────────────────────────────────────────────
@app.get("/test-gemini")
async def test_gemini():
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY no configurada en .env")
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(url)
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=f"Gemini API error: {r.text[:500]}")
    data = r.json()
    models = [
        {"name": m.get("name"), "displayName": m.get("displayName"), "description": m.get("description", "")[:80]}
        for m in data.get("models", [])
    ]
    return {"ok": True, "api_key_prefix": api_key[:8] + "...", "model_count": len(models), "models": models}


# ──────────────────────────────────────────────
# GET /analizar-jugador/{jugador_id}
# ──────────────────────────────────────────────
@app.get("/analizar-jugador/{jugador_id}")
async def analizar_jugador(jugador_id: int):
    """Análisis profundo de un jugador con Gemini Search Grounding.
    Devuelve caché si hay análisis de menos de 24h."""
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY no configurada en .env")

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # ── 1. Caché de 24h ──
        async with db.execute("""
            SELECT id, json_respuesta, fecha
            FROM historial_analisis
            WHERE jugador_id = ?
              AND tipo_consulta = 'jugador'
              AND datetime(fecha) >= datetime('now', '-24 hours')
            ORDER BY id DESC LIMIT 1
        """, (jugador_id,)) as c:
            cached = await c.fetchone()
        if cached:
            import json as _json
            return {
                "ok": True,
                "desde_cache": True,
                "fecha_analisis": cached["fecha"],
                "data": _json.loads(cached["json_respuesta"]),
            }

        # ── 2. Datos del jugador desde BD ──
        async with db.execute(
            "SELECT * FROM mi_plantilla WHERE id = ?", (jugador_id,)
        ) as c:
            en_plantilla_row = await c.fetchone()

        async with db.execute(
            "SELECT * FROM mercado WHERE id = ?", (jugador_id,)
        ) as c:
            en_mercado_row = await c.fetchone()

        async with db.execute(
            "SELECT * FROM jugadores_mundo WHERE id = ?", (jugador_id,)
        ) as c:
            mundo_row = await c.fetchone()

    if not en_plantilla_row and not en_mercado_row and not mundo_row:
        raise HTTPException(status_code=404, detail=f"Jugador {jugador_id} no encontrado en BD")

    row = en_plantilla_row or en_mercado_row or mundo_row
    nombre    = row["nombre"] if "nombre" in row.keys() else row["name"]
    posicion  = row["posicion"] if "posicion" in row.keys() else row["position"]
    precio    = (row["precio_actual"] if "precio_actual" in row.keys()
                 else row["precio"] if "precio" in row.keys()
                 else row["price"])
    en_plantilla = en_plantilla_row is not None
    en_venta     = en_mercado_row is not None
    precio_venta = en_mercado_row["precio"] if en_venta else None

    if en_plantilla and en_venta:
        estado_str = f"Está en mi plantilla y en venta por {precio_venta}€"
    elif en_plantilla:
        estado_str = "Está en mi plantilla, no en venta"
    else:
        estado_str = "Disponible en el mercado"

    # ── 3. Prompt ──
    prompt = f"""Jugador: {nombre}, {posicion}, selección: desconocida (Mundial 2026)
Mundial 2026. Análisis completo para fantasy Biwenger.

DATOS REALES DE MI APLICACIÓN (no busques estos):
- Precio actual Biwenger: {precio}€
- {estado_str}

INSTRUCCIONES:
- Si no encuentras URL real y verificable, devuelve null
- No estimes ni inventes datos
- Tendencia minutos: si bajan partido a partido es "bajando" aunque el rating sea bueno
- Consulta específicamente para titularidad y recomendaciones: analiticafantasy.com, jornadaperfecta.com, futbolfantasy.es
- Para stats busca en sofascore.com/football/player/{nombre}

Devuelve ÚNICAMENTE el siguiente JSON sin explicaciones ni markdown:
{{
  "titularidad": {{
    "condicion": "titular/suplente/rotación",
    "competencia": "nombres jugadores que compiten por su puesto",
    "probabilidad_titular_proximo_partido": "alta/media/baja",
    "fuentes": {{
      "analiticafantasy": {{"recomendacion": null, "probabilidad_titular": null, "url": null}},
      "jornadaperfecta": {{"recomendacion": null, "probabilidad_titular": null, "url": null}},
      "futbolfantasy": {{"recomendacion": null, "probabilidad_titular": null, "url": null}}
    }}
  }},
  "forma": {{
    "ultimos_3_partidos": [
      {{"rival": "", "rating_sofascore": null, "minutos": null, "fecha": "", "goles": null, "asistencias": null}}
    ],
    "tendencia_rating": "subiendo/bajando/estable",
    "tendencia_minutos": "subiendo/bajando/estable",
    "fuente_sofascore": null
  }},
  "proximo_rival_mundial": {{
    "nombre": "", "fecha": "", "nivel": "débil/medio/fuerte",
    "ranking_fifa_rival": null, "analisis": ""
  }},
  "grupo_mundial": {{
    "nombre_grupo": "", "equipos": [],
    "probabilidad_clasificacion": "alta/media/baja", "analisis": ""
  }},
  "lesiones_sanciones": {{
    "estado": "disponible/lesionado/sancionado/duda",
    "detalle": null, "fuente": null
  }},
  "apuestas": {{
    "cuota_marcar_gol": null, "cuota_asistencia": null, "fuente_url": null
  }},
  "fantasy_especialistas": {{
    "analiticafantasy": {{"recomendacion": null, "puntuacion_esperada": null, "url": null}},
    "jornadaperfecta": {{"recomendacion": null, "puntuacion_esperada": null, "url": null}},
    "futbolfantasy": {{"recomendacion": null, "puntuacion_esperada": null, "url": null}}
  }},
  "veredicto": {{
    "decision": "RETIRAR VENTA/MANTENER EN VENTA/VENDER URGENTE/FICHAR/NO FICHAR",
    "justificacion": "",
    "confianza": "alta/media/baja",
    "precio_minimo_venta_recomendado": null,
    "riesgo_principal": ""
  }}
}}"""

    # ── 4. Llamada a Gemini 2.5 Flash con Google Search Grounding ──
    gemini_url = (
        f"https://generativelanguage.googleapis.com/v1beta/"
        f"models/gemini-2.5-flash:generateContent?key={api_key}"
    )
    payload = {
        "tools": [{"google_search": {}}],
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(gemini_url, json=payload)

    if r.status_code != 200:
        raise HTTPException(
            status_code=r.status_code,
            detail=f"Gemini error {r.status_code}: {r.text[:500]}"
        )

    gemini_body = r.json()
    raw_text = (
        gemini_body.get("candidates", [{}])[0]
        .get("content", {})
        .get("parts", [{}])[0]
        .get("text", "")
    )

    # Limpiar posible bloque ```json ... ```
    import json as _json, re as _re
    clean = _re.sub(r"^```(?:json)?\s*", "", raw_text.strip(), flags=_re.IGNORECASE)
    clean = _re.sub(r"\s*```$", "", clean)
    try:
        analysis = _json.loads(clean)
    except _json.JSONDecodeError:
        analysis = {"raw": raw_text, "error": "No se pudo parsear el JSON de Gemini"}

    # ── 5. Guardar en historial_analisis ──
    now_iso = datetime.now().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO historial_analisis (jugador_id, jugador_nombre, fecha, json_respuesta, tipo_consulta)
            VALUES (?, ?, ?, ?, 'jugador')
        """, (jugador_id, nombre, now_iso, _json.dumps(analysis, ensure_ascii=False)))
        await db.commit()

    return {
        "ok": True,
        "desde_cache": False,
        "fecha_analisis": now_iso,
        "data": analysis,
    }


# ──────────────────────────────────────────────
# GET /historial-analisis — Todos los análisis guardados
# ──────────────────────────────────────────────
@app.get("/historial-analisis")
async def get_historial_analisis():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT id, jugador_id, jugador_nombre, fecha, tipo_consulta,
                   json(json_extract(json_respuesta, '$.veredicto.decision')) AS veredicto_decision,
                   json(json_extract(json_respuesta, '$.veredicto.confianza')) AS veredicto_confianza,
                   CASE WHEN tipo_consulta != 'jugador' THEN json_respuesta ELSE NULL END AS json_respuesta
            FROM historial_analisis
            ORDER BY id DESC
            LIMIT 100
        """) as c:
            rows = await c.fetchall()
    return {"ok": True, "data": _rows_to_list(rows)}


if __name__ == "__main__":
    import uvicorn
    # En Render, PORT viene inyectada por la plataforma. En local cae a 8000.
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
