import sqlite3

class DBManager:
    def __init__(self) -> None:
        self.conn = None

    def connect(self, path: str) -> None:
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")

    def execute(self, sql: str, params:  dict|tuple = ()) -> sqlite3.Cursor:
        if self.conn is None:
            raise RuntimeError("DB Manager 未初始化")
        cur = self.conn.execute(sql, params)
        self.conn.commit()
        return cur

db = DBManager()