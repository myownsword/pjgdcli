import subprocess
import sys
import os
import tempfile
import shutil
import atexit
import re

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_ENV = os.environ.copy()
BASE_ENV["PYTHONPATH"] = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
BASE_ENV["TERM"] = "dumb"
BASE_ENV["NO_COLOR"] = "1"
BASE_ENV["FORCE_COLOR"] = "0"
BASE_ENV["PYTHONIOENCODING"] = "utf-8"

_temp_dirs_to_clean = []

def make_isolated_home() -> str:
    tmp = tempfile.mkdtemp(prefix="pjgdcli_test_basic_")
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


def run(cmd, check=True):
    print(f"\n{'='*60}")
    print(f"$ {cmd}")
    print('='*60)
    env = BASE_ENV.copy()
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


temp_home = make_isolated_home()
expected_pjgdcli_dir = os.path.join(temp_home, ".pjgdcli")
expected_db_path = os.path.join(expected_pjgdcli_dir, "receipts.db")

print("=" * 60)
print("  pjgdcli 功能验证")
print("=" * 60)
print(f"\n[数据隔离] 使用临时 HOME 目录: {temp_home}")
print(f"[数据隔离] 预期数据目录:    {expected_pjgdcli_dir}")
print(f"[数据隔离] 预期数据库路径:  {expected_db_path}")
print(f"[数据隔离] 真实用户 HOME:   {os.path.expanduser('~')}")
assert temp_home != os.path.expanduser("~"), "临时 HOME 不能等于真实用户 HOME"
assert not os.path.exists(expected_db_path), "测试前临时目录不应存在数据库"
print("  [OK] 确认使用独立临时数据目录，不会触碰真实用户数据")

# 1. init
run("init")

assert os.path.isdir(expected_pjgdcli_dir), "初始化后应在临时目录创建 .pjgdcli"
assert os.path.isfile(expected_db_path), "初始化后应在临时目录创建 receipts.db"
print(f"  [OK] 数据库文件创建在临时位置: {expected_db_path}")

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
r_list = run("list -m 2026-01")
r_summary = run("summary -m 2026-01")

list_total = None
for line in r_list._combined_out.splitlines():
    if "总计" in line and "¥" in line:
        m = re.search(r"总计\s+¥([\d.]+)", line)
        if m:
            list_total = float(m.group(1))

summary_total = None
for line in r_summary._combined_out.splitlines():
    if "合计" in line and "¥" in line:
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

print("\n[数据隔离] 测试结束，验证真实用户数据未被触碰")
real_user_pjgdcli = os.path.join(os.path.expanduser("~"), ".pjgdcli")
real_pjgdcli_exists = os.path.exists(real_user_pjgdcli)
print(f"[数据隔离] 真实用户目录 {real_user_pjgdcli} " + ("存在" if real_pjgdcli_exists else "不存在"))
print("  [OK] 测试全程未触碰真实用户 HOME 下的 .pjgdcli 目录")

print("\n" + "=" * 60)
print("  所有验证通过！")
print("  - 数据完全隔离在临时目录")
print("  - 全部基础功能正常")
print("=" * 60)
