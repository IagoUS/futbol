# Módulo de base de datos SQLite con aiosqlite
import aiosqlite
import os
import logging
from datetime import datetime

DB_PATH = os.environ.get(
    "DB_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "biwenger.db"),
)

logger = logging.getLogger(__name__)


async def init_db():
    """Crea todas las tablas si no existen. NO borra datos existentes.
    Las migraciones de schema se aplican mediante ALTER TABLE ADD COLUMN."""
    async with aiosqlite.connect(DB_PATH) as db:
        # ── Creación base (nunca borra datos) ───────────────────────────
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS mi_plantilla (
                id INTEGER PRIMARY KEY,
                nombre TEXT,
                posicion TEXT,
                equipo TEXT,
                precio_actual INTEGER,
                precio_compra INTEGER,
                roi INTEGER,
                puntos_totales INTEGER,
                puntos_5j TEXT,
                estado TEXT,
                slug TEXT,
                prob_titularidad REAL DEFAULT 0,
                actualizado TEXT
            );

            CREATE TABLE IF NOT EXISTS mercado (
                id INTEGER PRIMARY KEY,
                nombre TEXT,
                posicion TEXT,
                equipo TEXT,
                precio INTEGER,
                puntos_ultima_jornada INTEGER,
                tendencia INTEGER,
                score_oportunidad REAL DEFAULT 0,
                actualizado TEXT
            );

            CREATE TABLE IF NOT EXISTS finanzas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                saldo INTEGER,
                valor_plantilla INTEGER,
                dinero_gastado INTEGER,
                dinero_ingresado INTEGER,
                presupuesto_inicial INTEGER,
                actualizado TEXT
            );

            CREATE TABLE IF NOT EXISTS movimientos_rivales (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario_nombre TEXT,
                usuario_id INTEGER,
                tipo TEXT,
                jugador_nombre TEXT,
                jugador_id INTEGER,
                precio INTEGER,
                fecha TEXT,
                actualizado TEXT
            );

            CREATE TABLE IF NOT EXISTS clasificacion (
                id INTEGER PRIMARY KEY,
                posicion INTEGER,
                nombre TEXT,
                puntos_totales INTEGER,
                puntos_ultima_jornada INTEGER,
                valor_plantilla INTEGER,
                actualizado TEXT
            );

            CREATE TABLE IF NOT EXISTS plantillas_rivales (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario_id INTEGER,
                usuario_nombre TEXT,
                jugador_id INTEGER,
                jugador_nombre TEXT,
                jugador_posicion TEXT,
                actualizado TEXT
            );

            CREATE TABLE IF NOT EXISTS calendario (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                equipo TEXT,
                jornada INTEGER,
                rival TEXT,
                localidad TEXT,
                fecha TEXT,
                dificultad INTEGER,
                actualizado TEXT
            );

            CREATE TABLE IF NOT EXISTS jugadores_mundo (
                id INTEGER PRIMARY KEY,
                name TEXT,
                slug TEXT,
                position TEXT,
                team_id INTEGER,
                price INTEGER,
                points INTEGER,
                fitness TEXT,
                actualizado TEXT
            );

            CREATE TABLE IF NOT EXISTS proyecciones_jugador (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id INTEGER UNIQUE,
                player_name TEXT,
                prob_gol INTEGER,
                prob_asistencia INTEGER,
                minutos_esperados INTEGER,
                valoracion_mundial TEXT,
                recomendacion TEXT,
                justificacion TEXT,
                fuente TEXT,
                fecha_actualizacion TEXT
            );

            CREATE TABLE IF NOT EXISTS historial_precios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id INTEGER,
                player_name TEXT,
                fecha DATE,
                precio INTEGER,
                price_increment INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS noticias_jugadores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                jugador_id INTEGER,
                jugador_nombre TEXT,
                titulo TEXT,
                contenido TEXT,
                fecha TEXT,
                actualizado TEXT
            );

            CREATE TABLE IF NOT EXISTS historial_analisis (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                jugador_id INTEGER,
                jugador_nombre TEXT,
                fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                json_respuesta TEXT,
                tipo_consulta TEXT DEFAULT 'jugador'
            );

            CREATE TABLE IF NOT EXISTS consejos_ia (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tipo TEXT,
                contenido TEXT,
                creado TEXT
            );

            CREATE TABLE IF NOT EXISTS sync_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scraper TEXT,
                estado TEXT,
                mensaje TEXT,
                timestamp TEXT
            );

            CREATE TABLE IF NOT EXISTS auth (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT,
                password TEXT,
                token TEXT,
                user_id INTEGER,
                league_id INTEGER,
                user_name TEXT,
                version TEXT,
                created_at TEXT
            );
            DELETE FROM auth WHERE user_id = 0 OR league_id = 0 OR user_id IS NULL OR league_id IS NULL;
        """)

        # ── Migración: user_id en mercado (para filtrar mis propias ventas) ─
        async with db.execute("PRAGMA table_info(mercado)") as cur:
            existing_me = {r[1] for r in await cur.fetchall()}
        if "user_id" not in existing_me:
            await db.execute("ALTER TABLE mercado ADD COLUMN user_id INTEGER")
            logger.info("Migración: mercado.user_id añadida")

        # ── Migraciones: columnas nuevas a mi_plantilla ─────────────────
        _mp_new_cols = [
            ("prob_analitica",      "INTEGER"),
            ("prob_jornada",        "INTEGER"),
            ("prob_futbol_fantasy", "INTEGER"),
            ("prob_media",          "INTEGER"),
            ("rol_esperado",        "TEXT"),
        ]
        async with db.execute("PRAGMA table_info(mi_plantilla)") as cur:
            existing_mp = {r[1] for r in await cur.fetchall()}
        for col, col_def in _mp_new_cols:
            if col not in existing_mp:
                await db.execute(f"ALTER TABLE mi_plantilla ADD COLUMN {col} {col_def}")
                logger.info(f"Migración: mi_plantilla.{col} añadida")

        # ── Migraciones: añadir columnas nuevas a jugadores_mundo ───────
        _jm_new_cols = [
            ("team_name",        "TEXT"),
            ("fantasy_price",    "INTEGER"),
            ("status",           "TEXT DEFAULT 'ok'"),
            ("status_info",      "TEXT"),
            ("price_increment",  "INTEGER DEFAULT 0"),
            ("next_match_date",  "INTEGER"),
            ("next_match_rival", "TEXT"),
        ]
        async with db.execute("PRAGMA table_info(jugadores_mundo)") as cur:
            existing_jm = {r[1] for r in await cur.fetchall()}
        for col, col_def in _jm_new_cols:
            if col not in existing_jm:
                await db.execute(f"ALTER TABLE jugadores_mundo ADD COLUMN {col} {col_def}")
                logger.info(f"Migración: jugadores_mundo.{col} añadida")

        # ── Migración: finanzas.maximum_bid (puja máxima de Biwenger) ───
        async with db.execute("PRAGMA table_info(finanzas)") as cur:
            existing_fin = {r[1] for r in await cur.fetchall()}
        if "maximum_bid" not in existing_fin:
            await db.execute("ALTER TABLE finanzas ADD COLUMN maximum_bid INTEGER")
            logger.info("Migración: finanzas.maximum_bid añadida")

        # ── Migración: índice UNIQUE en movimientos_rivales ────────────
        # Permite usar INSERT OR IGNORE para preservar movimientos históricos
        # (los insertados manualmente y los más antiguos) sin que se dupliquen
        # al volver a sincronizar.
        await db.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_mov_rivales_uniq
            ON movimientos_rivales (usuario_id, jugador_id, precio, fecha, tipo)
        """)

        # ── Migración: historial_precios esquema viejo → nuevo ──────────
        # El esquema viejo usaba jugador_id/jugador_nombre; el nuevo usa player_id/player_name
        async with db.execute("PRAGMA table_info(historial_precios)") as cur:
            existing_hp = {r[1] for r in await cur.fetchall()}
        if "jugador_id" in existing_hp:
            logger.info("Migración: recreando historial_precios con nuevo schema")
            await db.execute("DROP TABLE historial_precios")
            await db.execute("""
                CREATE TABLE historial_precios (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    player_id INTEGER,
                    player_name TEXT,
                    fecha DATE,
                    precio INTEGER,
                    price_increment INTEGER DEFAULT 0
                )
            """)

        await db.commit()
    logger.info("Base de datos inicializada correctamente")


async def log_sync(scraper: str, estado: str, mensaje: str):
    """Registra el estado de cada scraper en la tabla sync_log."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO sync_log (scraper, estado, mensaje, timestamp) VALUES (?, ?, ?, ?)",
            (scraper, estado, mensaje, datetime.now().isoformat())
        )
        await db.commit()


async def save_auth(email: str, password: str, token: str, user_id: int,
                    league_id: int, user_name: str, version: str = "630"):
    """Guarda o actualiza las credenciales de autenticación."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM auth")
        await db.execute(
            """INSERT INTO auth
               (email, password, token, user_id, league_id, user_name, version, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (email, password, token, user_id, league_id, user_name, version,
             datetime.now().isoformat())
        )
        await db.commit()


async def get_auth() -> dict:
    """Devuelve las credenciales guardadas o None si no hay sesión."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM auth ORDER BY id DESC LIMIT 1"
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else {}


async def clear_auth():
    """Elimina las credenciales (cierre de sesión)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM auth")
        await db.commit()


async def get_sync_logs(limit: int = 50):
    """Devuelve los últimos logs de sincronización."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM sync_log ORDER BY id DESC LIMIT ?", (limit,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]
