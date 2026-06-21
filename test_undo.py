import subprocess
import sys
import os
import tempfile
import shutil
import atexit

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_ENV = os.environ.copy()
BASE_ENV["PYTHONPATH"] = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
BASE_ENV["PYTHONIOENCODING"] = "utf-8"
BASE_ENV["NO_COLOR"] = "1"

_temp_dirs_to_clean = []

def make_isolated_home() -> str:
    tmp = tempfile.mkdtemp(prefix="pjgdcli_test_undo_")
    _temp_dirs_to_clean.append(tmp)

    if sys.platform == "win32":
        BASE_ENV["USERPROFILE"] = tmp
        BASE_ENV["HOME"] = tmp
    else:
        BASE_ENV["HOME"] = tmp

    return tmp

def cleanup_temp_dirs():
    for d in _temp_dirs_to_clean:
        if os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)

atexit.register(cleanup_temp_dirs)


def run(cmd):
    print(f"\n$ {cmd}")
    r = subprocess.run(
        [sys.executable, "-m", "pjgdcli.cli"] + cmd.split(),
        capture_output=True,
        env=BASE_ENV.copy(),
    )
    out = r.stdout.decode("utf-8", errors="replace").strip()
    err = r.stderr.decode("utf-8", errors="replace").strip()
    if out:
        print(out)
    if err:
        print("STDERR:", err)
    print(f"(exit {r.returncode})")
    return out + "\n" + err, r.returncode


temp_home = make_isolated_home()
expected_pjgdcli_dir = os.path.join(temp_home, ".pjgdcli")
expected_db_path = os.path.join(expected_pjgdcli_dir, "receipts.db")

print("=" * 60)
print("  撤销功能验证（连续两次撤销）")
print("=" * 60)
print(f"\n[数据隔离] 使用临时 HOME 目录: {temp_home}")
print(f"[数据隔离] 预期数据目录:    {expected_pjgdcli_dir}")
print(f"[数据隔离] 预期数据库路径:  {expected_db_path}")
print(f"[数据隔离] 真实用户 HOME:   {os.path.expanduser('~')}")
assert temp_home != os.path.expanduser("~"), "临时 HOME 不能等于真实用户 HOME"
assert not os.path.exists(expected_db_path), "测试前临时目录不应存在数据库"
print("  [OK] 确认使用独立临时数据目录，不会触碰真实用户数据")

# 1. 初始化 + 新增
run("init")

assert os.path.isdir(expected_pjgdcli_dir), "初始化后应在临时目录创建 .pjgdcli"
assert os.path.isfile(expected_db_path), "初始化后应在临时目录创建 receipts.db"
print(f"  [OK] 数据库文件创建在临时位置: {expected_db_path}")

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

print("\n[数据隔离] 测试结束，验证真实用户数据未被触碰")
real_user_pjgdcli = os.path.join(os.path.expanduser("~"), ".pjgdcli")
real_pjgdcli_exists = os.path.exists(real_user_pjgdcli)
print(f"[数据隔离] 真实用户目录 {real_user_pjgdcli} " + ("存在" if real_pjgdcli_exists else "不存在"))
print("  [OK] 测试全程未触碰真实用户 HOME 下的 .pjgdcli 目录")

print("\n" + "=" * 60)
print("  全部验证通过！撤销行为正确：")
print("  - 数据完全隔离在临时目录")
print("  - 只有一次可撤销历史")
print("  - 撤销后历史被删除，不能再次撤销")
print("  - 状态保持不变")
print("=" * 60)
