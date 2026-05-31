"""Scraper #8 — FútbolFantasy (probabilidad de titularidad real).

HTML estático, sin JavaScript. Selectores:
- `a.camiseta[href*="/jugadores/"][href*="/world-cup-2026"]`
- atributo `data-probabilidad` → "80%" (str con %, convertir a int)
- atributo `data-equipo` → código país ej. "SUI"
- href → contiene slug del jugador (ej. ".../jugadores/gregor-kobel/world-cup-2026")

Almacena:
- `mi_plantilla.prob_futbol_fantasy` (jugadores de mi plantilla)
- `ff_probabilidades` (TODOS los matches contra jugadores_mundo)
"""
import asyncio
import logging
import re
import unicodedata
from datetime import datetime
from typing import Optional

import aiosqlite
import httpx
from bs4 import BeautifulSoup

from database import DB_PATH, log_sync

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────
# Mapeo team_name → slug FútbolFantasy
# ──────────────────────────────────────────────────────────────────────────
# Overrides para nombres en español que no slugifican directo a lo que FF usa.
# El resto se deriva automáticamente con `_slugify_team()`.
TEAM_SLUG_OVERRIDES = {
    # Inglés (por si el campo team_name viene en inglés)
    "France": "francia",
    "Tunisia": "tunez",
    "Iran": "iran",
    "Switzerland": "suiza",
    "USA": "estados-unidos",
    "United States": "estados-unidos",
    "Cape Verde": "cabo-verde",
    "Bosnia and Herzegovina": "bosnia-herzegovina",
    "Morocco": "marruecos",
    "South Africa": "sudafrica",
    "Sweden": "suecia",
    "Belgium": "belgica",
    "Germany": "alemania",
    "Spain": "espana",
    "Brazil": "brasil",
    "Italy": "italia",
    "Netherlands": "holanda",
    "Denmark": "dinamarca",
    "Croatia": "croacia",
    "Poland": "polonia",
    "Austria": "austria",
    "Saudi Arabia": "arabia-saudi",
    "Egypt": "egipto",
    "Senegal": "senegal",
    "Ivory Coast": "costa-de-marfil",
    "Côte d'Ivoire": "costa-de-marfil",
    "Cameroon": "camerun",
    "Algeria": "argelia",
    "Korea Republic": "corea-del-sur",
    "South Korea": "corea-del-sur",
    "Japan": "japon",
    "Australia": "australia",
    "Canada": "canada",
    "Mexico": "mexico",
    "Uruguay": "uruguay",
    "Colombia": "colombia",
    "Ecuador": "ecuador",
    "Chile": "chile",
    "Peru": "peru",
    "Paraguay": "paraguay",
    "Greece": "grecia",
    "Portugal": "portugal",
    "Norway": "noruega",
    "Wales": "gales",
    "Scotland": "escocia",
    "England": "inglaterra",
    "Turkey": "turquia",
    "Czech Republic": "republica-checa",
    "Czechia": "republica-checa",
    # Español (jugadores_mundo.team_name suele venir en español)
    "Bosnia y Herzegovina": "bosnia-herzegovina",
    "Bosnia-Herzegovina": "bosnia-herzegovina",
    "Países Bajos": "holanda",
    "Paises Bajos": "holanda",
    "Holanda": "holanda",
    "Congo (RDC)": "rd-congo",
    "Congo RDC": "rd-congo",
    "RD Congo": "rd-congo",
    "República Democrática del Congo": "rd-congo",
    "Costa de Marfil": "costa-de-marfil",
    "Corea del Sur": "corea-del-sur",
    "Corea del Norte": "corea-del-norte",
    "Estados Unidos": "estados-unidos",
    "Cabo Verde": "cabo-verde",
    "Arabia Saudí": "arabia-saudi",
    "Arabia Saudita": "arabia-saudi",
    "República Checa": "republica-checa",
    "Republica Checa": "republica-checa",
    "República de Irlanda": "republica-de-irlanda",
    "Irlanda del Norte": "irlanda-del-norte",
    "Nueva Zelanda": "nueva-zelanda",
    "Sudáfrica": "sudafrica",
    "España": "espana",
}

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

BASE_URL = "https://www.futbolfantasy.com/world-cup/equipos/{slug}"
HREF_PLAYER_RE = re.compile(r"/jugadores/([^/]+)/world-cup")
PROB_RE = re.compile(r"(\d+)")


# ──────────────────────────────────────────────────────────────────────────
# Helpers de normalización
# ──────────────────────────────────────────────────────────────────────────
def _strip_accents(text: str) -> str:
    if not text:
        return ""
    s = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in s if unicodedata.category(ch) != "Mn")


def _slugify_team(team_name: str) -> str:
    """Convierte 'Estados Unidos' → 'estados-unidos'."""
    if not team_name:
        return ""
    t = _strip_accents(team_name).lower().strip()
    # Quitar caracteres no alfanuméricos salvo espacios/guiones
    t = re.sub(r"[^a-z0-9\s\-]", "", t)
    t = re.sub(r"[\s_]+", "-", t)
    t = re.sub(r"-+", "-", t).strip("-")
    return t


def _slugify_player(name: str) -> str:
    """Convierte 'Gregor Kobel' → 'gregor-kobel'. Misma lógica que _slugify_team
    pero conserva intención de ser slug-de-jugador (separa para legibilidad)."""
    return _slugify_team(name)


# ──────────────────────────────────────────────────────────────────────────
# Migración tabla ff_probabilidades
# ──────────────────────────────────────────────────────────────────────────
async def _ensure_table(db: aiosqlite.Connection) -> None:
    await db.execute("""
        CREATE TABLE IF NOT EXISTS ff_probabilidades (
            player_id INTEGER PRIMARY KEY,
            slug TEXT,
            prob INTEGER,
            equipo TEXT,
            fecha_update TEXT
        )
    """)


# ──────────────────────────────────────────────────────────────────────────
# Fetch y parse de una página de equipo
# ──────────────────────────────────────────────────────────────────────────
async def _fetch_team(client: httpx.AsyncClient, slug: str) -> Optional[str]:
    url = BASE_URL.format(slug=slug)
    try:
        r = await client.get(url, headers={"User-Agent": USER_AGENT}, timeout=20.0,
                             follow_redirects=True)
        if r.status_code != 200:
            logger.warning(f"[futbolfantasy] {slug}: HTTP {r.status_code}")
            return None
        return r.text
    except Exception as e:
        logger.warning(f"[futbolfantasy] {slug}: {type(e).__name__}: {e}")
        return None


def _parse_team_html(html: str) -> list:
    """Devuelve lista de dicts: [{slug, prob, equipo}, ...]."""
    soup = BeautifulSoup(html, "html.parser")
    cams = soup.select('a.camiseta[href*="/jugadores/"][href*="/world-cup-2026"]')
    out = []
    for a in cams:
        href = a.get("href", "")
        m = HREF_PLAYER_RE.search(href)
        if not m:
            continue
        player_slug = m.group(1)
        equipo = a.get("data-equipo") or ""
        prob_raw = a.get("data-probabilidad") or ""
        pm = PROB_RE.search(str(prob_raw))
        if not pm:
            continue
        try:
            prob = int(pm.group(1))
        except ValueError:
            continue
        out.append({"slug": player_slug, "prob": prob, "equipo": equipo})
    return out


# ──────────────────────────────────────────────────────────────────────────
# Construir mapa slug → player_id desde jugadores_mundo
# ──────────────────────────────────────────────────────────────────────────
_INITIAL_RE = re.compile(r"^[A-Za-zÀ-ÿ]\.\s+(.+)$")


async def _build_player_index(db: aiosqlite.Connection) -> dict:
    """Construye varios índices para matching escalonado:
    - by_slug: slug completo del nombre
    - by_apellido_completo: apellido tras patrón "X. Apellido" (ej. "el-ouahdi")
    - by_last2: últimas 2 palabras unidas con guión (apellidos compuestos como "de-winter")
    - by_last:  última palabra (fallback más amplio)
    """
    db.row_factory = aiosqlite.Row
    async with db.execute(
        "SELECT id, name, team_name FROM jugadores_mundo WHERE name IS NOT NULL"
    ) as cur:
        rows = await cur.fetchall()

    by_slug: dict = {}
    by_apellido_completo: dict = {}
    by_last2: dict = {}
    by_last: dict = {}

    for r in rows:
        pid = r["id"]
        name = r["name"] or ""
        slug = _slugify_player(name)
        if slug:
            by_slug.setdefault(slug, []).append(pid)

        # Patrón "X. Apellido" → extraer apellido completo
        m = _INITIAL_RE.match(name.strip())
        if m:
            apellido_slug = _slugify_player(m.group(1))
            if apellido_slug:
                by_apellido_completo.setdefault(apellido_slug, []).append(pid)

        # Últimas 2 palabras (apellidos compuestos como "De Winter", "El Ouahdi")
        parts = slug.split("-") if slug else []
        if len(parts) >= 2:
            last2 = "-".join(parts[-2:])
            by_last2.setdefault(last2, []).append(pid)
        # Última palabra
        if len(parts) >= 1:
            by_last.setdefault(parts[-1], []).append(pid)

    return {
        "by_slug": by_slug,
        "by_apellido_completo": by_apellido_completo,
        "by_last2": by_last2,
        "by_last": by_last,
    }


def _match_player(entry_slug: str, entry_team: str, index: dict,
                  team_codes: dict) -> Optional[int]:
    """Devuelve player_id que mejor encaja con el slug FF, o None.

    Estrategia escalonada (de más estricta a más laxa):
      1. Slug exacto
      2. Apellido completo tras patrón "X." en jugadores_mundo
         (ej. FF: "zakaria-el-ouahdi" → buscar "el-ouahdi" entre los apellidos
         extraídos de nombres tipo "Z. El Ouahdi")
      3. Últimas 2 palabras del slug FF (apellidos compuestos)
         (ej. FF: "koni-de-winter" → buscar "de-winter")
      4. Última palabra del slug FF (fallback amplio)
    """
    by_slug = index["by_slug"]
    by_apellido_completo = index["by_apellido_completo"]
    by_last2 = index["by_last2"]
    by_last = index["by_last"]
    parts = entry_slug.split("-") if entry_slug else []

    # 1. Match exacto por slug completo
    candidates = by_slug.get(entry_slug, [])
    if len(candidates) >= 1:
        return candidates[0]

    # 2. ¿El slug FF coincide con algún apellido de tipo "X. Apellido"?
    #    Probamos varios sufijos del slug FF para encontrar el apellido.
    if len(parts) >= 2:
        for start in range(1, len(parts)):
            sufijo = "-".join(parts[start:])
            candidates = by_apellido_completo.get(sufijo, [])
            if len(candidates) == 1:
                return candidates[0]
            if len(candidates) > 1:
                return candidates[0]

    # 3. Últimas 2 palabras (apellido compuesto)
    if len(parts) >= 2:
        last2 = "-".join(parts[-2:])
        candidates = by_last2.get(last2, [])
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            return candidates[0]

    # 4. Última palabra (fallback más amplio — solo si es única)
    if len(parts) >= 1:
        candidates = by_last.get(parts[-1], [])
        if len(candidates) == 1:
            return candidates[0]
        # Con múltiples candidatos no podemos desambiguar sin más datos
    return None


# ──────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────
async def scrape_futbolfantasy(client: httpx.AsyncClient = None) -> dict:
    """Scrapea futbolfantasy.com y actualiza prob_futbol_fantasy + ff_probabilidades.

    El parámetro `client` se ignora (usamos uno propio con UA de navegador) y solo
    está para mantener compatibilidad con la firma esperada por run_all_scrapers.
    """
    try:
        # 1. Equipos únicos desde jugadores_mundo
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT DISTINCT team_name FROM jugadores_mundo "
                "WHERE team_name IS NOT NULL AND team_name != ''"
            ) as cur:
                team_rows = await cur.fetchall()
            equipos = [r["team_name"] for r in team_rows]

        if not equipos:
            await log_sync("futbolfantasy", "ok", "sin equipos en jugadores_mundo")
            return {"ok": True, "count": 0}

        # 2. team_name → slug
        slugs = {}
        for team in equipos:
            slug = TEAM_SLUG_OVERRIDES.get(team)
            if not slug:
                slug = _slugify_team(team)
                logger.info(f"[futbolfantasy] slug derivado: '{team}' → '{slug}'")
            slugs[team] = slug

        logger.info(f"[futbolfantasy] iniciando: {len(slugs)} equipos a scrappear")

        # 3. Fetch secuencial con rate limit 1s (cliente propio con UA navegador)
        all_entries = []  # [{team_name, slug, prob, equipo}]
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as own_client:
            for i, (team, slug) in enumerate(slugs.items(), 1):
                html = await _fetch_team(own_client, slug)
                if html is None:
                    logger.warning(f"[futbolfantasy] [{i}/{len(slugs)}] {team} ({slug}): sin HTML")
                else:
                    entries = _parse_team_html(html)
                    for e in entries:
                        e["team_name"] = team
                    all_entries.extend(entries)
                    logger.info(f"[futbolfantasy] [{i}/{len(slugs)}] {team} ({slug}): "
                                f"{len(entries)} jugadores parseados")
                # Rate limit (también después del último para no acoplar con siguiente scraper)
                await asyncio.sleep(1.0)

        if not all_entries:
            msg = "0 jugadores parseados (¿FF cambió el HTML?)"
            await log_sync("futbolfantasy", "error", msg)
            return {"ok": False, "error": msg}

        # 4. Construir índice de jugadores y matchear
        ahora = datetime.now().isoformat()
        async with aiosqlite.connect(DB_PATH) as db:
            await _ensure_table(db)
            index = await _build_player_index(db)

            # 5. Insertar/actualizar ff_probabilidades + recoger player_ids matched
            matched_player_ids = set()
            sin_match = 0
            for e in all_entries:
                pid = _match_player(e["slug"], e["equipo"], index, slugs)
                if pid is None:
                    sin_match += 1
                    continue
                matched_player_ids.add(pid)
                await db.execute("""
                    INSERT INTO ff_probabilidades (player_id, slug, prob, equipo, fecha_update)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(player_id) DO UPDATE SET
                        slug = excluded.slug,
                        prob = excluded.prob,
                        equipo = excluded.equipo,
                        fecha_update = excluded.fecha_update
                """, (pid, e["slug"], e["prob"], e["equipo"], ahora))

            # 6. Actualizar mi_plantilla.prob_futbol_fantasy desde ff_probabilidades
            await db.execute("""
                UPDATE mi_plantilla
                   SET prob_futbol_fantasy = (
                       SELECT prob FROM ff_probabilidades
                       WHERE ff_probabilidades.player_id = mi_plantilla.id
                   )
                 WHERE id IN (SELECT player_id FROM ff_probabilidades)
            """)

            # 6b. Recalcular prob_media combinando con prob_jornada
            from ._common import recalcular_prob_media
            await recalcular_prob_media(db)

            # Estadística de plantilla actualizada
            async with db.execute(
                "SELECT COUNT(*) FROM mi_plantilla WHERE prob_futbol_fantasy IS NOT NULL"
            ) as cur:
                row = await cur.fetchone()
                plantilla_con_prob = row[0] if row else 0
            async with db.execute("SELECT COUNT(*) FROM mi_plantilla") as cur:
                row = await cur.fetchone()
                plantilla_total = row[0] if row else 0

            await db.commit()

        msg = (
            f"{len(matched_player_ids)} matches en jugadores_mundo, "
            f"{sin_match} sin match (de {len(all_entries)} entradas FF) | "
            f"plantilla: {plantilla_con_prob}/{plantilla_total} con prob"
        )
        logger.info(f"[futbolfantasy] {msg}")
        await log_sync("futbolfantasy", "ok", msg)
        return {
            "ok": True,
            "count": len(matched_player_ids),
            "sin_match": sin_match,
            "ff_total": len(all_entries),
            "plantilla_con_prob": plantilla_con_prob,
            "plantilla_total": plantilla_total,
        }

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        logger.error(f"[futbolfantasy] {type(e).__name__}: {e}\n{tb}")
        msg = f"{type(e).__name__}: {e}" if str(e) else f"{type(e).__name__}: (sin mensaje)"
        await log_sync("futbolfantasy", "error", msg[:500])
        return {"ok": False, "error": msg}
