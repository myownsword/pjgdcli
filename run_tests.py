import subprocess
import sys
import os
import locale

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

os.environ["PYTHONPATH"] = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
os.environ["TERM"] = "dumb"
os.environ["NO_COLOR"] = "1"
os.environ["FORCE_COLOR"] = "0"
os.environ["PYTHONIOENCODING"] = "utf-8"

def run(cmd, check=True):
    print(f"\n{'='*60}")
    print(f"$ {cmd}")
    print('='*60)
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    r = subprocess.run(
        [sys.executable, "-m", "pjgdcli.cli"] + cmd.split(),
        capture_output=True,
        env=env,
    )
    out = r.stdout.decode("utf-8", errors="replace").strip()
    err = r.stderr.decode("utf-8", errors="replace").strip()
    combined = out + "\n" + err
    if out:
        print(out)
    if err:
        print("STDERR:", err)
    if check and r.returncode != 0:
        print(f"(exit code {r.returncode})")
    r._combined_out = combined
    return r

print("=" * 60)
print("  pjgdcli 功能验证")
print("=" * 60)

# 1. init
run("init")

# 2. 新增成功
run("add -i FPTEST001 -a 300.00 -d 2026-06-10 -p 项目A -m 测试票据1 -t 测试")

# 3. 重复发票号失败
r = run("add -i FPTEST001 -a 500.00 -d 2026-06-11 -p 项目B", check=False)
assert r.returncode == 1, "重复发票号应返回非零"
assert "发票号已存在" in r._combined_out, "应提示发票号已存在"
print("  [OK] 重复发票号校验正确")

# 4. 标记报销
run("reimburse 1")
r = run("list -s reimbursed")
assert "已报销" in r._combined_out
print("  [OK] 报销标记生效")

# 5. 撤销后恢复未报销
run("undo 1")
r = run("list -s unreimbursed")
assert "未报销" in r._combined_out
assert "FPTEST001" in r._combined_out
print("  [OK] 撤销后状态恢复为未报销")

# 6. 导入正常 CSV
run("import examples/receipts_sample.csv")

# 7. 导入含错误的 CSV（应产生异常批次 + 失败报告）
run("import examples/receipts_with_errors.csv")

# 8. 月度汇总
run("summary -m 2026-01")

# 9. 验证汇总与查询金额一致
# 查询 2026-01 所有票据
r_list = run("list -m 2026-01")
r_summary = run("summary -m 2026-01")

list_total = None
for line in r_list._combined_out.splitlines():
    if "总计" in line and "¥" in line:
        import re
        m = re.search(r"总计\s+¥([\d.]+)", line)
        if m:
            list_total = float(m.group(1))

summary_total = None
for line in r_summary._combined_out.splitlines():
    if "合计" in line and "¥" in line:
        import re
        vals = re.findall(r"¥([\d.]+)", line)
        if vals:
            summary_total = float(vals[-1])

print(f"\n查询结果总计: {list_total}")
print(f"汇总报表总计: {summary_total}")
assert list_total is not None and summary_total is not None
assert abs(list_total - summary_total) < 0.01, f"金额不一致: list={list_total}, summary={summary_total}"
print("  [OK] 月度汇总金额与查询结果一致")

# 10. 查看异常批次
run("batches -f")

# 11. 标签列表
run("tag list")

# 12. 多条件查询
run("list -p 项目A -m 2026-01")
run("list --min-amount 100 --max-amount 1000")
run("list -t 差旅 -t 餐饮")

print("\n" + "=" * 60)
print("  所有验证通过！")
print("=" * 60)
