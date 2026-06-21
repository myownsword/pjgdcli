import sys
from typing import List, Optional

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.console import Group
from rich import box

from .database import init_db, get_db_path
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


if __name__ == "__main__":
    main()
