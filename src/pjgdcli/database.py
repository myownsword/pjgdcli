import sqlite3
import os
from contextlib import contextmanager
from datetime import datetime

DB_PATH = os.path.join(os.path.expanduser("~"), ".pjgdcli", "receipts.db")


def get_db_path():
    return DB_PATH


def ensure_db_dir():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)


@contextmanager
def get_connection():
    ensure_db_dir()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.executescript("""
            CREATE TABLE IF NOT EXISTS receipts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_number TEXT NOT NULL UNIQUE,
                amount REAL NOT NULL,
                date TEXT NOT NULL,
                project TEXT NOT NULL,
                description TEXT,
                status TEXT NOT NULL DEFAULT 'unreimbursed',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE
            );

            CREATE TABLE IF NOT EXISTS receipt_tags (
                receipt_id INTEGER NOT NULL,
                tag_id INTEGER NOT NULL,
                PRIMARY KEY (receipt_id, tag_id),
                FOREIGN KEY (receipt_id) REFERENCES receipts(id) ON DELETE CASCADE,
                FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS status_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                receipt_id INTEGER NOT NULL,
                old_status TEXT NOT NULL,
                new_status TEXT NOT NULL,
                changed_at TEXT NOT NULL,
                FOREIGN KEY (receipt_id) REFERENCES receipts(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS import_batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_name TEXT NOT NULL,
                imported_at TEXT NOT NULL,
                total_rows INTEGER NOT NULL,
                success_count INTEGER NOT NULL,
                failed_count INTEGER NOT NULL,
                report_path TEXT
            );

            CREATE TABLE IF NOT EXISTS import_failures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id INTEGER NOT NULL,
                row_number INTEGER NOT NULL,
                invoice_number TEXT,
                error_message TEXT NOT NULL,
                FOREIGN KEY (batch_id) REFERENCES import_batches(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS reimbursement_packages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                total_amount REAL NOT NULL DEFAULT 0,
                tags TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                submitted_at TEXT
            );

            CREATE TABLE IF NOT EXISTS package_receipts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                package_id INTEGER NOT NULL,
                receipt_id INTEGER NOT NULL,
                invoice_number TEXT NOT NULL,
                amount REAL NOT NULL,
                date TEXT NOT NULL,
                project TEXT NOT NULL,
                description TEXT,
                tags TEXT,
                FOREIGN KEY (package_id) REFERENCES reimbursement_packages(id) ON DELETE CASCADE,
                FOREIGN KEY (receipt_id) REFERENCES receipts(id),
                UNIQUE(package_id, receipt_id)
            );

            CREATE INDEX IF NOT EXISTS idx_receipts_project ON receipts(project);
            CREATE INDEX IF NOT EXISTS idx_receipts_date ON receipts(date);
            CREATE INDEX IF NOT EXISTS idx_receipts_status ON receipts(status);
            CREATE INDEX IF NOT EXISTS idx_packages_status ON reimbursement_packages(status);
            CREATE INDEX IF NOT EXISTS idx_package_receipts_receipt ON package_receipts(receipt_id);
        """)
