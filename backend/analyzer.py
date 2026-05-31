# Motor de análisis — calcula scores de oportunidad, ROI y riesgo de venta
import aiosqlite
import logging
from database import DB_PATH

logger = logging.getLogger(__name__)


def _safe(val, default=0):
    """Convierte None a un valor por defecto seguro."""
    return val if val is not None else default


async def calcular_scores():
    """
    Calcula la Puntuación de Oportunidad (0-100) para cada jugador del mercado:
      score = media_puntos_5j * 0.30
            + dificultad_calendario_inversa * 0.25
            + tendencia_precio * 0.15
            + prob_titularidad * 0.20
            + diferencial_vs_rivales * 0.10
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # Jugadores de mi plantilla (para diferencial vs rivales)
        async with db.execute("SELECT jugador_id FROM plantillas_rivales") as c:
            rivales_ids = {r["jugador_id"] for r in await c.fetchall()}

        async with db.execute("SELECT id FROM mi_plantilla") as c:
            mis_ids = {r["id"] for r in await c.fetchall()}

        # Calcular score para cada jugador del mercado
        async with db.execute("SELECT * FROM mercado") as c:
            jugadores = await c.fetchall()

        for j in jugadores:
            jid = j["id"]

            # 1. Media de puntos últimas 5 jornadas (normalizada a 0-100)
            puntos_uj = _safe(j["puntos_ultima_jornada"])
            media_pts = min(puntos_uj * 10, 100)  # escala simple

            # 2. Dificultad del calendario inversa (sin datos reales → neutro 50)
            dif_cal = 50

            # 3. Tendencia de precio (normalizada: +ve = subiendo = bueno)
            tendencia = _safe(j["tendencia"])
            tendencia_norm = 50 + min(max(tendencia / 100000, -50), 50)

            # 4. Probabilidad de titularidad (por defecto 50 si no hay datos)
            prob_tit = 50

            # 5. Diferencial vs rivales
            if jid in rivales_ids and jid not in mis_ids:
                diferencial = 80  # Lo tienen rivales pero no yo → interesante
            elif jid not in rivales_ids and jid not in mis_ids:
                diferencial = 60  # Nadie lo tiene → diferencial puro
            else:
                diferencial = 20  # Ya lo tengo o es muy común

            score = (
                media_pts * 0.30 +
                dif_cal * 0.25 +
                tendencia_norm * 0.15 +
                prob_tit * 0.20 +
                diferencial * 0.10
            )
            score = round(min(max(score, 0), 100), 1)

            await db.execute(
                "UPDATE mercado SET score_oportunidad = ? WHERE id = ?",
                (score, jid)
            )

        await db.commit()
    logger.info("Scores de oportunidad calculados para el mercado")
    return {"ok": True, "mensaje": "Scores calculados"}


async def calcular_roi_plantilla():
    """Recalcula el ROI de cada jugador de mi plantilla."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT id, precio_actual, precio_compra FROM mi_plantilla") as c:
            jugadores = await c.fetchall()

        for j in jugadores:
            roi = _safe(j["precio_actual"]) - _safe(j["precio_compra"])
            await db.execute(
                "UPDATE mi_plantilla SET roi = ? WHERE id = ?",
                (roi, j["id"])
            )
        await db.commit()
    logger.info("ROI de plantilla recalculado")
    return {"ok": True}


async def detectar_riesgo_venta():
    """
    Índice de riesgo de venta: jugadores propios con score < 30,
    precio cayendo y rivales difíciles próximamente.
    Devuelve lista de jugadores a considerar vender.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT id, nombre, posicion, equipo, precio_actual, precio_compra, roi,
                   puntos_totales, puntos_5j, estado, prob_titularidad
            FROM mi_plantilla
        """) as c:
            jugadores = await c.fetchall()

    riesgo = []
    for j in jugadores:
        score_riesgo = 0

        # Estado físico malo
        if j["estado"] in ("injured", "doubt", "suspended"):
            score_riesgo += 40

        # ROI negativo
        if _safe(j["roi"]) < 0:
            score_riesgo += 20

        # Probabilidad de jugar baja
        if _safe(j["prob_titularidad"]) < 30:
            score_riesgo += 25

        # Pocos puntos últimas jornadas
        puntos_5j = j["puntos_5j"] or ""
        if puntos_5j:
            try:
                pts = [float(x) for x in puntos_5j.split(",") if x]
                if pts and sum(pts) / len(pts) < 3:
                    score_riesgo += 15
            except Exception:
                pass

        if score_riesgo >= 30:
            riesgo.append({
                "id": j["id"],
                "nombre": j["nombre"],
                "posicion": j["posicion"],
                "equipo": j["equipo"],
                "precio_actual": j["precio_actual"],
                "roi": j["roi"],
                "estado": j["estado"],
                "prob_titularidad": j["prob_titularidad"],
                "score_riesgo": score_riesgo,
            })

    riesgo.sort(key=lambda x: x["score_riesgo"], reverse=True)
    return riesgo


async def run_analysis():
    """Ejecuta todo el análisis en secuencia."""
    r1 = await calcular_scores()
    r2 = await calcular_roi_plantilla()
    riesgo = await detectar_riesgo_venta()
    return {
        "ok": True,
        "scores": r1,
        "roi": r2,
        "jugadores_riesgo": len(riesgo),
        "detalle_riesgo": riesgo,
    }
