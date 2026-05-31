"""Helpers compartidos entre scrapers de fuentes externas (FF, JP, ...)."""
import logging

import aiosqlite

logger = logging.getLogger(__name__)


async def recalcular_prob_media(db: aiosqlite.Connection) -> None:
    """Recalcula `mi_plantilla.prob_media` a partir de prob_futbol_fantasy y
    prob_jornada. Si solo una está disponible, usa esa. Si ninguna, deja el
    valor previo intacto.
    """
    await db.execute("""
        UPDATE mi_plantilla SET prob_media = (
            CASE
                WHEN prob_futbol_fantasy IS NOT NULL AND prob_jornada IS NOT NULL
                    THEN (prob_futbol_fantasy + prob_jornada) / 2
                WHEN prob_futbol_fantasy IS NOT NULL THEN prob_futbol_fantasy
                WHEN prob_jornada IS NOT NULL THEN prob_jornada
                ELSE prob_media
            END
        )
    """)
    logger.info("[common] prob_media recalculada en mi_plantilla")
