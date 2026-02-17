import sqlite3

from .config import DB_NAME, USERS


def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS bills (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT,
                    monthly_target REAL
                )""")

    c.execute("""CREATE TABLE IF NOT EXISTS allocations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT,
                    category TEXT,
                    percentage REAL
                )""")

    c.execute("""CREATE TABLE IF NOT EXISTS income (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT,
                    amount REAL,
                    category TEXT,
                    allocated REAL,
                    date TEXT
                )""")

    c.execute("""CREATE TABLE IF NOT EXISTS bonus (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT,
                    amount REAL,
                    category TEXT,
                    allocated REAL,
                    date TEXT
                )""")

    c.execute("""CREATE TABLE IF NOT EXISTS settings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT,
                    key TEXT,
                    value TEXT
                )""")

    for user in USERS:
        c.execute("SELECT 1 FROM bills WHERE user_id=?", (user["id"],))
        if not c.fetchone():
            c.execute(
                "INSERT INTO bills (user_id, monthly_target) VALUES (?, ?)",
                (user["id"], user["default_bills"]),
            )

        for category in ["Savings", "Investing", "Fun"]:
            c.execute(
                "SELECT 1 FROM allocations WHERE user_id=? AND category=?",
                (user["id"], category),
            )
            if not c.fetchone():
                c.execute(
                    "INSERT INTO allocations (user_id, category, percentage) VALUES (?, ?, ?)",
                    (user["id"], category, 0.0),
                )

    conn.commit()
    conn.close()
