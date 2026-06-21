import sys
from typing import List, Optional

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.console import Group
from rich import box

from .database import init_db, get_db_path, get_connection
from . import services

console = Console()


def _print_receipts(receipts: List[dict], title: str = "票据列表"):
    if not receipts:
        console.print(f"[yellow]{title}: 暂无数据[/yellow]")
        return

    table = Table(title=title, box=box.ROUNDED, show_lines=False)
    table.add_column("ID", justify="right", style="cyan", no_wrap=True)
    table.add_column("发票号", style="magenta")
    table.add_column("金额", justify="right", style="green")
    table.add_column("日期", style="blue")
    table.add_column("项目", style="yellow")
    table.add_column("状态", style="bold")
    table.add_column("标签", style="white")
    table.add_column("备注", style="dim")

    for r in receipts:
        status_style = "bold green" if r["status"] == "reimbursed" else "bold red"
        status_text = "已报销" if r["status"] == "reimbursed" else "未报销"
        tags = ", ".join(r.get("tags", []))
        desc = r.get("description") or ""
        table.add_row(
            str(r["id"]),
            r["invoice_number"],
            f"¥{r['amount']:.2f}",
            r["date"],
            r["project"],
            f"[{status_style}]{status_text}[/{status_style}]",
            tags,
            desc,
        )
    console.print(table)

    total = sum(r["amount"] for r in receipts)
    reimbursed = sum(r["amount"] for r in receipts if r["status"] == "reimbursed")
    unreimbursed = sum(r["amount"] for r in receipts if r["status"] != "reimbursed")
    console.print(f"  [dim]共 {len(receipts)} 张 | 总计 [bold]¥{total:.2f}[/bold] | 已报销 [green]¥{reimbursed:.2f}[/green] | 未报销 [red]¥{unreimbursed:.2f}[/red][/dim]")


@click.group()
@click.version_option("0.1.0", prog_name="pjgdcli")
def main():
    """本地票据归档 CLI 工具

    使用 SQLite 存储本地票据数据，支持新增、查询、标签管理、报销状态追踪和 CSV 批量导入。
    """
    init_db()


@main.command("init")
def init_cmd():
    """初始化数据库"""
    init_db()
    console.print(f"[green]数据库初始化成功！[/green] 路径: [blue]{get_db_path()}[/blue]")


@main.command("add")
@click.option("--invoice", "-i", required=True, help="发票号码")
@click.option("--amount", "-a", required=True, type=float, help="金额（正数）")
@click.option("--date", "-d", required=True, help="开票日期 (YYYY-MM-DD)")
@click.option("--project", "-p", required=True, help="所属项目名称")
@click.option("--desc", "-m", default=None, help="备注说明")
@click.option("--tag", "-t", "tags", multiple=True, help="标签（可多次指定）")
@click.option("--reimbursed", "-r", is_flag=True, help="标记为已报销")
def add_cmd(invoice: str, amount: float, date: str, project: str, desc: Optional[str], tags: tuple, reimbursed: bool):
    """新增一张票据"""
    try:
        status = "reimbursed" if reimbursed else "unreimbursed"
        rid = services.add_receipt(invoice, amount, date, project, desc, status)
        if tags:
            services.add_tags_to_receipt(rid, list(tags))
        console.print(f"[green]票据新增成功！[/green] ID={rid}, 发票号=[blue]{invoice}[/blue]")
    except ValueError as e:
        console.print(f"[red]错误: {e}[/red]")
        sys.exit(1)


@main.command("list")
@click.option("--project", "-p", default=None, help="按项目过滤")
@click.option("--month", "-m", default=None, help="按月份过滤 (YYYY-MM)")
@click.option("--min-amount", "min_amount", type=float, default=None, help="最小金额")
@click.option("--max-amount", "max_amount", type=float, default=None, help="最大金额")
@click.option("--tag", "-t", "tags", multiple=True, help="按标签过滤（可多次指定，需同时匹配所有标签）")
@click.option("--status", "-s", type=click.Choice(["reimbursed", "unreimbursed"]), default=None, help="按状态过滤")
def list_cmd(project: Optional[str], month: Optional[str], min_amount: Optional[float], max_amount: Optional[float], tags: tuple, status: Optional[str]):
    """查询票据列表，支持多种过滤条件组合"""
    receipts = services.list_receipts(
        project=project,
        month=month,
        min_amount=min_amount,
        max_amount=max_amount,
        tags=list(tags) if tags else None,
        status=status,
    )
    title_parts = []
    if project:
        title_parts.append(f"项目={project}")
    if month:
        title_parts.append(f"月份={month}")
    if min_amount is not None or max_amount is not None:
        rng = f"¥{min_amount or 0:.2f}~¥{max_amount or '∞'}"
        title_parts.append(f"金额={rng}")
    if tags:
        title_parts.append(f"标签={','.join(tags)}")
    if status:
        title_parts.append(f"状态={status}")
    title = "票据查询结果" + (f" ({'; '.join(title_parts)})" if title_parts else "")
    _print_receipts(receipts, title)


@main.command("reimburse")
@click.argument("receipt_id", type=int)
def reimburse_cmd(receipt_id: int):
    """将票据标记为已报销"""
    receipt = services.get_receipt_by_id(receipt_id)
    if not receipt:
        console.print(f"[red]票据 ID={receipt_id} 不存在[/red]")
        sys.exit(1)
    services.update_status(receipt_id, "reimbursed")
    console.print(f"[green]票据已标记为已报销[/green] ID={receipt_id}, 发票号={receipt['invoice_number']}")


@main.command("unreimburse")
@click.argument("receipt_id", type=int)
def unreimburse_cmd(receipt_id: int):
    """将票据回退为未报销"""
    receipt = services.get_receipt_by_id(receipt_id)
    if not receipt:
        console.print(f"[red]票据 ID={receipt_id} 不存在[/red]")
        sys.exit(1)
    services.update_status(receipt_id, "unreimbursed")
    console.print(f"[green]票据已回退为未报销[/green] ID={receipt_id}, 发票号={receipt['invoice_number']}")


@main.command("undo")
@click.argument("receipt_id", type=int)
def undo_cmd(receipt_id: int):
    """撤销最近一次状态变更"""
    receipt = services.get_receipt_by_id(receipt_id)
    if not receipt:
        console.print(f"[red]票据 ID={receipt_id} 不存在[/red]")
        sys.exit(1)
    old_status = services.undo_last_status_change(receipt_id)
    if old_status is None:
        console.print(f"[yellow]票据 ID={receipt_id} 没有可撤销的状态变更历史[/yellow]")
        return
    status_text = "已报销" if old_status == "reimbursed" else "未报销"
    console.print(f"[green]已撤销状态变更[/green] ID={receipt_id}, 当前状态=[bold]{status_text}[/bold]")


@main.group("tag")
def tag_group():
    """标签管理命令"""
    pass


@tag_group.command("list")
def tag_list_cmd():
    """列出所有标签"""
    tags = services.list_all_tags()
    if not tags:
        console.print("[yellow]暂无标签[/yellow]")
        return
    table = Table(title="标签列表", box=box.ROUNDED)
    table.add_column("ID", justify="right", style="cyan")
    table.add_column("名称", style="magenta")
    table.add_column("票据数", justify="right", style="green")
    for t in tags:
        table.add_row(str(t["id"]), t["name"], str(t["receipt_count"]))
    console.print(table)


@tag_group.command("add")
@click.argument("receipt_id", type=int)
@click.argument("tag_names", nargs=-1, required=True)
def tag_add_cmd(receipt_id: int, tag_names: tuple):
    """为票据绑定标签

    RECEIPT_ID: 票据ID
    TAG_NAMES: 一个或多个标签名称
    """
    receipt = services.get_receipt_by_id(receipt_id)
    if not receipt:
        console.print(f"[red]票据 ID={receipt_id} 不存在[/red]")
        sys.exit(1)
    services.add_tags_to_receipt(receipt_id, list(tag_names))
    console.print(f"[green]已绑定标签[/green] {', '.join(tag_names)} -> 票据ID={receipt_id}")


@tag_group.command("remove")
@click.argument("receipt_id", type=int)
@click.argument("tag_names", nargs=-1, required=True)
def tag_remove_cmd(receipt_id: int, tag_names: tuple):
    """从票据移除标签"""
    receipt = services.get_receipt_by_id(receipt_id)
    if not receipt:
        console.print(f"[red]票据 ID={receipt_id} 不存在[/red]")
        sys.exit(1)
    services.remove_tags_from_receipt(receipt_id, list(tag_names))
    console.print(f"[green]已移除标签[/green] {', '.join(tag_names)} <- 票据ID={receipt_id}")


@main.command("import")
@click.argument("csv_file", type=click.Path(exists=True, dir_okay=False))
def import_cmd(csv_file: str):
    """从 CSV 文件批量导入票据

    CSV 必填字段: invoice_number, amount, date, project
    可选字段: description, tags (多个标签用分号分隔)
    """
    try:
        result = services.import_csv(csv_file)
    except Exception as e:
        console.print(f"[red]导入失败: {e}[/red]")
        sys.exit(1)

    console.print(Panel.fit(
        f"[bold green]导入完成[/bold green]\n"
        f"批次ID: [cyan]{result['batch_id']}[/cyan]\n"
        f"文件: [blue]{result['file_name']}[/blue]\n"
        f"总行数: [bold]{result['total_rows']}[/bold]\n"
        f"成功: [green]{result['success_count']}[/green]\n"
        f"失败: [red]{result['failed_count']}[/red]",
        title="CSV 导入结果",
        border_style="green" if result["failed_count"] == 0 else "yellow",
    ))

    if result["failures"]:
        table = Table(title=f"失败明细 ({result['failed_count']} 行)", box=box.ROUNDED)
        table.add_column("行号", justify="right", style="cyan")
        table.add_column("发票号", style="magenta")
        table.add_column("错误信息", style="red")
        for f in result["failures"]:
            table.add_row(str(f["row_number"]), f["invoice_number"] or "-", f["error_message"])
        console.print(table)
        if result["report_path"]:
            console.print(f"[dim]失败报告已保存至: {result['report_path']}[/dim]")


@main.command("summary")
@click.option("--month", "-m", required=True, help="月份 (YYYY-MM)")
def summary_cmd(month: str):
    """月度汇总报表 - 按项目展示已报销与未报销金额"""
    data = services.monthly_summary(month)
    if not data:
        console.print(f"[yellow]{month} 月暂无数据[/yellow]")
        return

    table = Table(title=f"{month} 月度汇总（按项目）", box=box.ROUNDED, show_footer=True)
    table.add_column("项目", style="yellow", footer="合计")
    table.add_column("票据数", justify="right", style="cyan", footer=str(sum(d["receipt_count"] for d in data)))
    table.add_column("已报销", justify="right", style="green", footer=f"¥{sum(d['reimbursed_amount'] for d in data):.2f}")
    table.add_column("未报销", justify="right", style="red", footer=f"¥{sum(d['unreimbursed_amount'] for d in data):.2f}")
    table.add_column("总计", justify="right", style="bold", footer=f"¥{sum(d['total_amount'] for d in data):.2f}")

    for d in data:
        table.add_row(
            d["project"],
            str(d["receipt_count"]),
            f"¥{d['reimbursed_amount']:.2f}",
            f"¥{d['unreimbursed_amount']:.2f}",
            f"¥{d['total_amount']:.2f}",
        )
    console.print(table)


@main.command("batches")
@click.option("--failed-only", "-f", is_flag=True, help="仅显示有失败记录的批次")
def batches_cmd(failed_only: bool):
    """查看导入批次报表（含异常批次）"""
    batches = services.list_import_batches(only_failed=failed_only)
    if not batches:
        console.print("[yellow]暂无导入批次记录[/yellow]")
        return

    for b in batches:
        has_failure = b["failed_count"] > 0
        border_style = "red" if has_failure else "green"
        title = f"批次 #{b['id']} {'[异常]' if has_failure else ''}"

        info = (
            f"文件: [blue]{b['file_name']}[/blue]\n"
            f"时间: [dim]{b['imported_at']}[/dim]\n"
            f"总行数: [bold]{b['total_rows']}[/bold] | "
            f"成功: [green]{b['success_count']}[/green] | "
            f"失败: [red]{b['failed_count']}[/red]"
        )
        if b["report_path"]:
            info += f"\n报告: [dim]{b['report_path']}[/dim]"

        if has_failure and b["failures"]:
            fail_table = Table(box=box.SIMPLE, show_header=True)
            fail_table.add_column("行号", justify="right", style="cyan")
            fail_table.add_column("发票号", style="magenta")
            fail_table.add_column("错误", style="red")
            for f in b["failures"][:10]:
                fail_table.add_row(str(f["row_number"]), f["invoice_number"] or "-", f["error_message"])
            if len(b["failures"]) > 10:
                fail_table.add_row("…", "…", f"[dim]还有 {len(b['failures']) - 10} 条…[/dim]")
            console.print(Panel(Group(info, "", fail_table), title=title, border_style=border_style))
        else:
            console.print(Panel(info, title=title, border_style=border_style))


def _get_package_status_style(status: str) -> str:
    return {
        "pending": "bold yellow",
        "submitted": "bold green",
        "cancelled": "bold red",
    }.get(status, "bold")


def _get_package_status_text(status: str) -> str:
    return {
        "pending": "待提交",
        "submitted": "已提交",
        "cancelled": "已取消",
    }.get(status, status)


@main.group("package")
def package_group():
    """报销申请包管理

    批量筛选未报销票据生成待提交包，支持查看、提交、取消和导出CSV。
    已入待提交包或已报销的票据不能再加入其他待提交包。
    """
    pass


@package_group.command("create")
@click.option("--name", "-n", required=True, help="报销包名称")
@click.option("--desc", "-m", default=None, help="报销包描述")
@click.option("--project", "-p", default=None, help="按项目过滤")
@click.option("--month", "-mth", default=None, help="按月份过滤 (YYYY-MM)")
@click.option("--min-amount", "min_amount", type=float, default=None, help="最小金额")
@click.option("--max-amount", "max_amount", type=float, default=None, help="最大金额")
@click.option("--tag", "-t", "tags", multiple=True, help="按标签过滤（可多次指定）")
def package_create_cmd(name: str, desc: Optional[str], project: Optional[str],
                       month: Optional[str], min_amount: Optional[float],
                       max_amount: Optional[float], tags: tuple):
    """创建报销申请包（按条件筛选未报销票据）

    示例:
      pjgdcli package create -n "2026年6月差旅报销" -p 项目A -mth 2026-06 -t 差旅
    """
    try:
        pkg = services.create_package(
            name=name,
            description=desc,
            project=project,
            month=month,
            min_amount=min_amount,
            max_amount=max_amount,
            tags=list(tags) if tags else None,
        )
        console.print(f"[green]报销包创建成功！[/green] ID={pkg['id']}, 名称=[blue]{pkg['name']}[/blue]")
        console.print(f"  票据数: [bold]{len(pkg['receipts'])}[/bold] 张 | 总金额: [bold green]¥{pkg['total_amount']:.2f}[/bold green]")
        if pkg["tags"]:
            console.print(f"  标签: [dim]{', '.join(pkg['tags'])}[/dim]")
    except ValueError as e:
        console.print(f"[red]创建失败: {e}[/red]")
        sys.exit(1)


@package_group.command("list")
@click.option("--status", "-s", type=click.Choice(["pending", "submitted", "cancelled"]),
              default=None, help="按状态过滤")
def package_list_cmd(status: Optional[str]):
    """列出所有报销包"""
    packages = services.list_packages(status=status)
    if not packages:
        console.print("[yellow]暂无报销包[/yellow]")
        return

    table = Table(title="报销包列表", box=box.ROUNDED)
    table.add_column("ID", justify="right", style="cyan", no_wrap=True)
    table.add_column("名称", style="blue")
    table.add_column("状态", style="bold")
    table.add_column("票据数", justify="right", style="magenta")
    table.add_column("总金额", justify="right", style="green")
    table.add_column("标签", style="dim")
    table.add_column("创建时间", style="white")
    table.add_column("提交时间", style="white")

    for pkg in packages:
        status_style = _get_package_status_style(pkg["status"])
        status_text = _get_package_status_text(pkg["status"])
        tags = ", ".join(pkg.get("tags", []))
        table.add_row(
            str(pkg["id"]),
            pkg["name"],
            f"[{status_style}]{status_text}[/{status_style}]",
            str(pkg["receipt_count"]),
            f"¥{pkg['total_amount']:.2f}",
            tags,
            pkg["created_at"],
            pkg.get("submitted_at") or "-",
        )
    console.print(table)


@package_group.command("view")
@click.argument("package_id", type=int)
def package_view_cmd(package_id: int):
    """查看报销包详情（含票据快照）"""
    pkg = services.get_package(package_id)
    if not pkg:
        console.print(f"[red]报销包 ID={package_id} 不存在[/red]")
        sys.exit(1)

    status_style = _get_package_status_style(pkg["status"])
    status_text = _get_package_status_text(pkg["status"])
    tags = ", ".join(pkg.get("tags", []))

    info = Panel(
        f"名称: [bold blue]{pkg['name']}[/bold blue]\n"
        f"状态: [{status_style}]{status_text}[/{status_style}]\n"
        f"票据数: [bold]{len(pkg['receipts'])}[/bold] 张\n"
        f"总金额: [bold green]¥{pkg['total_amount']:.2f}[/bold green]\n"
        f"标签: [dim]{tags or '-'}[/dim]\n"
        f"描述: [dim]{pkg.get('description') or '-'}[/dim]\n"
        f"创建时间: {pkg['created_at']}\n"
        f"更新时间: {pkg['updated_at']}\n"
        f"提交时间: {pkg.get('submitted_at') or '-'}",
        title=f"报销包 #{pkg['id']}",
        border_style="blue",
    )
    console.print(info)

    if pkg["receipts"]:
        table = Table(title="包内票据快照", box=box.ROUNDED, show_lines=False)
        table.add_column("票据ID", justify="right", style="cyan")
        table.add_column("发票号", style="magenta")
        table.add_column("金额", justify="right", style="green")
        table.add_column("日期", style="blue")
        table.add_column("项目", style="yellow")
        table.add_column("标签", style="white")
        table.add_column("备注", style="dim")

        for pr in pkg["receipts"]:
            pr_tags = ", ".join(pr.get("tags", []))
            table.add_row(
                str(pr["receipt_id"]),
                pr["invoice_number"],
                f"¥{pr['amount']:.2f}",
                pr["date"],
                pr["project"],
                pr_tags,
                pr.get("description") or "",
            )
        console.print(table)


@package_group.command("submit")
@click.argument("package_id", type=int)
def package_submit_cmd(package_id: int):
    """提交报销包（将包内所有票据标记为已报销）"""
    try:
        pkg = services.submit_package(package_id)
        console.print(f"[green]报销包提交成功！[/green] ID={pkg['id']}, 名称=[blue]{pkg['name']}[/blue]")
        console.print(f"  已将 [bold]{len(pkg['receipts'])}[/bold] 张票据标记为已报销，总金额: [bold green]¥{pkg['total_amount']:.2f}[/bold green]")
    except ValueError as e:
        console.print(f"[red]提交失败: {e}[/red]")
        sys.exit(1)


@package_group.command("cancel")
@click.argument("package_id", type=int)
def package_cancel_cmd(package_id: int):
    """取消报销包（释放包内票据，可重新入包）"""
    try:
        pkg = services.cancel_package(package_id)
        console.print(f"[green]报销包已取消[/green] ID={pkg['id']}, 名称=[blue]{pkg['name']}[/blue]")
        console.print(f"  [dim]包内 {len(pkg['receipts'])} 张票据已释放，可重新加入其他报销包[/dim]")
    except ValueError as e:
        console.print(f"[red]取消失败: {e}[/red]")
        sys.exit(1)


@package_group.command("export")
@click.argument("package_id", type=int)
@click.option("--output", "-o", "output_path", required=True, type=click.Path(dir_okay=False),
              help="输出CSV文件路径")
def package_export_cmd(package_id: int, output_path: str):
    """导出报销包为CSV文件"""
    try:
        result = services.export_package_csv(package_id, output_path)
        console.print(f"[green]导出成功！[/green] 文件已保存至: [blue]{result}[/blue]")
    except ValueError as e:
        console.print(f"[red]导出失败: {e}[/red]")
        sys.exit(1)


@main.command("history")
@click.argument("receipt_id", type=int)
def history_cmd(receipt_id: int):
    """查看票据状态变更历史"""
    receipt = services.get_receipt_by_id(receipt_id)
    if not receipt:
        console.print(f"[red]票据 ID={receipt_id} 不存在[/red]")
        sys.exit(1)

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM status_history
            WHERE receipt_id = ? ORDER BY id ASC
            """,
            (receipt_id,),
        ).fetchall()

    console.print(f"[bold]票据 ID={receipt_id} (发票号: {receipt['invoice_number']}) 状态历史[/bold]")
    if not rows:
        console.print("[dim]暂无状态变更记录[/dim]")
        return

    table = Table(box=box.ROUNDED)
    table.add_column("序号", justify="right", style="cyan")
    table.add_column("原状态", style="red")
    table.add_column("新状态", style="green")
    table.add_column("变更时间", style="blue")

    for i, row in enumerate(rows, 1):
        old = "已报销" if row["old_status"] == "reimbursed" else "未报销"
        new = "已报销" if row["new_status"] == "reimbursed" else "未报销"
        table.add_row(str(i), old, new, row["changed_at"])
    console.print(table)


if __name__ == "__main__":
    main()
