from shared.db_manager import DBManager


class ConfigDB:
    """配置数据库"""
    _DDL = """
        CREATE TABLE IF NOT EXISTS config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key VARCHAR(128) NOT NULL UNIQUE,
            value TEXT,
            enable INTEGER DEFAULT 1
        );
    """

    def ensure_tables(self):
        self.db.execute(self._DDL)

    def __init__(self, db: DBManager) -> None:
        self.db = db

    def get(self, key: str) -> str | None:
        row = self.db.execute(
            "SELECT value FROM config WHERE key = ? AND enable = 1", (key,)
        ).fetchone()
        return row["value"] if row else None

    def set(self, key: str, value: str) -> None:
        self.db.execute(
            """INSERT INTO config (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
            (key, value),
        )



    

    