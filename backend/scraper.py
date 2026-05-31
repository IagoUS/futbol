# Módulo de scraping — 10 scrapers para la API de Biwenger
import asyncio
import json
import os
import sys
import httpx
import aiosqlite
import logging
from datetime import datetime, timedelta
from database import DB_PATH, log_sync, get_auth, save_auth

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Configuración
# ──────────────────────────────────────────────
COMPETITION = "world-cup"  # world-cup | laliga
DEFAULT_VERSION = "630"

BASE_URL = "https://biwenger.as.com/api/v2"
CF_BASE = "https://cf.biwenger.com/api/v2"

# Caché de credenciales en memoria (se carga de la BD al inicio de cada sync)
_auth_cache: dict = {}


def get_headers() -> dict:
    """Devuelve las cabeceras usando las credenciales del caché."""
    return {
        "Authorization": f"Bearer {_auth_cache.get('token', '')}",
        "x-league": str(_auth_cache.get("league_id", "")),
        "x-user": str(_auth_cache.get("user_id", "")),
        "x-version": _auth_cache.get("version", DEFAULT_VERSION),
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "x-lang": "es",
        "Referer": "https://biwenger.as.com/",
    }


async def load_auth_cache():
    """Carga las credenciales de la BD al caché de memoria."""
    global _auth_cache
    auth = await get_auth()
    if auth and auth.get("user_id") and auth.get("league_id"):
        _auth_cache = auth
        logger.info(f"Auth cargada: user={auth.get('user_id')}, league={auth.get('league_id')}")
    else:
        _auth_cache = {}
        if auth:
            logger.warning(
                f"Auth incompleta en BD (user={auth.get('user_id')}, "
                f"league={auth.get('league_id')}) — descartada, inicia sesión de nuevo"
            )
        else:
            logger.warning("No hay sesión activa en la BD")


async def _silent_relogin(client: httpx.AsyncClient) -> bool:
    """Intenta relogin silencioso cuando el token caduca (401)."""
    email = _auth_cache.get("email", "")
    password = _auth_cache.get("password", "")
    if not email or not password:
        auth = await get_auth()
        email = auth.get("email", "")
        password = auth.get("password", "")
    if not email or not password:
        logger.warning("Sin credenciales guardadas para relogin automático")
        return False
    try:
        await do_login(email, password, client)
        logger.info("Relogin automático exitoso")
        return True
    except Exception as e:
        logger.error(f"Relogin automático fallido: {e}")
        return False


async def _api_get(client: httpx.AsyncClient, url: str) -> httpx.Response:
    """GET con retry automático ante 401 (token caducado)."""
    r = await client.get(url, headers=get_headers())
    if r.status_code == 401:
        logger.warning(f"401 en {url} — relogin automático")
        if await _silent_relogin(client):
            r = await client.get(url, headers=get_headers())
    return r


async def do_login(email: str, password: str,
                   client: httpx.AsyncClient | None = None) -> dict:
    """Autentica con la API de Biwenger y actualiza las credenciales en BD y caché."""
    global _auth_cache
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=15.0)
    try:
        login_url = f"{BASE_URL}/auth/login"
        login_body = {"email": email, "password": password}
        login_headers = {
            "Content-Type": "application/json; charset=UTF-8",
            "x-lang": "es",
            "x-version": DEFAULT_VERSION,
        }
        logger.info(f"Login → POST {login_url} | body keys: {list(login_body.keys())}")
        r = await client.post(login_url, json=login_body, headers=login_headers)

        # Log completo de la respuesta para depuración
        logger.info(f"Login response | status={r.status_code}")
        logger.info(f"Login response | headers={dict(r.headers)}")
        try:
            logger.info(f"Login response | body={r.text[:2000]}")
        except Exception:
            pass

        if r.status_code in (400, 401, 403):
            body_preview = r.text[:500] if r.text else "(vacío)"
            raise ValueError(f"Credenciales incorrectas (HTTP {r.status_code}): {body_preview}")
        r.raise_for_status()
        data = r.json()
        logger.info(f"Login response | JSON keys top-level: {list(data.keys())}")
        if "data" in data:
            logger.info(f"Login response | JSON data keys: {list(data['data'].keys()) if isinstance(data['data'], dict) else type(data['data']).__name__}")

        # Login solo devuelve {"token": "..."} — extraer el token
        payload = data.get("data", data)
        token = (
            payload.get("token")
            or payload.get("satellizer_token")
            or payload.get("jwt")
            or payload.get("accessToken")
            or data.get("token", "")
            or data.get("satellizer_token", "")
        )
        if not token:
            raise ValueError(f"No se encontró token en la respuesta: {data}")
        logger.info(f"Token extraído correctamente (primeros 20 chars): {token[:20]}...")

        # GET /account para obtener user_id y leagues
        r_acc = await client.get(
            f"{BASE_URL}/account",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=UTF-8",
                "x-lang": "es",
                "x-version": DEFAULT_VERSION,
            },
        )
        logger.info(f"Account response | status={r_acc.status_code}")
        try:
            logger.info(f"Account response | body={r_acc.text[:2000]}")
        except Exception:
            pass
        r_acc.raise_for_status()
        acc_data = r_acc.json()
        logger.info(f"Account response | JSON keys: {list(acc_data.keys())}")

        acc = acc_data.get("data", acc_data)

        # data.account.id → ID de la cuenta Biwenger
        account = acc.get("account", {}) or {}
        account_id = account.get("id") or acc.get("id") or 0
        user_name = account.get("name") or account.get("username") or "Usuario"

        # Buscar liga world-cup; si no, usar la primera disponible
        leagues = acc.get("leagues", []) or []
        logger.info(f"Ligas disponibles: {[(l.get('id'), l.get('competition')) for l in leagues]}")
        target_league = next(
            (l for l in leagues if l.get("competition") == "world-cup"), None
        ) or (leagues[0] if leagues else None)

        league_id = target_league.get("id", 0) if target_league else 0
        # data.leagues[n].user.id → ID de usuario dentro de la liga (usado como x-user)
        league_user = (target_league.get("user", {}) or {}) if target_league else {}
        user_id = league_user.get("id") or account_id or 0

        logger.info(
            f"Account extraído: account_id={account_id}, user_id(x-user)={user_id}, "
            f"league_id={league_id}, competition={target_league.get('competition') if target_league else None}"
        )

        if not user_id:
            raise ValueError(f"GET /account no devolvió user_id. Respuesta completa: {acc_data}")
        if not league_id:
            raise ValueError(f"GET /account no devolvió leagues. Respuesta completa: {acc_data}")

        # Guardar en BD y actualizar caché
        await save_auth(email, password, token, user_id, league_id, user_name, DEFAULT_VERSION)
        _auth_cache = {
            "email": email,
            "password": password,
            "token": token,
            "user_id": user_id,
            "league_id": league_id,
            "user_name": user_name,
            "version": DEFAULT_VERSION,
        }
        logger.info(f"Login OK: {user_name} (user={user_id}, league={league_id})")
        return _auth_cache.copy()
    finally:
        if own_client:
            await client.aclose()

def ts() -> str:
    return datetime.now().isoformat()


def _posicion(pos_id) -> str:
    """Convierte el ID de posición al nombre legible."""
    mapa = {1: "Portero", 2: "Defensa", 3: "Centrocampista", 4: "Delantero", 5: "Entrenador"}
    return mapa.get(pos_id, str(pos_id))


# ──────────────────────────────────────────────
# Helper — Carga jugadores_mundo desde la BD
# ──────────────────────────────────────────────
async def _load_jugadores_mundo() -> dict:
    """Lee jugadores_mundo de la BD. Devuelve {id: row_dict}."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT id, name, slug, position, team_id, team_name, price, fantasy_price, "
                "points, fitness, status, status_info, price_increment, next_match_date, next_match_rival "
                "FROM jugadores_mundo"
            ) as cur:
                rows = await cur.fetchall()
        return {row["id"]: dict(row) for row in rows}
    except Exception as e:
        logger.warning(f"_load_jugadores_mundo error: {e}")
        return {}


# ──────────────────────────────────────────────
# Helper — Catálogo completo de jugadores (CF)
# ──────────────────────────────────────────────
async def _fetch_cf_players(client: httpx.AsyncClient) -> tuple[dict, dict]:
    """Descarga el catálogo completo de jugadores desde cf.biwenger.com.
    Devuelve (catalogue {player_id: player_dict}, teams {team_id: team_dict})."""
    _cf_headers = {
        "Referer": "https://biwenger.as.com/",
        "Origin": "https://biwenger.as.com",
        "x-lang": "es",
    }
    _candidates = [
        f"{CF_BASE}/competitions/{COMPETITION}/data?score=2&lang=es",
        f"{CF_BASE}/competitions/{COMPETITION}/data?lang=es&score=2",
        f"{CF_BASE}/competitions/{COMPETITION}/data?lang=es",
        f"{CF_BASE}/competitions/{COMPETITION}/players?lang=es&score=2&fields=id,name,slug,position,teamID,team,price,points,fitness",
    ]
    for url in _candidates:
        try:
            r = await client.get(url, headers=_cf_headers)
            logger.info(f"CF intento | url={url} | status={r.status_code} | body={r.text[:300]}")
            if r.status_code == 200:
                body = r.json()
                data_node = body.get("data", {})
                # teams: puede ser dict {id: team} o lista
                teams_raw = data_node.get("teams", {}) if isinstance(data_node, dict) else {}
                teams: dict = {}
                if isinstance(teams_raw, dict):
                    teams = {int(k): v for k, v in teams_raw.items()}
                elif isinstance(teams_raw, list):
                    teams = {t["id"]: t for t in teams_raw if isinstance(t, dict) and t.get("id")}
                # players
                raw = (
                    data_node.get("players", []) if isinstance(data_node, dict) else []
                    or body.get("data", [])
                    or []
                )
                if isinstance(raw, dict):
                    raw = list(raw.values())
                catalogue = {p["id"]: p for p in raw if isinstance(p, dict) and p.get("id")}
                if catalogue:
                    logger.info(f"CF catálogo OK: {len(catalogue)} jugadores, {len(teams)} equipos desde {url}")
                    return catalogue, teams
                logger.warning(f"CF 200 pero sin jugadores en {url} | keys={list(data_node.keys()) if isinstance(data_node, dict) else '?'}")
        except Exception as e:
            logger.warning(f"CF error en {url}: {e}")
    logger.error("CF catálogo: ningún endpoint funcionó")
    return {}, {}


# ──────────────────────────────────────────────
# SCRAPER 0 — Jugadores del Mundo (catálogo CF)
# ──────────────────────────────────────────────
async def scrape_jugadores_mundo(client: httpx.AsyncClient) -> dict:
    """Descarga catálogo completo de jugadores desde CF y los guarda en jugadores_mundo."""
    try:
        catalogue, teams = await _fetch_cf_players(client)
        if not catalogue:
            await log_sync("jugadores_mundo", "error", "CF catálogo vacío o 403")
            return {"ok": False, "error": "CF catálogo vacío"}

        now = ts()
        lesionados = 0
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM jugadores_mundo")
            for jid, p in catalogue.items():
                # team
                team_id = p.get("teamID") or p.get("teamId")
                team_obj = teams.get(int(team_id), {}) if team_id else {}
                team_name = team_obj.get("name", "") or ""

                # next match from team
                next_games = team_obj.get("nextGames", []) or []
                next_match_date = None
                next_match_rival = None
                if next_games:
                    g = next_games[0]
                    next_match_date = g.get("date")  # Unix timestamp
                    home_id = (g.get("home") or {}).get("id")
                    away_id = (g.get("away") or {}).get("id")
                    rival_id = away_id if home_id == team_id else home_id
                    rival_obj = teams.get(int(rival_id), {}) if rival_id else {}
                    next_match_rival = rival_obj.get("name", str(rival_id))

                # points
                pts_raw = p.get("points")
                if isinstance(pts_raw, dict) and pts_raw:
                    pts = list(pts_raw.values())[-1]
                elif isinstance(pts_raw, (int, float)):
                    pts = int(pts_raw)
                else:
                    pts = 0

                # fitness (legacy list field — keep as JSON string)
                fit_raw = p.get("fitness")
                fit = json.dumps(fit_raw) if isinstance(fit_raw, list) else (str(fit_raw) if fit_raw else "[]")

                # status / injury
                status = p.get("status", "ok") or "ok"
                status_info = p.get("statusInfo") or None
                if status != "ok":
                    lesionados += 1

                price_increment = p.get("priceIncrement", 0) or 0

                await db.execute("""
                    INSERT OR REPLACE INTO jugadores_mundo
                    (id, name, slug, position, team_id, team_name, price, fantasy_price,
                     points, fitness, status, status_info, price_increment,
                     next_match_date, next_match_rival, actualizado)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    jid, p.get("name", ""), p.get("slug", ""),
                    _posicion(p.get("position", 0)),
                    team_id, team_name,
                    p.get("price", 0) or 0,
                    p.get("fantasyPrice", 0) or 0,
                    pts, fit,
                    status, status_info, price_increment,
                    next_match_date, next_match_rival,
                    now
                ))
            await db.commit()

        msg = f"{len(catalogue)} jugadores ({lesionados} con dudas/lesiones)"
        await log_sync("jugadores_mundo", "✓", msg)
        logger.info(f"jugadores_mundo: {msg}")
        return {"ok": True, "count": len(catalogue), "lesionados": lesionados}

    except Exception as e:
        logger.exception("scrape_jugadores_mundo error")
        await log_sync("jugadores_mundo", "error", str(e))
        return {"ok": False, "error": str(e)}


# ──────────────────────────────────────────────
# SCRAPER 1 — Mi Plantilla
# ──────────────────────────────────────────────
async def scrape_mi_plantilla(client: httpx.AsyncClient) -> dict:
    try:
        _url = (
            f"{BASE_URL}/user"
            "?fields=*,lineup(type,playersID,reservesID,captain,striker,coach,date)"
            ",players(id,owner),market,offers,-trophies"
        )
        r = await client.get(_url, headers={**get_headers(), "x-user": str(_auth_cache.get("user_id", ""))})
        if r.status_code == 401:
            if await _silent_relogin(client):
                r = await client.get(_url, headers={**get_headers(), "x-user": str(_auth_cache.get("user_id", ""))})
        r.raise_for_status()
        data = r.json()
        user_data = data.get("data", {})
        logger.info(f"mi_plantilla response keys: {list(user_data.keys()) if isinstance(user_data, dict) else type(user_data)}")

        # Cruzar IDs con jugadores_mundo (poblado previamente por scrape_jugadores_mundo)
        jugadores_mundo = await _load_jugadores_mundo()
        logger.info(f"jugadores_mundo cargados: {len(jugadores_mundo)}")

        jugadores = []
        # API devuelve data.players = [{id, owner:{date,price}}, ...]
        players_raw = user_data.get("players", []) or []
        logger.info(f"mi_plantilla: {len(players_raw)} IDs | sample={str(players_raw[:3])[:200]}")

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM mi_plantilla")
            for p in players_raw:
                pid = p.get("id")
                owner = p.get("owner", {}) or {}
                precio_compra = (owner.get("price") if isinstance(owner, dict) else 0) or 0

                jm = jugadores_mundo.get(pid, {})
                nombre = jm.get("name") or f"Jugador {pid}"
                posicion = jm.get("position", "")
                equipo = str(jm.get("team_id") or "")
                precio_actual = jm.get("price", 0) or 0
                slug = jm.get("slug", "")
                roi = precio_actual - precio_compra

                puntos_totales = jm.get("points", 0) or 0
                puntos_5j_str = str(puntos_totales)
                estado_str = jm.get("fitness", "ok") or "ok"

                jugadores.append({"id": pid, "nombre": nombre, "posicion": posicion,
                                  "equipo": equipo, "precio_actual": precio_actual,
                                  "precio_compra": precio_compra, "roi": roi,
                                  "puntos_totales": puntos_totales, "puntos_5j": puntos_5j_str,
                                  "estado": estado_str, "slug": slug})
                await db.execute("""
                    INSERT OR REPLACE INTO mi_plantilla
                    (id, nombre, posicion, equipo, precio_actual, precio_compra, roi,
                     puntos_totales, puntos_5j, estado, slug, actualizado)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    pid, nombre, posicion, equipo,
                    precio_actual, precio_compra, roi, puntos_totales,
                    puntos_5j_str, estado_str, slug, ts()
                ))
            await db.commit()

        await log_sync("mi_plantilla", "ok", f"{len(jugadores)} jugadores guardados")
        return {"ok": True, "count": len(jugadores)}

    except httpx.HTTPStatusError as e:
        msg = "Token caducado" if e.response.status_code == 401 else str(e)
        await log_sync("mi_plantilla", "error", msg)
        return {"ok": False, "error": msg, "status": e.response.status_code}
    except Exception as e:
        await log_sync("mi_plantilla", "error", str(e))
        return {"ok": False, "error": str(e)}


# ──────────────────────────────────────────────
# SCRAPER 2 — Mercado de Fichajes
# ──────────────────────────────────────────────
async def scrape_mercado(client: httpx.AsyncClient) -> dict:
    try:
        jugadores_mundo = await _load_jugadores_mundo()

        r = await _api_get(client, f"{BASE_URL}/market")
        r.raise_for_status()
        data = r.json()
        raw = data.get("data", data)
        # API devuelve data.sales = [{price, player:{id}, user, until}, ...]
        ventas = (raw.get("sales", []) if isinstance(raw, dict) else raw) or []
        logger.info(f"mercado: {len(ventas)} en venta | sample={str(ventas[:2])[:200]}")

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM mercado")
            for item in ventas:
                player_obj = item.get("player", {}) or {}
                pid = player_obj.get("id") if isinstance(player_obj, dict) else player_obj
                precio = item.get("price", 0) or 0

                # user_id del vendedor (puede ser dict {id, name} o int)
                user_obj = item.get("user")
                if isinstance(user_obj, dict):
                    seller_id = user_obj.get("id")
                else:
                    seller_id = user_obj

                jm = jugadores_mundo.get(pid, {})
                nombre = jm.get("name") or f"Jugador {pid}"
                posicion = jm.get("position", "")
                equipo = str(jm.get("team_id") or "")

                puntos_uj = jm.get("points", 0) or 0
                price_increment = jm.get("price_increment", 0) or 0
                status = jm.get("status", "ok") or "ok"
                next_match_date = jm.get("next_match_date")

                score = 0
                if price_increment > 0:    score += 30
                if status == "ok":         score += 20
                if next_match_date:        score += 20
                if precio < 1_000_000:     score += 30   # especulación
                elif precio > 10_000_000:  score += 20   # estrella
                elif precio > 5_000_000:   score += 10   # jugador bueno

                await db.execute("""
                    INSERT OR REPLACE INTO mercado
                    (id, nombre, posicion, equipo, precio, puntos_ultima_jornada, tendencia, score_oportunidad, user_id, actualizado)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (pid, nombre, posicion, equipo, precio, puntos_uj, price_increment, score, seller_id, ts()))
            await db.commit()

        await log_sync("mercado", "ok", f"{len(ventas)} jugadores guardados")
        return {"ok": True, "count": len(ventas)}

    except httpx.HTTPStatusError as e:
        msg = "Token caducado" if e.response.status_code == 401 else str(e)
        await log_sync("mercado", "error", msg)
        return {"ok": False, "error": msg, "status": e.response.status_code}
    except Exception as e:
        await log_sync("mercado", "error", str(e))
        return {"ok": False, "error": str(e)}


# ──────────────────────────────────────────────
# SCRAPER 3 — Saldo y Finanzas
# ──────────────────────────────────────────────
async def scrape_finanzas(client: httpx.AsyncClient) -> dict:
    try:
        _league_url = (
            f"{BASE_URL}/league"
            "?include=all,-lastAccess"
            "&fields=*,standings,tournaments,group,settings(description)"
        )
        r = await _api_get(client, _league_url)
        r.raise_for_status()
        league_data = r.json().get("data", {})
        logger.info(f"finanzas league keys: {list(league_data.keys()) if isinstance(league_data, dict) else type(league_data)}")

        presupuesto_inicial = league_data.get("budget", 0) or 0

        # Valor de plantilla desde standings
        standings = league_data.get("standings", []) or []
        my_uid = str(_auth_cache.get("user_id", ""))
        my_row = next(
            (s for s in standings if str(s.get("id", "")) == my_uid),
            standings[0] if standings else {}
        )
        valor_plantilla = my_row.get("teamValue", 0) or 0
        transfers = my_row.get("transfers", {}) or {}
        dinero_gastado = transfers.get("spent", 0) or 0
        dinero_ingresado = transfers.get("earned", 0) or 0

        # Saldo real desde /user (data.balance)
        _user_url = f"{BASE_URL}/user?fields=balance"
        r_user = await client.get(
            _user_url,
            headers={**get_headers(), "x-user": str(_auth_cache.get("user_id", ""))}
        )
        saldo = 0
        if r_user.status_code == 200:
            saldo = r_user.json().get("data", {}).get("balance", 0) or 0

        # Puja máxima desde /market?status=sold (data.status.maximumBid)
        # Biwenger usa este valor (no el saldo bruto) para validar pujas: tiene
        # en cuenta pujas pendientes, valor de protección de plantilla mínima, etc.
        maximum_bid = None
        try:
            r_mkt = await _api_get(client, f"{BASE_URL}/market?status=sold")
            if r_mkt.status_code == 200:
                status_info = r_mkt.json().get("data", {}).get("status", {}) or {}
                maximum_bid = status_info.get("maximumBid")
                # balance del market también puede sobreescribir el de /user si
                # difiere; mantenemos el de /user como saldo principal y
                # registramos el otro como referencia en log.
                logger.info(
                    f"finanzas market.status balance={status_info.get('balance')} "
                    f"maximumBid={maximum_bid}"
                )
        except Exception as e:
            logger.warning(f"finanzas: no se pudo leer /market?status=sold: {e}")

        logger.info(
            f"finanzas saldo={saldo} valor_plantilla={valor_plantilla} "
            f"maximum_bid={maximum_bid}"
        )

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM finanzas")
            await db.execute("""
                INSERT INTO finanzas
                (saldo, valor_plantilla, dinero_gastado, dinero_ingresado,
                 presupuesto_inicial, maximum_bid, actualizado)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (saldo, valor_plantilla, dinero_gastado, dinero_ingresado,
                  presupuesto_inicial, maximum_bid, ts()))
            await db.commit()

        await log_sync(
            "finanzas", "ok",
            f"Saldo: {saldo}, Valor: {valor_plantilla}, MaxBid: {maximum_bid}"
        )
        return {"ok": True, "saldo": saldo, "maximum_bid": maximum_bid}

    except httpx.HTTPStatusError as e:
        msg = "Token caducado" if e.response.status_code == 401 else str(e)
        await log_sync("finanzas", "error", msg)
        return {"ok": False, "error": msg, "status": e.response.status_code}
    except Exception as e:
        await log_sync("finanzas", "error", str(e))
        return {"ok": False, "error": str(e)}


# ──────────────────────────────────────────────
# SCRAPER 4 — Movimientos de Rivales
# ──────────────────────────────────────────────
async def scrape_movimientos_rivales(client: httpx.AsyncClient) -> dict:
    try:
        r = await _api_get(client, f"{BASE_URL}/home")
        logger.info(f"/home | status={r.status_code} | body={r.text[:3000]}")
        r.raise_for_status()
        data = r.json()

        board = data.get("data", {}).get("league", {}).get("board", []) or []
        logger.info(f"/home board items: {len(board)}, types: {list({i.get('type') for i in board})}")

        transferencias = [i for i in board if i.get("type") in ("transfer", "market")]

        jugadores_mundo = await _load_jugadores_mundo()

        async with aiosqlite.connect(DB_PATH) as db:
            # ── NO DELETE: usamos INSERT OR IGNORE + índice UNIQUE para
            # preservar movimientos históricos que ya no aparecen en /home.
            count_new = 0
            count_seen = 0
            for t in transferencias:
                board_type = t.get("type", "unknown")  # 'transfer' | 'market'
                fecha = t.get("date", ts())
                content = t.get("content", [])
                if isinstance(content, dict):
                    content = [content]
                for item in content:
                    jugador_id = item.get("player")
                    if isinstance(jugador_id, dict):
                        jugador_id = jugador_id.get("id")
                    jm = jugadores_mundo.get(jugador_id, {})
                    jugador_nombre = jm.get("name") or f"Jugador {jugador_id}"

                    to_user = item.get("to", {}) or {}
                    from_user = item.get("from", {}) or {}
                    precio = item.get("amount", 0) or 0

                    # Generar una fila por cada lado del movimiento:
                    #   - to_user (recibe el jugador)  → tipo='COMPRA'
                    #   - from_user (cede el jugador) → tipo='VENTA'
                    # En el tipo 'market' (fichaje libre) normalmente solo hay to_user
                    # (el mercado libre cede). En 'transfer' suelen estar ambos.
                    sides = []
                    if to_user.get("id"):
                        sides.append(("COMPRA", to_user.get("id"), to_user.get("name", "")))
                    if from_user.get("id"):
                        sides.append(("VENTA", from_user.get("id"), from_user.get("name", "")))
                    # Fallback: si no hay ningún lado identificable, descartar
                    if not sides:
                        continue

                    for tipo, uid, uname in sides:
                        count_seen += 1
                        cur = await db.execute("""
                            INSERT OR IGNORE INTO movimientos_rivales
                            (usuario_nombre, usuario_id, tipo, jugador_nombre,
                             jugador_id, precio, fecha, actualizado)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            uname, uid, tipo,
                            jugador_nombre, jugador_id,
                            precio, str(fecha), ts()
                        ))
                        if cur.rowcount and cur.rowcount > 0:
                            count_new += 1
            await db.commit()

        await log_sync(
            "movimientos_rivales", "ok",
            f"{count_new} nuevos / {count_seen} vistos (resto ya existía)"
        )
        return {"ok": True, "count": count_new, "seen": count_seen}

    except httpx.HTTPStatusError as e:
        msg = "Token caducado" if e.response.status_code == 401 else str(e)
        await log_sync("movimientos_rivales", "error", msg)
        return {"ok": False, "error": msg, "status": e.response.status_code}
    except Exception as e:
        await log_sync("movimientos_rivales", "error", str(e))
        return {"ok": False, "error": str(e)}


# ──────────────────────────────────────────────
# SCRAPER 5 — Clasificación de la Liga
# ──────────────────────────────────────────────
async def scrape_clasificacion(client: httpx.AsyncClient) -> dict:
    try:
        _league_url = (
            f"{BASE_URL}/league"
            "?include=all,-lastAccess"
            "&fields=*,standings,tournaments,group,settings(description)"
        )
        r = await _api_get(client, _league_url)
        r.raise_for_status()
        league_data = r.json().get("data", {})

        standings = league_data.get("standings", []) or []

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM clasificacion")
            for i, entry in enumerate(standings):
                # data.standings es plano: {id, name, points, teamValue, position}
                posicion = entry.get("position", i + 1)
                await db.execute("""
                    INSERT OR REPLACE INTO clasificacion
                    (id, posicion, nombre, puntos_totales, puntos_ultima_jornada, valor_plantilla, actualizado)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    entry.get("id", i), posicion, entry.get("name", ""),
                    entry.get("points", 0) or 0,
                    entry.get("lastRoundPoints", entry.get("roundPoints", 0)) or 0,
                    entry.get("teamValue", 0) or 0, ts()
                ))
            await db.commit()

        await log_sync("clasificacion", "ok", f"{len(standings)} equipos guardados")
        return {"ok": True, "count": len(standings)}

    except httpx.HTTPStatusError as e:
        msg = "Token caducado" if e.response.status_code == 401 else str(e)
        await log_sync("clasificacion", "error", msg)
        return {"ok": False, "error": msg, "status": e.response.status_code}
    except Exception as e:
        await log_sync("clasificacion", "error", str(e))
        return {"ok": False, "error": str(e)}


# ──────────────────────────────────────────────
# SCRAPER 6 — Plantillas de Rivales
# ──────────────────────────────────────────────
async def scrape_plantillas_rivales(client: httpx.AsyncClient) -> dict:
    try:
        # Obtener lista de usuarios de la liga
        r = await _api_get(client, f"{BASE_URL}/league")
        r.raise_for_status()
        league_data = r.json().get("data", {})
        users = league_data.get("users", []) or []

        total = 0
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM plantillas_rivales")
            for u in users:
                uid = u.get("id")
                uname = u.get("name", "")
                if str(uid) == str(_auth_cache.get("user_id", "")):
                    continue  # Saltar mi propio equipo
                try:
                    r2 = await _api_get(client, f"{BASE_URL}/league/users/{uid}/team")
                    if r2.status_code != 200:
                        continue
                    team_data = r2.json().get("data", {})
                    players = team_data.get("players", [])
                    for p in players:
                        pi = p.get("player", p)
                        await db.execute("""
                            INSERT INTO plantillas_rivales
                            (usuario_id, usuario_nombre, jugador_id, jugador_nombre, jugador_posicion, actualizado)
                            VALUES (?, ?, ?, ?, ?, ?)
                        """, (
                            uid, uname, pi.get("id"), pi.get("name", ""),
                            _posicion(pi.get("position", 0)), ts()
                        ))
                        total += 1
                except Exception:
                    continue
            await db.commit()

        await log_sync("plantillas_rivales", "ok", f"{total} entradas guardadas")
        return {"ok": True, "count": total}

    except httpx.HTTPStatusError as e:
        msg = "Token caducado" if e.response.status_code == 401 else str(e)
        await log_sync("plantillas_rivales", "error", msg)
        return {"ok": False, "error": msg, "status": e.response.status_code}
    except Exception as e:
        await log_sync("plantillas_rivales", "error", str(e))
        return {"ok": False, "error": str(e)}


# ──────────────────────────────────────────────
# SCRAPER 7 — Calendario de Partidos
# ──────────────────────────────────────────────
async def scrape_calendario(client: httpx.AsyncClient) -> dict:
    try:
        r = await _api_get(client, f"{BASE_URL}/rounds/league")
        r.raise_for_status()
        data = r.json()
        raw = data.get("data", data)
        logger.info(f"calendario /rounds/league type={type(raw).__name__}, sample={str(raw)[:300]}")

        # La respuesta puede ser lista de jornadas o dict con 'rounds'
        if isinstance(raw, list):
            rounds = raw
        else:
            rounds = raw.get("rounds", raw.get("data", []))

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM calendario")
            count = 0
            for rnd in rounds:
                jornada = rnd.get("number", rnd.get("round", rnd.get("id", 0)))
                matches = rnd.get("matches", rnd.get("games", []))
                for m in matches:
                    home = (m.get("home") or m.get("localTeam") or {}).get("name", "")
                    away = (m.get("away") or m.get("visitorTeam") or {}).get("name", "")
                    fecha = m.get("date", m.get("kickoff", ""))
                    await db.execute("""
                        INSERT INTO calendario
                        (equipo, jornada, rival, localidad, fecha, dificultad, actualizado)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (home, jornada, away, "casa", str(fecha), 5, ts()))
                    await db.execute("""
                        INSERT INTO calendario
                        (equipo, jornada, rival, localidad, fecha, dificultad, actualizado)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (away, jornada, home, "fuera", str(fecha), 5, ts()))
                    count += 2
            await db.commit()

        await log_sync("calendario", "ok", f"{count} partidos guardados")
        return {"ok": True, "count": count}

    except httpx.HTTPStatusError as e:
        msg = "Token caducado" if e.response.status_code == 401 else str(e)
        await log_sync("calendario", "error", msg)
        return {"ok": False, "error": msg, "status": e.response.status_code}
    except Exception as e:
        await log_sync("calendario", "error", str(e))
        return {"ok": False, "error": str(e)}


# ──────────────────────────────────────────────
# SCRAPER 8 — Probabilidad de Titularidad (Gemini Search Grounding)
# ──────────────────────────────────────────────
def _parse_gemini_json(text: str) -> dict:
    """Extrae el primer bloque JSON válido de la respuesta de Gemini."""
    import json, re as _re
    # Strip markdown code fences
    text = _re.sub(r"```(?:json)?", "", text).strip().rstrip("`").strip()
    try:
        return json.loads(text)
    except Exception:
        match = _re.search(r"\{[\s\S]*\}", text)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                pass
    return {}


async def _scrape_prob_titularidad_bg() -> None:
    """Background task: consulta probabilidad de titular vía Gemini para cada jugador."""
    from ai_advisor import llamar_gemini
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT m.id, m.nombre, m.posicion,
                          COALESCE(j.team_name, m.equipo) AS pais,
                          m.prob_media
                   FROM mi_plantilla m
                   LEFT JOIN jugadores_mundo j ON m.id = j.id
                   WHERE m.prob_media IS NULL
                   ORDER BY m.id"""
            ) as cur:
                jugadores = await cur.fetchall()

        total = 0
        for j in jugadores:
            jid = j["id"]
            nombre = j["nombre"] or "?"
            posicion = j["posicion"] or "?"
            pais = j["pais"] or "?"
            try:
                prompt = f"""Jugador: {nombre}, {posicion}, selección: {pais}
Mundial 2026. Busca en estas webs ESPECÍFICAMENTE:
- mundofantasy.es
- biwenger.as.com (noticias del jugador)
- marca.com/futbol/mundial
- as.com/mundial
- sofascore.com

Busca la probabilidad de que este jugador sea titular en el Mundial 2026.
Si no encuentras dato en alguna web devuelve null.

Devuelve SOLO este JSON sin texto adicional:
{{
  "mundofantasy": null,
  "biwenger_as": null,
  "marca": null,
  "media": null,
  "rol": "titular/rotacion/suplente",
  "fuentes": {{
    "mundofantasy": null,
    "biwenger_as": null,
    "marca": null
  }}
}}
La media es el promedio de los valores no-null."""

                respuesta = await llamar_gemini(prompt)
                datos = _parse_gemini_json(respuesta)

                mundof = datos.get("mundofantasy")
                biw_as = datos.get("biwenger_as")
                marca_v = datos.get("marca")
                rol = datos.get("rol", "rotacion")

                valores = [v for v in [mundof, biw_as, marca_v] if v is not None]
                media = datos.get("media") or (round(sum(valores) / len(valores)) if valores else None)

                # Fallback sin grounding si todas las fuentes devolvieron null
                if media is None:
                    from ai_advisor import llamar_gemini_sin_grounding
                    fallback_prompt = (
                        f"Jugador: {nombre}, {posicion}, selección: {pais}\n"
                        "Mundial 2026. Basándote en tu conocimiento del jugador, "
                        "estima su probabilidad de ser titular (0-100) y su rol "
                        "(titular/rotacion/suplente). Solo el JSON, sin búsqueda web.\n"
                        "{\"media\": null, \"rol\": \"rotacion\"}"
                    )
                    fb_raw = await llamar_gemini_sin_grounding(fallback_prompt)
                    fb = _parse_gemini_json(fb_raw)
                    media = fb.get("media")
                    rol = fb.get("rol", rol)
                    logger.info(f"[prob_titularidad_bg] {nombre}: fallback sin grounding → media={media} rol={rol}")

                prob_legacy = media or 50

                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute(
                        """UPDATE mi_plantilla
                           SET prob_analitica = ?, prob_jornada = ?,
                               prob_futbol_fantasy = COALESCE(prob_futbol_fantasy, ?),
                               prob_media = ?,
                               rol_esperado = ?, prob_titularidad = ?
                           WHERE id = ?""",
                        (mundof, biw_as, marca_v, media, rol, prob_legacy, jid)
                    )
                    await db.commit()
                total += 1
                logger.info(f"[prob_titularidad_bg] {nombre}: mundof={mundof} biw_as={biw_as} marca={marca_v} media={media} rol={rol}")
            except Exception as e:
                logger.warning(f"[prob_titularidad_bg] Error para {nombre}: {e}")
                continue
            await asyncio.sleep(2)

        await log_sync("prob_titularidad", "ok", f"[bg] {total} jugadores actualizados")
    except Exception as e:
        logger.error(f"[prob_titularidad_bg] Error general: {e}")
        await log_sync("prob_titularidad", "error", str(e))


async def scrape_prob_titularidad(client: httpx.AsyncClient) -> dict:
    """Lanza la actualización de probabilidad en background y devuelve ✓ inmediatamente."""
    asyncio.create_task(_scrape_prob_titularidad_bg())
    return {"ok": True, "count": 0, "mensaje": "procesando en background"}


# ──────────────────────────────────────────────
# SCRAPER 10b — Proyecciones de Rendimiento (apuestas + analistas)
# ──────────────────────────────────────────────
async def _scrape_proyecciones_bg() -> None:
    """Background task: obtiene proyección de rendimiento vía Gemini para cada jugador."""
    from ai_advisor import llamar_gemini
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cutoff = (datetime.now() - timedelta(hours=24)).isoformat()
            async with db.execute(
                """SELECT m.id, m.nombre, m.posicion,
                          COALESCE(j.team_name, m.equipo) AS pais
                   FROM mi_plantilla m
                   LEFT JOIN jugadores_mundo j ON m.id = j.id
                   LEFT JOIN proyecciones_jugador p ON m.id = p.player_id
                   WHERE p.player_id IS NULL
                      OR p.fecha_actualizacion < ?
                   ORDER BY m.id""",
                (cutoff,)
            ) as cur:
                jugadores = await cur.fetchall()

        total_objetivo = len(jugadores)
        con_datos = 0  # Gemini devolvió al menos un campo útil
        vacios = 0     # Gemini respondió pero sin datos parseables
        errores = 0    # excepción durante el procesado
        logger.info(f"[proyecciones_bg] iniciando: {total_objetivo} jugadores a procesar")
        for idx, j in enumerate(jugadores, 1):
            jid = j["id"]
            nombre = j["nombre"] or "?"
            posicion = j["posicion"] or "?"
            pais = j["pais"] or "?"
            try:
                prompt = f"""Jugador: {nombre}, {posicion}, selección: {pais}
Mundial 2026.

Este jugador YA está en mi plantilla. La recomendación debe ser MANTENER o VENDER, nunca COMPRAR.

Busca en casas de apuestas (Bet365, William Hill, Betfair, Bwin o similar) y en webs especializadas:

1. Cuota para marcar gol en el torneo
2. Cuota para dar asistencia en el torneo
3. Cuota para ser máximo goleador
4. Minutos esperados por partido (si lo encuentras)
5. Valoración general del jugador para el Mundial según analistas deportivos

Convierte las cuotas en probabilidad implícita (prob = 1/cuota × 100).

Devuelve SOLO este JSON:
{{
  "prob_gol_torneo": null,
  "prob_asistencia_torneo": null,
  "minutos_esperados": null,
  "valoracion_mundial": "alta/media/baja",
  "recomendacion": "mantener/vender",
  "justificacion": "max 2 frases",
  "fuente_apuestas": null
}}"""

                respuesta = await llamar_gemini(prompt)
                datos = _parse_gemini_json(respuesta)

                ahora = datetime.now().isoformat()
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute(
                        """INSERT INTO proyecciones_jugador
                             (player_id, player_name, prob_gol, prob_asistencia,
                              minutos_esperados, valoracion_mundial, recomendacion,
                              justificacion, fuente, fecha_actualizacion)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                           ON CONFLICT(player_id) DO UPDATE SET
                             player_name=excluded.player_name,
                             prob_gol=excluded.prob_gol,
                             prob_asistencia=excluded.prob_asistencia,
                             minutos_esperados=excluded.minutos_esperados,
                             valoracion_mundial=excluded.valoracion_mundial,
                             recomendacion=excluded.recomendacion,
                             justificacion=excluded.justificacion,
                             fuente=excluded.fuente,
                             fecha_actualizacion=excluded.fecha_actualizacion""",
                        (jid, nombre,
                         datos.get("prob_gol_torneo"), datos.get("prob_asistencia_torneo"),
                         datos.get("minutos_esperados"), datos.get("valoracion_mundial"),
                         datos.get("recomendacion"), datos.get("justificacion"),
                         datos.get("fuente_apuestas"), ahora)
                    )
                    await db.commit()

                # Clasificar resultado: tiene datos útiles si al menos uno de los
                # campos clave no es None
                tiene_datos = any(
                    datos.get(k) is not None
                    for k in ("prob_gol_torneo", "prob_asistencia_torneo",
                              "minutos_esperados", "valoracion_mundial", "recomendacion")
                )
                if tiene_datos:
                    con_datos += 1
                else:
                    vacios += 1
                logger.info(
                    f"[proyecciones_bg] [{idx}/{total_objetivo}] {nombre}: "
                    f"gol={datos.get('prob_gol_torneo')} asist={datos.get('prob_asistencia_torneo')} "
                    f"val={datos.get('valoracion_mundial')} reco={datos.get('recomendacion')}"
                )
            except Exception as e:
                errores += 1
                logger.warning(
                    f"[proyecciones_bg] [{idx}/{total_objetivo}] {nombre}: "
                    f"{type(e).__name__}: {e} — continuando con el siguiente"
                )
                # No interrumpir; ir al siguiente jugador
            # Pausa entre jugadores para no saturar Gemini (también tras errores)
            try:
                await asyncio.sleep(2)
            except Exception:
                pass

        resumen = (
            f"Proyecciones completadas: {con_datos}/{total_objetivo} "
            f"(vacíos: {vacios}, errores: {errores})"
        )
        logger.info(f"[proyecciones_bg] {resumen}")
        await log_sync("proyecciones", "ok", resumen)
    except Exception as e:
        logger.exception("[proyecciones_bg] Error general (interrupción del proceso)")
        await log_sync("proyecciones", "error", f"{type(e).__name__}: {e}")


async def scrape_proyecciones(client: httpx.AsyncClient) -> dict:
    """Lanza la actualización de proyecciones en background y devuelve ✓ inmediatamente."""
    asyncio.create_task(_scrape_proyecciones_bg())
    return {"ok": True, "count": 0, "mensaje": "procesando en background"}


# ──────────────────────────────────────────────
# SCRAPER 9 — Historial de Precios
# ──────────────────────────────────────────────
async def scrape_historial_precios(client: httpx.AsyncClient) -> dict:
    """Snapshot diario de precios y tendencias desde jugadores_mundo (sin llamadas CF individuales)."""
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row

            # Jugadores de mi plantilla + top mercado
            async with db.execute("""
                SELECT j.id, j.name, j.price, j.price_increment
                FROM jugadores_mundo j
                WHERE j.id IN (
                    SELECT id FROM mi_plantilla
                    UNION
                    SELECT id FROM (SELECT id FROM mercado ORDER BY score_oportunidad DESC LIMIT 30)
                )
            """) as c:
                jugadores = await c.fetchall()

            # Evitar duplicados del mismo día
            async with db.execute(
                "SELECT player_id FROM historial_precios WHERE fecha = ?", (today,)
            ) as c:
                ya_registrados = {r["player_id"] for r in await c.fetchall()}

            total = 0
            for j in jugadores:
                if j["id"] in ya_registrados:
                    continue
                await db.execute("""
                    INSERT INTO historial_precios (player_id, player_name, fecha, precio, price_increment)
                    VALUES (?, ?, ?, ?, ?)
                """, (j["id"], j["name"], today, j["price"] or 0, j["price_increment"] or 0))
                total += 1
            await db.commit()

        await log_sync("historial_precios", "ok", f"{total} snapshots del {today}")
        return {"ok": True, "count": total, "fecha": today}

    except Exception as e:
        await log_sync("historial_precios", "error", str(e))
        return {"ok": False, "error": str(e)}


# ──────────────────────────────────────────────
# SCRAPER 10 — Noticias y Alertas
# ──────────────────────────────────────────────
async def scrape_noticias(client: httpx.AsyncClient) -> dict:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT id, slug, nombre FROM mi_plantilla") as c:
                jugadores = await c.fetchall()

        total = 0
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM noticias_jugadores")
            for j in jugadores:
                slug = j["slug"]
                jid = j["id"]
                jnombre = j["nombre"]
                if not slug:
                    continue
                try:
                    url = f"{CF_BASE}/players/{COMPETITION}/{slug}?fields=news,threads&score=2&lang=es"
                    r = await _api_get(client, url)
                    if r.status_code != 200:
                        continue
                    pdata = r.json().get("data", {})
                    noticias = pdata.get("news", []) or pdata.get("threads", []) or []

                    for n in noticias[:3]:
                        titulo = n.get("title", n.get("subject", ""))
                        contenido = n.get("body", n.get("message", ""))
                        fecha = n.get("date", n.get("createdAt", ts()))
                        await db.execute("""
                            INSERT INTO noticias_jugadores
                            (jugador_id, jugador_nombre, titulo, contenido, fecha, actualizado)
                            VALUES (?, ?, ?, ?, ?, ?)
                        """, (jid, jnombre, titulo, contenido, str(fecha), ts()))
                        total += 1
                except Exception:
                    continue
            await db.commit()

        await log_sync("noticias", "ok", f"{total} noticias guardadas")
        return {"ok": True, "count": total}

    except Exception as e:
        await log_sync("noticias", "error", str(e))
        return {"ok": False, "error": str(e)}


# ──────────────────────────────────────────────
# SCRAPER 8b — FútbolFantasy (httpx + BeautifulSoup, sin Playwright)
# Implementación en scrapers/futbolfantasy.py — re-exportada para compatibilidad
# con el bucle de run_all_scrapers.
# ──────────────────────────────────────────────
from scrapers.futbolfantasy import scrape_futbolfantasy  # noqa: E402,F401
from scrapers.jornadaperfecta import scrape_jornadaperfecta  # noqa: E402,F401


# ----- Bloque legacy (Playwright/subprocess) eliminado -----
# El antiguo `scrape_futbolfantasy` y sus helpers (TEAM_SLUG_MAP,
# _normalize_name, _parse_ff_html, _fetch_all_futbolfantasy_subprocess) han
# sido reemplazados por una implementación pura httpx en el módulo nuevo.
_LEGACY_PLACEHOLDER = None




# ──────────────────────────────────────────────
# Ejecutar todos los scrapers
# ──────────────────────────────────────────────
async def run_all_scrapers() -> list:
    """Ejecuta los scrapers separando dos fases:

    1. MAIN (bloquean la respuesta del endpoint /sync). Si uno falla, se
       continúa con el siguiente.
    2. BACKGROUND (lanzados con asyncio.create_task; no se espera resultado).
       Se reservan los scrapers lentos basados en LLM (Gemini) para que el
       frontend reciba el "✓ sincronización completada" en cuanto termina la
       parte principal.

    Devuelve la lista de resultados de los scrapers MAIN, más una entrada
    sintética por cada scraper background marcándolo como "lanzado en background".
    """
    results = []
    await load_auth_cache()  # Cargar credenciales de la BD antes de empezar

    main_scrapers = [
        ("jugadores_mundo", scrape_jugadores_mundo),
        ("mi_plantilla", scrape_mi_plantilla),
        ("mercado", scrape_mercado),
        ("finanzas", scrape_finanzas),
        ("movimientos_rivales", scrape_movimientos_rivales),
        ("clasificacion", scrape_clasificacion),
        ("plantillas_rivales", scrape_plantillas_rivales),
        ("calendario", scrape_calendario),
        ("futbolfantasy", scrape_futbolfantasy),
        ("jornadaperfecta", scrape_jornadaperfecta),
        ("historial_precios", scrape_historial_precios),
        ("noticias", scrape_noticias),
    ]
    background_scrapers = [
        ("prob_titularidad", scrape_prob_titularidad),
        ("proyecciones", scrape_proyecciones),
    ]

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Fase 1 — MAIN: secuencial, await cada uno, capturar errores
        for name, fn in main_scrapers:
            logger.info(f"[{ts()}] Ejecutando scraper MAIN: {name}")
            try:
                result = await fn(client)
            except Exception as e:
                logger.exception(f"[{ts()}] {name} lanzó excepción")
                result = {"ok": False, "error": f"{type(e).__name__}: {e}"}
            results.append({"scraper": name, **result})

        # Fase 2 — BACKGROUND: fire-and-forget. Las funciones internas ya
        # hacen asyncio.create_task de su trabajo pesado, pero las lanzamos
        # también en task aquí para garantizar que NO se espera resultado
        # aunque cambien su firma en el futuro.
        for name, fn in background_scrapers:
            logger.info(f"[{ts()}] Lanzando scraper BACKGROUND: {name}")
            asyncio.create_task(_run_background_scraper(name, fn))
            results.append({
                "scraper": name,
                "ok": True,
                "mensaje": "lanzado en background",
                "background": True,
            })

    return results


async def _run_background_scraper(name: str, fn) -> None:
    """Wrapper para ejecutar un scraper en background sin bloquear /sync.
    Cualquier excepción se loguea pero no propaga."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            await fn(client)
    except Exception:
        logger.exception(f"[bg-scraper] {name} falló en background")
