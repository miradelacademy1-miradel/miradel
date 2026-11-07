import logging

from sqlalchemy import inspect, text

from .db import Base, engine

log = logging.getLogger("miradel")


def ensure_schema() -> None:
    """Yangi jadvallarni yaratadi va mavjud jadvallarga qoʻshilgan yangi ustunlarni ALTER bilan qoʻshadi.
    Faqat NULL boʻlishi mumkin yoki server_default bor ustunlar qoʻshiladi (eski maʼlumot buzilmaydi)."""
    Base.metadata.create_all(bind=engine)
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                if not (col.nullable or col.server_default is not None):
                    log.warning("Ustun qoʻshilmadi (default yoʻq): %s.%s", table.name, col.name)
                    continue
                sql = f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {col.type.compile(engine.dialect)}'
                if col.server_default is not None:
                    sql += f" DEFAULT {col.server_default.arg.text}"
                conn.execute(text(sql))
                log.info("Ustun qoʻshildi: %s.%s", table.name, col.name)
