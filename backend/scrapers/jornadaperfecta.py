"""Scraper #9 — Jornada Perfecta (estado de jugadores y probabilidad de titularidad).

URL: https://www.jornadaperfecta.com/mundial/equipo/{slug}
Reusa de futbolfantasy.py: _slugify_team, TEAM_SLUG_OVERRIDES, USER_AGENT,
_build_player_index, _match_player.

Selectores:
  a.player[href*="/mundial/jugador/"]   → cada jugador
  img.face → atributo `alt` (nombre)
  div.status img → atributo `title` (estado)

Si no hay <div.status> o el title es vacío, se interpreta como "sin novedad" (disponible).

Almacena:
  - jp_estados (player_id PK)
  - mi_plantilla.prob_jornada
  - mi_plantilla.prob_media (recalculado al final desde prob_futbol_fantasy + prob_jornada)
"""
import asyncio
import logging
import re
from datetime import datetime
from typing import Optional

import aiosqlite
import httpx
from bs4 import BeautifulSoup

from database import DB_PATH, log_sync
from .futbolfantasy import (
    TEAM_SLUG_OVERRIDES,
    USER_AGENT,
    _slugify_team,
    _build_player_index,
    _match_player,
)
from ._common import recalcular_prob_media

logger = logging.getLogger(__name__)


BASE_URL = "https://www.jornadaperfecta.com/mundial/equipo/{slug}"
HREF_PLAYER_RE = re.compile(r"/mundial/jugador/([^/?#]+)")

# Overrides específicos de JP que difieren de FF.
# Verificados con peticiones HEAD: paises-bajos (200) vs FF=holanda;
# bosnia-y-herzegovina (200) vs FF=bosnia-herzegovina.
# Nueva Zelanda y Congo (RDC) devuelven 404 — JP no los cubre.
JP_TEAM_SLUG_OVERRIDES = {
    "Países Bajos": "paises-bajos",
    "Paises Bajos": "paises-bajos",
    "Holanda": "paises-bajos",
    "Netherlands": "paises-bajos",
    "Bosnia y Herzegovina": "bosnia-y-herzegovina",
    "Bosnia-Herzegovina": "bosnia-y-herzegovina",
    "Bosnia and Herzegovina": "bosnia-y-herzegovina",
}

# Mapeo estado → probabilidad de titularidad (0-100). Sin estado explícito se
# interpreta como "disponible" (la mayoría de jugadores aparecen sin icono).
ESTADO_A_PROB = {
    "Disponible": 85,
    "Duda siguiente partido": 40,
    "Duda": 40,
    "Lesionado": 0,
    "Sancionado": 0,
    "Apercibido": 70,
    "No disponible": 0,
}
PROB_DEFAULT_DESCONOCIDO = 50
PROB_SIN_ESTADO = 85  # No hay icono → sin novedad → asumir disponible


# ──────────────────────────────────────────────────────────────────────────
# Migración tabla jp_estados
# ──────────────────────────────────────────────────────────────────────────
async def _ensure_table(db: aiosqlite.Connection) -> None:
    await db.execute("""
        CREATE TABLE IF NOT EXISTS jp_estados (
            player_id INTEGER PRIMARY KEY,
            slug_jp TEXT,
            nombre_jp TEXT,
            estado TEXT,
            prob_jp INTEGER,
            fecha_update TEXT
        )
    """)


# ──────────────────────────────────────────────────────────────────────────
# Fetch + parse
# ──────────────────────────────────────────────────────────────────────────
async def _fetch_team(client: httpx.AsyncClient, slug: str) -> Optional[str]:
    url = BASE_URL.format(slug=slug)
    try:
        r = await client.get(url, headers={"User-Agent": USER_AGENT}, timeout=20.0,
                             follow_redirects=True)
        if r.status_code != 200:
            logger.warning(f"[jornadaperfecta] {slug}: HTTP {r.status_code}")
            return None
        return r.text
    except Exception as e:
        logger.warning(f"[jornadaperfecta] {slug}: {type(e).__name__}: {e}")
        return None


def _parse_team_html(html: str) -> list:
    """Devuelve [{slug, nombre, estado, prob}, ...]."""
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for a in soup.select('a.player[href*="/mundial/jugador/"]'):
        href = a.get("href", "")
        m = HREF_PLAYER_RE.search(href)
        if not m:
            continue
        slug = m.group(1)

        face = a.select_one("img.face")
        nombre = (face.get("alt") if face else "") or ""
        nombre = nombre.strip()

        estado_raw = None
        status_img = a.select_one("div.status img")
        if status_img:
            estado_raw = status_img.get("title")
            if estado_raw:
                estado_raw = estado_raw.strip()

        if not estado_raw:
            # Sin icono de estado → asumir disponible
            estado = "Sin novedad"
            prob = PROB_SIN_ESTADO
        elif estado_raw in ESTADO_A_PROB:
            estado = estado_raw
            prob = ESTADO_A_PROB[estado_raw]
        else:
            estado = estado_raw
            prob = PROB_DEFAULT_DESCONOCIDO
            logger.info(f"[jornadaperfecta] estado no reconocido: '{estado_raw}' (slug={slug})")

        out.append({"slug": slug, "nombre": nombre, "estado": estado, "prob": prob})
    return out


# ──────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────
async def scrape_jornadaperfecta(client: httpx.AsyncClient = None) -> dict:
    """Scrapea jornadaperfecta.com y actualiza prob_jornada + jp_estados.
    El parámetro `client` se ignora (cliente propio con UA navegador).
    """
    try:
        # 1. Equipos únicos desde jugadores_mundo
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT DISTINCT team_name FROM jugadores_mundo "
                "WHERE team_name IS NOT NULL AND team_name != ''"
            ) as cur:
                rows = await cur.fetchall()
            equipos = [r["team_name"] for r in rows]

        if not equipos:
            await log_sync("jornadaperfecta", "ok", "sin equipos en jugadores_mundo")
            return {"ok": True, "count": 0}

        # 2. team_name → slug. Prioridad: overrides JP-específicos → overrides FF
        # → slug derivado del nombre.
        slugs = {}
        for team in equipos:
            slug = JP_TEAM_SLUG_OVERRIDES.get(team) or TEAM_SLUG_OVERRIDES.get(team)
            if not slug:
                slug = _slugify_team(team)
                logger.info(f"[jornadaperfecta] slug derivado: '{team}' → '{slug}'")
            slugs[team] = slug

        logger.info(f"[jornadaperfecta] iniciando: {len(slugs)} equipos a scrappear")

        # 3. Fetch secuencial con rate-limit 1s
        all_entries = []  # [{team_name, slug, nombre, estado, prob}]
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as own_client:
            for i, (team, slug) in enumerate(slugs.items(), 1):
                html = await _fetch_team(own_client, slug)
                if html is None:
                    logger.warning(f"[jornadaperfecta] [{i}/{len(slugs)}] {team} ({slug}): sin HTML")
                else:
                    entries = _parse_team_html(html)
                    for e in entries:
                        e["team_name"] = team
                    all_entries.extend(entries)
                    logger.info(f"[jornadaperfecta] [{i}/{len(slugs)}] {team} ({slug}): "
                                f"{len(entries)} jugadores parseados")
                await asyncio.sleep(1.0)

        if not all_entries:
            msg = "0 jugadores parseados (¿JP cambió el HTML?)"
            await log_sync("jornadaperfecta", "error", msg)
            return {"ok": False, "error": msg}

        # 4. Match contra jugadores_mundo (mismo algoritmo de 4 niveles que FF)
        ahora = datetime.now().isoformat()
        async with aiosqlite.connect(DB_PATH) as db:
            await _ensure_table(db)
            index = await _build_player_index(db)

            matched_player_ids = set()
            sin_match = 0
            for e in all_entries:
                pid = _match_player(e["slug"], "", index, slugs)
                if pid is None:
                    sin_match += 1
                    continue
                matched_player_ids.add(pid)
                await db.execute("""
                    INSERT INTO jp_estados
                        (player_id, slug_jp, nombre_jp, estado, prob_jp, fecha_update)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(player_id) DO UPDATE SET
                        slug_jp = excluded.slug_jp,
                        nombre_jp = excluded.nombre_jp,
                        estado = excluded.estado,
                        prob_jp = excluded.prob_jp,
                        fecha_update = excluded.fecha_update
                """, (pid, e["slug"], e["nombre"], e["estado"], e["prob"], ahora))

            # 5. Actualizar mi_plantilla.prob_jornada desde jp_estados
            await db.execute("""
                UPDATE mi_plantilla
                   SET prob_jornada = (
                       SELECT prob_jp FROM jp_estados
                       WHERE jp_estados.player_id = mi_plantilla.id
                   )
                 WHERE id IN (SELECT player_id FROM jp_estados)
            """)

            # 6. Recalcular prob_media (combinando con prob_futbol_fantasy)
            await recalcular_prob_media(db)

            # Estadísticas finales
            async with db.execute(
                "SELECT COUNT(*) FROM mi_plantilla WHERE prob_jornada IS NOT NULL"
            ) as cur:
                row = await cur.fetchone()
                plantilla_con_prob = row[0] if row else 0
            async with db.execute("SELECT COUNT(*) FROM mi_plantilla") as cur:
                row = await cur.fetchone()
                plantilla_total = row[0] if row else 0

            await db.commit()

        msg = (
            f"{len(matched_player_ids)} matches en jugadores_mundo, "
            f"{sin_match} sin match (de {len(all_entries)} entradas JP) | "
            f"plantilla: {plantilla_con_prob}/{plantilla_total} con prob_jornada"
        )
        logger.info(f"[jornadaperfecta] {msg}")
        await log_sync("jornadaperfecta", "ok", msg)
        return {
            "ok": True,
            "count": len(matched_player_ids),
            "sin_match": sin_match,
            "jp_total": len(all_entries),
            "plantilla_con_prob": plantilla_con_prob,
            "plantilla_total": plantilla_total,
        }

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        logger.error(f"[jornadaperfecta] {type(e).__name__}: {e}\n{tb}")
        msg = f"{type(e).__name__}: {e}" if str(e) else f"{type(e).__name__}: (sin mensaje)"
        await log_sync("jornadaperfecta", "error", msg[:500])
        return {"ok": False, "error": msg}
