import csv
import os
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from .database import get_connection


STATUS_REIMBURSED = "reimbursed"
STATUS_UNREIMBURSED = "unreimbursed"
VALID_STATUSES = {STATUS_REIMBURSED, STATUS_UNREIMBURSED}

PACKAGE_STATUS_PENDING = "pending"
PACKAGE_STATUS_SUBMITTED = "submitted"
PACKAGE_STATUS_CANCELLED = "cancelled"
VALID_PACKAGE_STATUSES = {PACKAGE_STATUS_PENDING, PACKAGE_STATUS_SUBMITTED, PACKAGE_STATUS_CANCELLED}


def _now():
    return datetime.now().isoformat(timespec="seconds")


def add_receipt(
    invoice_number: str,
    amount: float,
    date: str,
    project: str,
    description: Optional[str] = None,
    status: str = STATUS_UNREIMBURSED,
) -> int:
    if status not in VALID_STATUSES:
        raise ValueError(f"无效状态: {status}")
    if amount <= 0:
        raise ValueError("金额必须为正数")
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise ValueError(f"日期格式错误，应为 YYYY-MM-DD: {date}")

    with get_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO receipts (invoice_number, amount, date, project, description, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (invoice_number, amount, date, project, description, status, _now(), _now()),
            )
            receipt_id = cursor.lastrowid
            if status != STATUS_UNREIMBURSED:
                cursor.execute(
                    """
                    INSERT INTO status_history (receipt_id, old_status, new_status, changed_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (receipt_id, STATUS_UNREIMBURSED, status, _now()),
                )
            return receipt_id
        except Exception as e:
            if "UNIQUE constraint failed: receipts.invoice_number" in str(e):
                raise ValueError(f"发票号已存在: {invoice_number}")
            raise


def get_receipt_by_id(receipt_id: int) -> Optional[Dict]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM receipts WHERE id = ?", (receipt_id,)
        ).fetchone()
        return dict(row) if row else None


def get_receipt_by_invoice(invoice_number: str) -> Optional[Dict]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM receipts WHERE invoice_number = ?", (invoice_number,)
        ).fetchone()
        return dict(row) if row else None


def list_receipts(
    project: Optional[str] = None,
    month: Optional[str] = None,
    min_amount: Optional[float] = None,
    max_amount: Optional[float] = None,
    tags: Optional[List[str]] = None,
    status: Optional[str] = None,
) -> List[Dict]:
    query = "SELECT DISTINCT r.* FROM receipts r"
    params = []
    conditions = []

    if tags:
        query += " JOIN receipt_tags rt ON r.id = rt.receipt_id JOIN tags t ON rt.tag_id = t.id"
        placeholders = ",".join(["?"] * len(tags))
        conditions.append(f"t.name IN ({placeholders})")
        params.extend(tags)

    if project:
        conditions.append("r.project = ?")
        params.append(project)
    if month:
        conditions.append("strftime('%Y-%m', r.date) = ?")
        params.append(month)
    if min_amount is not None:
        conditions.append("r.amount >= ?")
        params.append(min_amount)
    if max_amount is not None:
        conditions.append("r.amount <= ?")
        params.append(max_amount)
    if status:
        conditions.append("r.status = ?")
        params.append(status)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    if tags:
        query += f" GROUP BY r.id HAVING COUNT(DISTINCT t.name) = {len(tags)}"

    query += " ORDER BY r.date DESC, r.id DESC"

    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
        receipts = [dict(row) for row in rows]
        for r in receipts:
            r["tags"] = get_tags_for_receipt(r["id"])
        return receipts


def update_status(receipt_id: int, new_status: str) -> bool:
    if new_status not in VALID_STATUSES:
        raise ValueError(f"无效状态: {new_status}")

    with get_connection() as conn:
        row = conn.execute(
            "SELECT status FROM receipts WHERE id = ?", (receipt_id,)
        ).fetchone()
        if not row:
            return False
        old_status = row["status"]
        if old_status == new_status:
            return True
        conn.execute(
            "UPDATE receipts SET status = ?, updated_at = ? WHERE id = ?",
            (new_status, _now(), receipt_id),
        )
        conn.execute(
            """
            INSERT INTO status_history (receipt_id, old_status, new_status, changed_at)
            VALUES (?, ?, ?, ?)
            """,
            (receipt_id, old_status, new_status, _now()),
        )
        return True


def undo_last_status_change(receipt_id: int) -> Optional[str]:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, old_status FROM status_history
            WHERE receipt_id = ? ORDER BY id DESC LIMIT 1
            """,
            (receipt_id,),
        ).fetchone()
        if not row:
            return None
        history_id = row["id"]
        old_status = row["old_status"]
        current_row = conn.execute(
            "SELECT status FROM receipts WHERE id = ?", (receipt_id,)
        ).fetchone()
        if not current_row:
            return None
        conn.execute(
            "UPDATE receipts SET status = ?, updated_at = ? WHERE id = ?",
            (old_status, _now(), receipt_id),
        )
        conn.execute(
            "DELETE FROM status_history WHERE id = ?",
            (history_id,),
        )
        return old_status


def add_tag(name: str) -> int:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM tags WHERE name = ?", (name,))
        row = cursor.fetchone()
        if row:
            return row["id"]
        cursor.execute("INSERT INTO tags (name) VALUES (?)", (name,))
        return cursor.lastrowid


def get_or_create_tag(name: str) -> int:
    return add_tag(name)


def add_tags_to_receipt(receipt_id: int, tag_names: List[str]) -> None:
    for name in tag_names:
        tag_id = add_tag(name)
        with get_connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO receipt_tags (receipt_id, tag_id) VALUES (?, ?)",
                (receipt_id, tag_id),
            )


def remove_tags_from_receipt(receipt_id: int, tag_names: List[str]) -> None:
    with get_connection() as conn:
        for name in tag_names:
            row = conn.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()
            if row:
                conn.execute(
                    "DELETE FROM receipt_tags WHERE receipt_id = ? AND tag_id = ?",
                    (receipt_id, row["id"]),
                )


def get_tags_for_receipt(receipt_id: int) -> List[str]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT t.name FROM tags t
            JOIN receipt_tags rt ON t.id = rt.tag_id
            WHERE rt.receipt_id = ? ORDER BY t.name
            """,
            (receipt_id,),
        ).fetchall()
        return [row["name"] for row in rows]


def list_all_tags() -> List[Dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT t.id, t.name, COUNT(rt.receipt_id) as receipt_count
            FROM tags t LEFT JOIN receipt_tags rt ON t.id = rt.tag_id
            GROUP BY t.id ORDER BY t.name
            """
        ).fetchall()
        return [dict(row) for row in rows]


def validate_csv_row(row: Dict, line_num: int, seen_invoices: set) -> Tuple[bool, Dict, str]:
    errors = []

    required_fields = ["invoice_number", "amount", "date", "project"]
    for field in required_fields:
        if field not in row or not str(row[field]).strip():
            errors.append(f"缺少必填字段: {field}")

    if errors:
        return False, row, "; ".join(errors)

    invoice_number = str(row["invoice_number"]).strip()
    amount_str = str(row["amount"]).strip()
    date_str = str(row["date"]).strip()
    project = str(row["project"]).strip()

    try:
        amount = float(amount_str)
        if amount <= 0:
            errors.append("金额必须为正数")
    except (ValueError, TypeError):
        errors.append(f"金额格式错误: {amount_str}")
        amount = 0

    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        errors.append(f"日期格式错误(应为 YYYY-MM-DD): {date_str}")

    if invoice_number in seen_invoices:
        errors.append(f"CSV 内发票号重复: {invoice_number}")

    existing = get_receipt_by_invoice(invoice_number)
    if existing:
        errors.append(f"数据库中发票号已存在: {invoice_number}")

    if errors:
        return False, row, "; ".join(errors)

    return True, {
        "invoice_number": invoice_number,
        "amount": amount,
        "date": date_str,
        "project": project,
        "description": str(row.get("description", "")).strip() or None,
        "tags": [t.strip() for t in str(row.get("tags", "")).split(";") if t.strip()],
    }, ""


def import_csv(file_path: str) -> Dict:
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"文件不存在: {file_path}")

    file_name = os.path.basename(file_path)
    failures = []
    successes = []
    seen_invoices = set()

    with open(file_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for line_num, row in enumerate(reader, start=2):
            is_valid, data, error = validate_csv_row(row, line_num, seen_invoices)
            if not is_valid:
                failures.append({
                    "row_number": line_num,
                    "invoice_number": str(row.get("invoice_number", "")).strip(),
                    "error_message": error,
                })
                continue
            seen_invoices.add(data["invoice_number"])
            try:
                receipt_id = add_receipt(
                    invoice_number=data["invoice_number"],
                    amount=data["amount"],
                    date=data["date"],
                    project=data["project"],
                    description=data["description"],
                )
                if data["tags"]:
                    add_tags_to_receipt(receipt_id, data["tags"])
                successes.append({
                    "row_number": line_num,
                    "receipt_id": receipt_id,
                    "invoice_number": data["invoice_number"],
                })
            except Exception as e:
                failures.append({
                    "row_number": line_num,
                    "invoice_number": data["invoice_number"],
                    "error_message": str(e),
                })

    batch_id = None
    report_path = None
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO import_batches (file_name, imported_at, total_rows, success_count, failed_count, report_path)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (file_name, _now(), len(successes) + len(failures), len(successes), len(failures), None),
        )
        batch_id = cursor.lastrowid

        for failure in failures:
            cursor.execute(
                """
                INSERT INTO import_failures (batch_id, row_number, invoice_number, error_message)
                VALUES (?, ?, ?, ?)
                """,
                (batch_id, failure["row_number"], failure["invoice_number"], failure["error_message"]),
            )

    if failures:
        report_dir = os.path.join(os.path.expanduser("~"), ".pjgdcli", "reports")
        os.makedirs(report_dir, exist_ok=True)
        report_path = os.path.join(
            report_dir,
            f"import_report_batch_{batch_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        )
        with open(report_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["row_number", "invoice_number", "error_message"])
            writer.writeheader()
            writer.writerows(failures)
        with get_connection() as conn:
            conn.execute(
                "UPDATE import_batches SET report_path = ? WHERE id = ?",
                (report_path, batch_id),
            )

    return {
        "batch_id": batch_id,
        "file_name": file_name,
        "total_rows": len(successes) + len(failures),
        "success_count": len(successes),
        "failed_count": len(failures),
        "report_path": report_path,
        "failures": failures,
    }


def monthly_summary(month: str) -> List[Dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                project,
                SUM(CASE WHEN status = 'reimbursed' THEN amount ELSE 0 END) as reimbursed_amount,
                SUM(CASE WHEN status = 'unreimbursed' THEN amount ELSE 0 END) as unreimbursed_amount,
                SUM(amount) as total_amount,
                COUNT(*) as receipt_count
            FROM receipts
            WHERE strftime('%Y-%m', date) = ?
            GROUP BY project
            ORDER BY project
            """,
            (month,),
        ).fetchall()
        return [dict(row) for row in rows]


def list_import_batches(only_failed: bool = False) -> List[Dict]:
    with get_connection() as conn:
        query = "SELECT * FROM import_batches"
        params = []
        if only_failed:
            query += " WHERE failed_count > 0"
        query += " ORDER BY imported_at DESC"
        rows = conn.execute(query, params).fetchall()
        batches = [dict(row) for row in rows]
        for batch in batches:
            if batch["failed_count"] > 0:
                fail_rows = conn.execute(
                    "SELECT row_number, invoice_number, error_message FROM import_failures WHERE batch_id = ? ORDER BY row_number",
                    (batch["id"],),
                ).fetchall()
                batch["failures"] = [dict(row) for row in fail_rows]
            else:
                batch["failures"] = []
        return batches


def _get_receipts_in_pending_packages() -> set:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT pr.receipt_id
            FROM package_receipts pr
            JOIN reimbursement_packages rp ON pr.package_id = rp.id
            WHERE rp.status = ?
            """,
            (PACKAGE_STATUS_PENDING,),
        ).fetchall()
        return {row["receipt_id"] for row in rows}


def create_package(
    name: str,
    description: Optional[str] = None,
    project: Optional[str] = None,
    month: Optional[str] = None,
    min_amount: Optional[float] = None,
    max_amount: Optional[float] = None,
    tags: Optional[List[str]] = None,
) -> Dict:
    available_receipts = list_receipts(
        project=project,
        month=month,
        min_amount=min_amount,
        max_amount=max_amount,
        tags=tags,
        status=STATUS_UNREIMBURSED,
    )

    pending_receipt_ids = _get_receipts_in_pending_packages()
    filtered_receipts = [r for r in available_receipts if r["id"] not in pending_receipt_ids]

    if not filtered_receipts:
        raise ValueError("没有符合条件的未报销票据可加入报销包")

    total_amount = sum(r["amount"] for r in filtered_receipts)
    all_tags = set()
    for r in filtered_receipts:
        all_tags.update(r.get("tags", []))
    tags_str = ";".join(sorted(all_tags)) if all_tags else None

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO reimbursement_packages (name, description, total_amount, tags, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (name, description, total_amount, tags_str, PACKAGE_STATUS_PENDING, _now(), _now()),
        )
        package_id = cursor.lastrowid

        for r in filtered_receipts:
            receipt_tags = ";".join(r.get("tags", []))
            cursor.execute(
                """
                INSERT INTO package_receipts (package_id, receipt_id, invoice_number, amount, date, project, description, tags)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (package_id, r["id"], r["invoice_number"], r["amount"], r["date"], r["project"], r.get("description"), receipt_tags),
            )

    return get_package(package_id)


def get_package(package_id: int) -> Optional[Dict]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM reimbursement_packages WHERE id = ?",
            (package_id,),
        ).fetchone()
        if not row:
            return None
        pkg = dict(row)
        receipt_rows = conn.execute(
            "SELECT * FROM package_receipts WHERE package_id = ? ORDER BY date DESC, id",
            (package_id,),
        ).fetchall()
        pkg["receipts"] = [dict(r) for r in receipt_rows]
        for r in pkg["receipts"]:
            r["tags"] = [t for t in (r.get("tags") or "").split(";") if t]
        pkg["tags"] = [t for t in (pkg.get("tags") or "").split(";") if t]
        return pkg


def list_packages(status: Optional[str] = None) -> List[Dict]:
    with get_connection() as conn:
        query = "SELECT * FROM reimbursement_packages"
        params = []
        if status:
            query += " WHERE status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC"
        rows = conn.execute(query, params).fetchall()
        packages = [dict(row) for row in rows]
        for pkg in packages:
            pkg["tags"] = [t for t in (pkg.get("tags") or "").split(";") if t]
            count = conn.execute(
                "SELECT COUNT(*) as cnt FROM package_receipts WHERE package_id = ?",
                (pkg["id"],),
            ).fetchone()
            pkg["receipt_count"] = count["cnt"] if count else 0
        return packages


def _validate_package_for_submission(package_id: int, conn=None) -> Dict:
    if conn is None:
        pkg = get_package(package_id)
    else:
        row = conn.execute(
            "SELECT * FROM reimbursement_packages WHERE id = ?",
            (package_id,),
        ).fetchone()
        if not row:
            pkg = None
        else:
            pkg = dict(row)
            receipt_rows = conn.execute(
                "SELECT * FROM package_receipts WHERE package_id = ? ORDER BY date DESC, id",
                (package_id,),
            ).fetchall()
            pkg["receipts"] = [dict(r) for r in receipt_rows]
            for r in pkg["receipts"]:
                r["tags"] = [t for t in (r.get("tags") or "").split(";") if t]
            pkg["tags"] = [t for t in (pkg.get("tags") or "").split(";") if t]

    if not pkg:
        raise ValueError(f"报销包 ID={package_id} 不存在")

    if pkg["status"] == PACKAGE_STATUS_SUBMITTED:
        raise ValueError(f"报销包 ID={package_id} 已提交，不能重复提交")

    if pkg["status"] == PACKAGE_STATUS_CANCELLED:
        raise ValueError(f"报销包 ID={package_id} 已取消，不能提交")

    if not pkg["receipts"]:
        raise ValueError(f"报销包 ID={package_id} 为空，不能提交")

    for pr in pkg["receipts"]:
        if conn is None:
            receipt = get_receipt_by_id(pr["receipt_id"])
        else:
            row = conn.execute(
                "SELECT * FROM receipts WHERE id = ?", (pr["receipt_id"],)
            ).fetchone()
            receipt = dict(row) if row else None

        if not receipt:
            raise ValueError(f"票据 ID={pr['receipt_id']} (发票号={pr['invoice_number']}) 已不存在")
        if receipt["status"] != STATUS_UNREIMBURSED:
            status_text = "已报销" if receipt["status"] == STATUS_REIMBURSED else receipt["status"]
            raise ValueError(f"票据 ID={pr['receipt_id']} (发票号={pr['invoice_number']}) 状态已变更为 {status_text}，不能提交")
        if pr["amount"] != receipt["amount"]:
            raise ValueError(f"票据 ID={pr['receipt_id']} (发票号={pr['invoice_number']}) 金额已变更 (快照={pr['amount']:.2f}, 当前={receipt['amount']:.2f})，不能提交")

    return pkg


def submit_package(package_id: int) -> Dict:
    with get_connection() as conn:
        pkg = _validate_package_for_submission(package_id, conn)

        for pr in pkg["receipts"]:
            conn.execute(
                "UPDATE receipts SET status = ?, updated_at = ? WHERE id = ?",
                (STATUS_REIMBURSED, _now(), pr["receipt_id"]),
            )
            conn.execute(
                """
                INSERT INTO status_history (receipt_id, old_status, new_status, changed_at)
                VALUES (?, ?, ?, ?)
                """,
                (pr["receipt_id"], STATUS_UNREIMBURSED, STATUS_REIMBURSED, _now()),
            )

        conn.execute(
            """
            UPDATE reimbursement_packages
            SET status = ?, updated_at = ?, submitted_at = ?
            WHERE id = ?
            """,
            (PACKAGE_STATUS_SUBMITTED, _now(), _now(), package_id),
        )

    return get_package(package_id)


def cancel_package(package_id: int) -> Dict:
    pkg = get_package(package_id)
    if not pkg:
        raise ValueError(f"报销包 ID={package_id} 不存在")

    if pkg["status"] == PACKAGE_STATUS_SUBMITTED:
        raise ValueError(f"报销包 ID={package_id} 已提交，不能取消")

    if pkg["status"] == PACKAGE_STATUS_CANCELLED:
        raise ValueError(f"报销包 ID={package_id} 已取消")

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE reimbursement_packages
            SET status = ?, updated_at = ?
            WHERE id = ?
            """,
            (PACKAGE_STATUS_CANCELLED, _now(), package_id),
        )

    return get_package(package_id)


def export_package_csv(package_id: int, output_path: str) -> str:
    output_dir = os.path.dirname(os.path.abspath(output_path))
    if output_dir and not os.path.isdir(output_dir):
        raise ValueError(f"导出目录不存在: {output_dir}")
    if output_dir and not os.access(output_dir, os.W_OK):
        raise ValueError(f"导出目录不可写: {output_dir}")

    pkg = get_package(package_id)
    if not pkg:
        raise ValueError(f"报销包 ID={package_id} 不存在")

    if not pkg["receipts"]:
        raise ValueError(f"报销包 ID={package_id} 为空，无法导出")

    with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["包ID", "包名称", "包状态", "发票号", "金额", "日期", "项目", "备注", "标签"])
        status_text = {
            PACKAGE_STATUS_PENDING: "待提交",
            PACKAGE_STATUS_SUBMITTED: "已提交",
            PACKAGE_STATUS_CANCELLED: "已取消",
        }.get(pkg["status"], pkg["status"])
        for pr in pkg["receipts"]:
            writer.writerow([
                pkg["id"],
                pkg["name"],
                status_text,
                pr["invoice_number"],
                f"{pr['amount']:.2f}",
                pr["date"],
                pr["project"],
                pr.get("description") or "",
                ";".join(pr.get("tags", [])),
            ])

    return output_path
