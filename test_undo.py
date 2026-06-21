import subprocess
import sys
import os

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

os.environ["PYTHONPATH"] = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["NO_COLOR"] = "1"

def run(cmd):
    print(f"\n$ {cmd}")
    r = subprocess.run(
        [sys.executable, "-m", "pjgdcli.cli"] + cmd.split(),
        capture_output=True,
        env=os.environ.copy(),
    )
    out = r.stdout.decode("utf-8", errors="replace").strip()
    err = r.stderr.decode("utf-8", errors="replace").strip()
    if out:
        print(out)
    if err:
        print("STDERR:", err)
    print(f"(exit {r.returncode})")
    return out + "\n" + err, r.returncode

# 清理并初始化
p = os.path.expanduser("~/.pjgdcli")
import shutil
if os.path.exists(p):
    shutil.rmtree(p)

print("=" * 60)
print("  撤销功能验证（连续两次撤销）")
print("=" * 60)

# 1. 初始化 + 新增
run("init")
run("add -i FP001 -a 100.00 -d 2026-06-01 -p 项目A -m 测试撤销")

# 2. 查看初始状态（未报销）
out, _ = run("list")
assert "未报销" in out, "初始状态应为未报销"

# 3. 标记为已报销
out, _ = run("reimburse 1")
assert "已标记为已报销" in out

# 4. 查询确认已报销
out, _ = run("list -s reimbursed")
assert "已报销" in out and "FP001" in out
print("  [OK] 报销后状态=已报销")

# 5. 第一次撤销
out, code = run("undo 1")
assert code == 0
assert "已撤销状态变更" in out
assert "未报销" in out
print("  [OK] 第一次撤销成功，状态恢复为未报销")

# 6. 查询确认状态
out, _ = run("list -s unreimbursed")
assert "未报销" in out and "FP001" in out
print("  [OK] 第一次撤销后状态查询确认=未报销")

# 7. 第二次撤销 —— 应失败提示没有可撤销的历史
out, code = run("undo 1")
assert code == 0, "第二次撤销虽然没历史但不应抛异常"
assert "没有可撤销的状态变更历史" in out, f"应提示没有可撤销历史，实际输出: {out}"
print("  [OK] 第二次撤销给出合理提示：没有可撤销的状态变更历史")

# 8. 状态应保持不变（仍是未报销）
out, _ = run("list -s unreimbursed")
assert "未报销" in out and "FP001" in out
out_reimbursed, _ = run("list -s reimbursed")
assert "FP001" not in out_reimbursed
print("  [OK] 第二次撤销后状态保持不变（仍是未报销）")

# 9. 再做一次报销 -> 撤销 -> 再报销 -> 撤销，验证有历史就能撤销，撤销完就不能再撤销
print("\n--- 额外验证：报销->撤销->报销->撤销 各两次 ---")
run("reimburse 1")   # 第2次报销
run("undo 1")        # 撤销（删除第2条历史）
out, code = run("undo 1")  # 第二次撤销 —— 应失败
assert "没有可撤销的状态变更历史" in out
print("  [OK] 第二轮报销-撤销后，第二次撤销同样提示无历史")

print("\n" + "=" * 60)
print("  全部验证通过！撤销行为正确：")
print("  - 只有一次可撤销历史")
print("  - 撤销后历史被删除，不能再次撤销")
print("  - 状态保持不变")
print("=" * 60)
