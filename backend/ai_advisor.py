# Consejero IA — llamada única a Gemini con Google Search Grounding
import httpx
import os
import re
import logging
import aiosqlite
from datetime import datetime
from database import DB_PATH, get_auth

logger = logging.getLogger(__name__)

_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"

# Marcadores de sección que Gemini debe respetar en su respuesta
_SECCIONES = ["COMPRAR", "VENDER", "11_IDEAL", "ESPECULACION", "ALERTA_RIVALES"]
_SEP = "==={}==="


async def _llamar_gemini_grounded(prompt: str) -> str:
    """Llamada única a Gemini 2.5 Flash con Google Search Grounding."""
    import traceback
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        logger.error("GEMINI_API_KEY no está configurada en .env")
        return "⚠️ GEMINI_API_KEY no configurada en .env"
    url = f"{_GEMINI_BASE}?key={api_key}"
    payload = {
        "tools": [{"google_search": {}}],
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 8192},
    }
    logger.info(f"[Gemini] Enviando prompt ({len(prompt)} chars):\n{prompt[:3000]}")
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(url, json=payload)
        logger.info(f"[Gemini] status={r.status_code} | body (primeros 2000 chars):\n{r.text[:2000]}")
        r.raise_for_status()
        data = r.json()
        candidates = data.get("candidates", [])
        if not candidates:
            logger.error(f"[Gemini] Sin candidates en la respuesta: {data}")
            return f"⚠️ Gemini no devolvió candidates: {data}"
        parts = candidates[0].get("content", {}).get("parts", [])
        if not parts:
            logger.error(f"[Gemini] 'parts' vacío en candidate: {candidates[0]}")
            return ""
        text = parts[0].get("text", "")
        logger.info(f"[Gemini] Respuesta OK ({len(text)} chars)")
        return text
    except httpx.HTTPStatusError as e:
        logger.error(f"[Gemini] HTTPStatusError {e.response.status_code}:\n{e.response.text[:2000]}")
        return f"⚠️ Error HTTP {e.response.status_code}: {e.response.text[:500]}"
    except Exception as e:
        logger.error(f"[Gemini] Excepción inesperada:\n{traceback.format_exc()}")
        return f"⚠️ Error al contactar con la IA: {str(e)}"


async def llamar_gemini(prompt: str) -> str:
    """Wrapper público de _llamar_gemini_grounded para uso desde otros módulos."""
    return await _llamar_gemini_grounded(prompt)


async def llamar_gemini_sin_grounding(prompt: str) -> str:
    """Llamada a Gemini SIN Google Search Grounding (solo conocimiento del modelo)."""
    import traceback
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        return ""
    url = f"{_GEMINI_BASE}?key={api_key}"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.4, "maxOutputTokens": 512},
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(url, json=payload)
        r.raise_for_status()
        data = r.json()
        candidates = data.get("candidates", [])
        if not candidates:
            return ""
        parts = candidates[0].get("content", {}).get("parts", [])
        return parts[0].get("text", "") if parts else ""
    except Exception as e:
        logger.error(f"[Gemini sin grounding] Error: {e}")
        return ""


async def _recopilar_contexto() -> dict:
    """Recopila todos los datos relevantes de la BD para el contexto de la IA.

    IMPORTANTE: filtra explícitamente al propio usuario (auth.user_id) de los
    "rivales", para que Gemini no analice los movimientos/plantilla del usuario
    como si fueran de un rival.
    """
    auth = await get_auth() or {}
    mi_user_id = auth.get("user_id") or 0

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute("""
            SELECT m.*,
                   COALESCE(j.team_name, m.equipo) AS team_name,
                   COALESCE(j.status, 'ok')        AS status_cf,
                   j.status_info,
                   COALESCE(j.price_increment, 0)  AS price_increment,
                   j.next_match_date, j.next_match_rival,
                   j.fitness
            FROM mi_plantilla m
            LEFT JOIN jugadores_mundo j ON m.id = j.id
            ORDER BY m.puntos_totales DESC
        """) as c:
            plantilla = [dict(r) for r in await c.fetchall()]

        async with db.execute("""
            SELECT me.*,
                   COALESCE(j.team_name, me.equipo) AS team_name,
                   COALESCE(j.status, 'ok')         AS status_cf,
                   j.status_info,
                   COALESCE(j.price_increment, 0)   AS price_increment,
                   j.next_match_date, j.next_match_rival,
                   j.fitness
            FROM mercado me
            LEFT JOIN jugadores_mundo j ON me.id = j.id
            ORDER BY me.score_oportunidad DESC LIMIT 20
        """) as c:
            mercado = [dict(r) for r in await c.fetchall()]

        async with db.execute("SELECT * FROM finanzas ORDER BY id DESC LIMIT 1") as c:
            row = await c.fetchone()
            finanzas = dict(row) if row else {}

        async with db.execute("SELECT * FROM clasificacion ORDER BY posicion") as c:
            clasificacion = [dict(r) for r in await c.fetchall()]

        # Movimientos: split entre los míos y los de rivales (excluyendo a mi user_id).
        async with db.execute(
            "SELECT * FROM movimientos_rivales "
            "WHERE usuario_id != ? OR usuario_id IS NULL "
            "ORDER BY id DESC LIMIT 30",
            (mi_user_id,)
        ) as c:
            movimientos_rivales = [dict(r) for r in await c.fetchall()]

        async with db.execute(
            "SELECT * FROM movimientos_rivales WHERE usuario_id = ? "
            "ORDER BY id DESC LIMIT 15",
            (mi_user_id,)
        ) as c:
            mis_movimientos = [dict(r) for r in await c.fetchall()]

        # Jugadores más comunes en plantillas rivales (excluyendo la mía).
        async with db.execute("""
            SELECT jugador_nombre, COUNT(*) as num_rivales
            FROM plantillas_rivales
            WHERE usuario_id != ? OR usuario_id IS NULL
            GROUP BY jugador_id
            ORDER BY num_rivales DESC
            LIMIT 10
        """, (mi_user_id,)) as c:
            jugadores_comunes = [dict(r) for r in await c.fetchall()]

        # Plantillas rivales (excluyendo la mía).
        async with db.execute("""
            SELECT pr.usuario_nombre,
                   GROUP_CONCAT(COALESCE(j.name, pr.jugador_nombre), ', ') AS jugadores
            FROM plantillas_rivales pr
            LEFT JOIN jugadores_mundo j ON j.id = pr.jugador_id
            WHERE pr.usuario_id != ? OR pr.usuario_id IS NULL
            GROUP BY pr.usuario_nombre
            ORDER BY pr.usuario_nombre
        """, (mi_user_id,)) as c:
            plantillas_rivales = [dict(r) for r in await c.fetchall()]

    return {
        "plantilla": plantilla,
        "mercado_top20": mercado,
        "finanzas": finanzas,
        "clasificacion": clasificacion,
        "ultimos_movimientos": movimientos_rivales,  # alias retrocompatible
        "movimientos_rivales": movimientos_rivales,
        "mis_movimientos": mis_movimientos,
        "jugadores_comunes_rivales": jugadores_comunes,
        "plantillas_rivales": plantillas_rivales,
        "mi_user_id": mi_user_id,
    }


_POS_ABREV = {
    "Portero": "P", "Defensa": "D", "Centrocampista": "C", "Delantero": "DL",
    "portero": "P", "defensa": "D", "centrocampista": "C", "delantero": "DL",
    "1": "P", "2": "D", "3": "C", "4": "DL",
}


def _prob_titular(j: dict) -> int:
    """Devuelve la mejor estimación disponible de probabilidad de titularidad.

    Prioridad (de más a menos fiable):
      1. prob_media       (combinación FF + Jornada Perfecta, calculada por scraper)
      2. prob_futbol_fantasy
      3. prob_jornada
      4. prob_titularidad (estimación antigua de Gemini — frecuentemente 0% u
         obsoleta, solo como último fallback)
      5. 50 (default neutro si no hay nada)

    Se devuelve int porque el prompt no necesita decimales.
    """
    for key in ("prob_media", "prob_futbol_fantasy", "prob_jornada", "prob_titularidad"):
        val = j.get(key)
        if val is not None:
            try:
                return int(round(float(val)))
            except (TypeError, ValueError):
                continue
    return 50


def _fmt_jugador(j: dict) -> str:
    pos_raw = j.get("posicion", "?")
    pos = _POS_ABREV.get(str(pos_raw), pos_raw)
    team = j.get("team_name") or j.get("equipo", "?")
    precio = j.get("precio_actual", j.get("precio", 0)) or 0
    pts = j.get("puntos_totales", j.get("puntos_ultima_jornada", 0)) or 0
    inc = j.get("price_increment", 0) or 0
    tendencia = f"↑+{inc:,}€" if inc > 0 else (f"↓{inc:,}€" if inc < 0 else "→")
    status = j.get("status_cf", j.get("status", "ok")) or "ok"
    status_info = j.get("status_info") or ""
    if status == "ok":
        estado = "✅ Disponible"
    elif status == "doubt":
        estado = f"⚠️ Duda — {status_info}" if status_info else "⚠️ Duda"
    else:
        estado = f"🔴 Lesionado — {status_info}" if status_info else "🔴 No disponible"
    next_rival = j.get("next_match_rival") or ""
    next_date = j.get("next_match_date")
    if next_rival and next_date:
        from datetime import datetime as _dt
        try:
            fecha_str = _dt.fromtimestamp(int(next_date)).strftime("%d/%m")
        except Exception:
            fecha_str = str(next_date)
        proximo = f"vs {next_rival} el {fecha_str}"
    else:
        proximo = "sin fecha"
    # fitness: JSON array of recent match points (empty = tournament not started)
    import json as _json
    fitness_raw = j.get("fitness") or "[]"
    try:
        fitness_list = _json.loads(fitness_raw) if isinstance(fitness_raw, str) else (fitness_raw or [])
    except Exception:
        fitness_list = []
    fitness_str = f"Forma últimas jornadas: {fitness_list}" if fitness_list else "Forma últimas jornadas: null (torneo no empezado)"
    return (
        f"{j.get('nombre','?')} [{pos}] ({team})"
        f" | Precio: {precio:,}€ {tendencia}"
        f" | Pts: {pts}"
        f" | {estado}"
        f" | Próximo: {proximo}"
        f" | {fitness_str}"
    )


def _construir_prompt_combinado(ctx: dict) -> str:
    """Construye el prompt único con todos los datos reales de la liga."""
    saldo = ctx["finanzas"].get("saldo", 0)

    plantilla_str = "\n".join(
        f"  {_fmt_jugador(j)} - Prob. titular: {_prob_titular(j)}%"
        for j in ctx["plantilla"]
    ) or "  (sin jugadores — sincroniza primero)"

    mercado_str = "\n".join(
        f"  {_fmt_jugador(j)}"
        for j in ctx["mercado_top20"][:20]
    ) or "  (mercado vacío)"

    mov_str = "\n".join(
        f"  {m.get('usuario_nombre','?')} "
        f"{'compró' if m.get('tipo') in ('market','buy','COMPRA') else 'vendió'} "
        f"a {m.get('jugador_nombre','?')} por {m.get('precio', 0):,}€"
        for m in ctx["movimientos_rivales"][:20]
    ) or "  (sin movimientos rivales recientes)"

    mis_mov_str = "\n".join(
        f"  {'compré' if m.get('tipo') in ('market','buy','COMPRA') else 'vendí'} "
        f"a {m.get('jugador_nombre','?')} por {m.get('precio', 0):,}€"
        for m in ctx.get("mis_movimientos", [])[:10]
    ) or "  (sin movimientos propios recientes)"

    clas_str = "\n".join(
        f"  {c.get('posicion','?')}. {c.get('nombre','?')} — {c.get('puntos_totales', 0)} pts "
        f"(saldo: {c.get('saldo', 0):,}€)"
        for c in ctx["clasificacion"]
    ) or "  (sin datos de clasificación)"

    comunes_str = "\n".join(
        f"  {j.get('jugador_nombre','?')} lo tienen {j.get('num_rivales', 0)} rivales"
        for j in ctx["jugadores_comunes_rivales"]
    ) or "  (sin datos)"

    rivales_str = "\n".join(
        f"  {r.get('usuario_nombre','?')}: {r.get('jugadores', '(vacía)')}"
        for r in ctx.get("plantillas_rivales", [])
    ) or "  (sin datos de plantillas rivales)"

    sep = _SEP
    secciones_esperadas = "\n".join(
        f"{sep.format(s)}\n[tu consejo aquí]" for s in _SECCIONES
    )

    return f"""Eres un analista experto en fantasy football para Biwenger Mundial 2026.
El torneo arranca el 11 de junio de 2026. Aún no ha empezado.
Todos los jugadores tienen 0 puntos porque el torneo NO ha comenzado todavía — es correcto.

IMPORTANTE — FIABILIDAD DE LOS DATOS:
Los campos status/status_cf de cada jugador vienen de la API oficial de Biwenger y son 100% fiables.
Si el status es 'ok', el jugador ESTÁ disponible y convocado — NO lo contradigas con búsquedas externas.
Si el status es 'doubt', hay duda real (detallada en status_info). Si es 'injured', está lesionado.
El campo fitness contiene los puntos reales de últimas jornadas (null = torneo no empezado aún).
Cuando el torneo empiece, el campo fitness será más fiable que cualquier análisis externo de forma reciente.
Usa Google Search SOLO para datos que NO tenemos: convocatorias finales, cuotas de apuestas,
análisis de analiticafantasy.com y jornadaperfecta.com, y noticias de última hora.

DATOS REALES DE MI LIGA:
- Mi saldo disponible: {saldo:,}€
- Mi plantilla ({len(ctx['plantilla'])} jugadores):
{plantilla_str}
- Mercado disponible (top 20 por score):
{mercado_str}
- Mis movimientos recientes (compras/ventas hechas por mí, NO son de rivales):
{mis_mov_str}
- Movimientos de RIVALES recientes (excluyen los míos):
{mov_str}
- Clasificación completa:
{clas_str}
- Jugadores más comunes en plantillas rivales:
{comunes_str}
- Plantillas completas de rivales:
{rivales_str}

INSTRUCCIÓN CLAVE: Usa Google Search para buscar información actualizada sobre los jugadores
de mi plantilla y del mercado: convocatorias confirmadas para el Mundial 2026, titularidad
esperada, lesiones, y análisis de analiticafantasy.com y jornadaperfecta.com.
No te bases solo en los datos que te doy — búscalos y enriquécelos con información real y reciente.

REGLAS DE POSICIÓN (OBLIGATORIAS):
Las posiciones son: P=Portero, D=Defensa, C=Centrocampista, DL=Delantero.
Un jugador NUNCA puede ocupar una posición diferente a la suya. Jamás pongas un [C] de delantero
ni un [D] de centrocampista. En el 11 IDEAL usa cada jugador ÚNICAMENTE en su posición natural.

FILTRO ECONÓMICO PARA VENDER:
Solo recomienda vender jugadores con precio_actual > 500.000€.
No recomiendes vender jugadores por debajo de ese umbral salvo que su "Prob. titular"
(el porcentaje que ves al lado de cada jugador de mi plantilla) sea 0%, o su status
sea 'injured' con lesión grave.

NOTA SOBRE "Prob. titular": ese valor es la mejor estimación disponible de
probabilidad de titularidad combinando dos fuentes externas (FútbolFantasy y
JornadaPerfecta). Considéralo el indicador principal de minutos esperados.

Dame consejos concretos y accionables. Estructura tu respuesta EXACTAMENTE con estos marcadores:

{sep.format("COMPRAR")}
TOP 3 FICHAJES — ordénalos de mayor a menor prioridad. Para cada uno indica:
1. [Nombre] ([posición]) — Precio: X€ — Por qué ficharlo: justificación con titularidad y potencial goleador/puntuador
2. ...
3. ...

{sep.format("VENDER")}
TOP 3 VENTAS URGENTES de mi plantilla — ordénalos de mayor a menor urgencia. Solo jugadores >500K€ salvo lesión grave. Para cada uno indica:
1. [Nombre] — Precio: X€ — Por qué venderlo: razón concreta (lesión, no titular, selección débil, etc.)
2. ...
3. ...

{sep.format("11_IDEAL")}
FORMACIÓN Y 11 IDEAL usando SOLO jugadores de MI PLANTILLA. Respeta ESTRICTAMENTE las posiciones [P]/[D]/[C]/[DL].
Indica: Formación (ej. 4-3-3), luego lista los 11 con posición y justificación breve de cada uno.

{sep.format("ESPECULACION")}
TOP 3 CHOLLOS — jugadores baratos del mercado con potencial de revalorización. Para cada uno:
1. [Nombre] — Precio: X€ — Por qué puede subir: razón concreta
2. ...
3. ...

{sep.format("ALERTA_RIVALES")}
Análisis de los movimientos de mis rivales y estrategia recomendada para contrarrestarlos.

IMPORTANTE: Usa exactamente los marcadores ===COMPRAR===, ===VENDER===, ===11_IDEAL===,
===ESPECULACION=== y ===ALERTA_RIVALES===. No añadas texto antes del primer marcador."""


async def generar_respuesta_chat(mensaje: str) -> str:
    """Responde una pregunta libre usando el contexto de la liga + Google Search Grounding."""
    ctx = await _recopilar_contexto()
    saldo = ctx["finanzas"].get("saldo", 0)

    plantilla_str = "\n".join(
        f"  {_fmt_jugador(j)}"
        for j in ctx["plantilla"]
    ) or "  (sin jugadores — sincroniza primero)"

    mercado_str = "\n".join(
        f"  {_fmt_jugador(j)}"
        for j in ctx["mercado_top20"][:10]
    ) or "  (mercado vacío)"

    mov_str = "\n".join(
        f"  {m.get('usuario_nombre','?')} "
        f"{'compró' if m.get('tipo') in ('market','buy','COMPRA') else 'vendió'} "
        f"a {m.get('jugador_nombre','?')} por {m.get('precio', 0):,}€"
        for m in ctx["movimientos_rivales"][:10]
    ) or "  (sin movimientos rivales)"

    clas_str = "\n".join(
        f"  {c.get('posicion','?')}. {c.get('nombre','?')} — {c.get('puntos_totales', 0)} pts"
        for c in ctx["clasificacion"]
    ) or "  (sin datos)"

    prompt = f"""Eres un analista experto en fantasy football para Biwenger Mundial 2026.
Tienes acceso a los datos reales de la liga del usuario.
Responde de forma directa y concisa. Máximo 3-4 párrafos.
Usa Google Search cuando necesites información externa actualizada sobre jugadores (lesiones, convocatorias, titularidad esperada).

DATOS DE LA LIGA:
- Saldo disponible: {saldo:,}€
- Mi plantilla:
{plantilla_str}
- Mercado (top 10 por score):
{mercado_str}
- Últimos movimientos rivales:
{mov_str}
- Clasificación:
{clas_str}

PREGUNTA DEL USUARIO: {mensaje}"""

    return await _llamar_gemini_grounded(prompt)


def _parsear_secciones(texto: str) -> dict[str, str]:
    """Extrae las 5 secciones del texto de respuesta de Gemini."""
    resultado: dict[str, str] = {}
    patron = r"===(" + "|".join(_SECCIONES) + r")===(.*?)(?====(?:" + "|".join(_SECCIONES) + r")===|$)"
    for m in re.finditer(patron, texto, re.DOTALL):
        clave = m.group(1)
        contenido = m.group(2).strip()
        resultado[clave] = contenido

    # Fallback: si no se parseó ninguna sección devolver todo como COMPRAR
    if not resultado:
        logger.warning("No se encontraron marcadores de sección en la respuesta de Gemini")
        resultado["COMPRAR"] = texto.strip()

    return resultado


async def generar_todos_los_consejos() -> dict:
    """Genera los 5 consejos con una única llamada a Gemini + Google Search Grounding."""
    ctx = await _recopilar_contexto()
    prompt = _construir_prompt_combinado(ctx)

    logger.info("Llamando a Gemini (grounded) para generar los 5 consejos…")
    respuesta_raw = await _llamar_gemini_grounded(prompt)
    logger.info(f"Respuesta Gemini ({len(respuesta_raw)} chars)")

    secciones = _parsear_secciones(respuesta_raw)
    ahora = datetime.now().isoformat()
    consejos: dict = {}

    async with aiosqlite.connect(DB_PATH) as db:
        for tipo in _SECCIONES:
            texto = secciones.get(tipo, f"⚠️ Sección {tipo} no generada por Gemini.")
            consejos[tipo] = texto
            await db.execute(
                "INSERT INTO consejos_ia (tipo, contenido, creado) VALUES (?, ?, ?)",
                (tipo, texto, ahora),
            )
        import json as _json
        fecha_tag = datetime.now().strftime("%Y-%m-%d")
        await db.execute(
            "INSERT INTO historial_analisis (jugador_id, jugador_nombre, json_respuesta, tipo_consulta) VALUES (?, ?, ?, ?)",
            (0, f"CONSEJOS_GENERALES_{fecha_tag}", _json.dumps(consejos, ensure_ascii=False), "consejos_generales")
        )
        await db.commit()

    return {"ok": True, "consejos": consejos}


async def obtener_ultimos_consejos() -> dict:
    """Devuelve los últimos consejos guardados en la BD."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        consejos = {}
        for tipo in ["COMPRAR", "VENDER", "11_IDEAL", "ESPECULACION", "ALERTA_RIVALES"]:
            async with db.execute(
                "SELECT contenido, creado FROM consejos_ia WHERE tipo = ? ORDER BY id DESC LIMIT 1",
                (tipo,)
            ) as c:
                row = await c.fetchone()
                if row:
                    consejos[tipo] = {"contenido": row["contenido"], "creado": row["creado"]}
    return consejos
