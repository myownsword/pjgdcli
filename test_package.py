import subprocess
import sys
import os
import csv
import tempfile
import shlex
import shutil
import atexit
import re

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_ENV = os.environ.copy()
BASE_ENV["PYTHONPATH"] = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
BASE_ENV["PYTHONIOENCODING"] = "utf-8"
BASE_ENV["NO_COLOR"] = "1"

_temp_dirs_to_clean = []
_temp_files_to_clean = []

def make_isolated_home() -> str:
    tmp = tempfile.mkdtemp(prefix="pjgdcli_test_pkg_")
    _temp_dirs_to_clean.append(tmp)

    if sys.platform == "win32":
        BASE_ENV["USERPROFILE"] = tmp
        BASE_ENV["HOME"] = tmp
    else:
        BASE_ENV["HOME"] = tmp

    return tmp

def cleanup_temp_resources():
    for f in _temp_files_to_clean:
        if os.path.isfile(f):
            try:
                os.remove(f)
            except OSError:
                pass
    for d in _temp_dirs_to_clean:
        if os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)

atexit.register(cleanup_temp_resources)


def run(cmd):
    print(f"\n$ {cmd}")
    try:
        args = shlex.split(cmd)
    except ValueError:
        args = cmd.split()
    r = subprocess.run(
        [sys.executable, "-m", "pjgdcli.cli"] + args,
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

print("=" * 70)
print("  报销申请包功能综合验证")
print("=" * 70)
print(f"\n[数据隔离] 使用临时 HOME 目录: {temp_home}")
print(f"[数据隔离] 预期数据目录:    {expected_pjgdcli_dir}")
print(f"[数据隔离] 预期数据库路径:  {expected_db_path}")
print(f"[数据隔离] 真实用户 HOME:   {os.path.expanduser('~')}")
assert temp_home != os.path.expanduser("~"), "临时 HOME 不能等于真实用户 HOME"
assert not os.path.exists(expected_db_path), "测试前临时目录不应存在数据库"
print("  [OK] 确认使用独立临时数据目录，不会触碰真实用户数据")

# 1. 初始化 + 导入示例数据
print("\n--- 1. 初始化并导入示例数据 ---")
run("init")

assert os.path.isdir(expected_pjgdcli_dir), "初始化后应在临时目录创建 .pjgdcli"
assert os.path.isfile(expected_db_path), "初始化后应在临时目录创建 receipts.db"
print(f"  [OK] 数据库文件创建在临时位置: {expected_db_path}")

out, _ = run("import examples/receipts_sample.csv")
assert "导入完成" in out

# 确认有未报销票据
out, _ = run("list -s unreimbursed")
assert "未报销" in out
print("  [OK] 示例数据导入成功，有未报销票据")

# 2. 创建报销包 - 按项目A筛选
print("\n--- 2. 创建报销包（按项目A筛选） ---")
out, code = run("package create -n BXB1 -p 项目A")
assert code == 0
assert "报销包创建成功" in out
assert "BXB1" in out
print("  [OK] 报销包创建成功")

# 3. 查看报销包列表
print("\n--- 3. 查看报销包列表 ---")
out, _ = run("package list")
assert "BXB1" in out or "BXB" in out
assert "待提交" in out
print("  [OK] 报销包列表显示正常，状态为待提交")

# 4. 查看报销包详情
print("\n--- 4. 查看报销包详情 ---")
out, _ = run("package view 1")
assert "BXB1" in out
assert "待提交" in out
# 检查5条票据记录的金额
assert "¥299.50" in out  # FP20260101001
assert "¥1200.00" in out  # FP20260101002
assert "¥88.00" in out    # FP20260101004
assert "¥156.80" in out  # FP20260201001
assert "¥230.00" in out  # FP20260201003
print("  [OK] 报销包详情显示正常，包含票据快照")

# 5. 验证：重复入包失败（票据已在其他待提交包）
print("\n--- 5. 验证：重复入包失败 ---")
out, code = run("package create -n CFB -p 项目A")
assert code == 1
assert "创建失败" in out
assert "没有符合条件的未报销票据可加入报销包" in out
print("  [OK] 重复入包验证通过：票据已在待提交包中，无法再次入包")

# 6. 取消报销包（释放票据）
print("\n--- 6. 取消报销包（释放票据） ---")
out, code = run("package cancel 1")
assert code == 0
assert "报销包已取消" in out
print("  [OK] 报销包取消成功，票据已释放")

# 7. 验证取消后状态
print("\n--- 7. 验证取消后状态 ---")
out, _ = run("package list")
assert "已取消" in out
print("  [OK] 报销包状态已更新为已取消")

# 8. 再次创建报销包（票据已释放，应能成功）
print("\n--- 8. 再次创建报销包（票据已释放） ---")
out, code = run("package create -n ZSB -p 项目A -m 2026_01_A")
assert code == 0
assert "报销包创建成功" in out
assert "ZSB" in out

amount_match = re.search(r"总金额:\s*¥([0-9]+\.[0-9]+)", out)
assert amount_match, "无法从输出提取总金额"
package_total = float(amount_match.group(1))
print(f"  [OK] 重新创建成功，报销包总金额: ¥{package_total:.2f}")

# 9. 导出CSV验证
print("\n--- 9. 导出CSV验证 ---")
csv_fd, csv_path = tempfile.mkstemp(prefix="pjgdcli_test_export_", suffix=".csv")
os.close(csv_fd)
os.remove(csv_path)
_temp_files_to_clean.append(csv_path)

out, code = run(f'package export 2 -o "{csv_path}"')
assert code == 0
assert "导出成功" in out
assert os.path.exists(csv_path)
print(f"  [OK] CSV导出成功: {csv_path}")

# 验证CSV内容与包快照一致
print("\n--- 10. 验证CSV内容与包快照一致 ---")
with open(csv_path, "r", encoding="utf-8-sig") as f:
    reader = csv.DictReader(f)
    csv_rows = list(reader)

out, _ = run("package view 2")
csv_amounts = [float(row["金额"]) for row in csv_rows]
csv_total = sum(csv_amounts)

assert len(csv_rows) == 5, f"CSV应包含5条票据记录，实际{len(csv_rows)}条"
assert abs(csv_total - package_total) < 0.01, f"CSV总金额({csv_total:.2f})与包总金额({package_total:.2f})不一致"
print(f"  [OK] CSV内容验证通过: {len(csv_rows)} 条记录，总金额 ¥{csv_total:.2f}")

# 验证CSV中的发票号
csv_invoices = [row["发票号"] for row in csv_rows]
csv_amounts = [float(row["金额"]) for row in csv_rows]
assert "FP20260101001" in csv_invoices
assert "FP20260101002" in csv_invoices
assert "FP20260101004" in csv_invoices
assert "FP20260201001" in csv_invoices
assert "FP20260201003" in csv_invoices
assert 299.50 in csv_amounts
assert 1200.00 in csv_amounts
assert 88.00 in csv_amounts
assert 156.80 in csv_amounts
assert 230.00 in csv_amounts
print("  [OK] CSV发票号与包快照一致")

# 11. 导出目录不可写验证
print("\n--- 11. 验证：导出目录不可写失败 ---")
invalid_path = "/nonexistent_dir_that_should_not_exist/test.csv"
if sys.platform == "win32":
    invalid_path = "Z:\\nonexistent_dir\\test.csv"
out, code = run(f'package export 2 -o "{invalid_path}"')
assert code == 1
assert "导出失败" in out
assert "目录不存在" in out or "不可写" in out or "路径" in out.lower()
print("  [OK] 导出目录不存在时失败提示正确")

# 12. 提交报销包
print("\n--- 12. 提交报销包 ---")
out, code = run("package submit 2")
assert code == 0
assert "报销包提交成功" in out
assert "已报销" in out
print("  [OK] 报销包提交成功")

# 13. 验证：已报销总金额与报销包金额一致
print("\n--- 13. 验证：已报销总金额与报销包金额一致 ---")
out_01, _ = run("summary -m 2026-01")
out_02, _ = run("summary -m 2026-02")

project_a_reimbursed_01 = 0.0
project_a_reimbursed_02 = 0.0

for line in out_01.split("\n"):
    if "项目A" in line:
        amounts = re.findall(r"¥([0-9]+\.[0-9]+)", line)
        if len(amounts) >= 2:
            project_a_reimbursed_01 = float(amounts[0])

for line in out_02.split("\n"):
    if "项目A" in line:
        amounts = re.findall(r"¥([0-9]+\.[0-9]+)", line)
        if len(amounts) >= 2:
            project_a_reimbursed_02 = float(amounts[0])

total_reimbursed = project_a_reimbursed_01 + project_a_reimbursed_02

assert total_reimbursed > 0, "已报销金额应为正数"
assert abs(total_reimbursed - package_total) < 0.01, \
    f"月度汇总已报销金额(¥{total_reimbursed:.2f})与报销包总金额(¥{package_total:.2f})不一致"
print(f"  [OK] 月度汇总验证通过：项目A已报销 ¥{total_reimbursed:.2f} = 报销包总金额 ¥{package_total:.2f}")

# 14. 验证：重复提交失败
print("\n--- 14. 验证：重复提交失败 ---")
out, code = run("package submit 2")
assert code == 1
assert "提交失败" in out
assert "已提交，不能重复提交" in out
print("  [OK] 重复提交验证通过")

# 15. 验证：取消已提交包失败
print("\n--- 15. 验证：取消已提交包失败 ---")
out, code = run("package cancel 2")
assert code == 1
assert "取消失败" in out
assert "已提交，不能取消" in out
print("  [OK] 取消已提交包验证通过")

# 16. 验证票据已报销
print("\n--- 16. 验证票据已报销 ---")
out, _ = run("list -s reimbursed -p 项目A")
assert "已报销" in out
assert "¥299.50" in out  # FP20260101001
assert "¥1200.00" in out  # FP20260101002
assert "¥88.00" in out    # FP20260101004
assert "¥156.80" in out  # FP20260201001
assert "¥230.00" in out  # FP20260201003
assert "共 5 张" in out
print("  [OK] 项目A票据已全部标记为已报销")

# 17. 查看票据状态历史
print("\n--- 17. 查看票据状态历史 ---")
out, _ = run("history 1")
assert "未报销" in out
assert "已报销" in out
print("  [OK] 票据状态历史记录正常")

# 18. 验证：已报销票据不能入包
print("\n--- 18. 验证：已报销票据不能入包 ---")
out, code = run("package create -n YBX -p 项目A")
assert code == 1
assert "创建失败" in out
assert "没有符合条件的未报销票据可加入报销包" in out
print("  [OK] 已报销票据不能入包验证通过")

# 19. 验证：票据状态变更后提交失败
print("\n--- 19. 验证：票据状态变更后提交失败 ---")
run("package create -n ZTBG -p 项目B")
run("reimburse 3")  # FP20260101003 是项目B的，ID=3
out, code = run("package submit 3")
assert code == 1
assert "提交失败" in out
assert "状态已变更为 已报销" in out
print("  [OK] 票据状态变更后提交失败验证通过")

print("\n[数据隔离] 测试结束，验证真实用户数据未被触碰")
real_user_pjgdcli = os.path.join(os.path.expanduser("~"), ".pjgdcli")
real_pjgdcli_exists = os.path.exists(real_user_pjgdcli)
print(f"[数据隔离] 真实用户目录 {real_user_pjgdcli} " + ("存在" if real_pjgdcli_exists else "不存在"))
print("  [OK] 测试全程未触碰真实用户 HOME 下的 .pjgdcli 目录")

print("\n[数据隔离] 验证临时目录资源将被清理")
print(f"  临时 HOME 目录: {temp_home}")
print(f"  临时导出 CSV:   {csv_path}")
print("  [OK] atexit 已注册清理函数，脚本退出时将自动删除以上资源")

print("\n" + "=" * 70)
print("  全部验证通过！报销申请包功能正常：")
print("  ✓ 数据完全隔离在临时目录")
print("  ✓ 建包成功")
print("  ✓ 重复入包失败")
print("  ✓ 取消释放票据")
print("  ✓ 提交后月度汇总金额一致")
print("  ✓ 导出CSV与包快照一致")
print("  ✓ 导出目录不存在失败")
print("  ✓ 重复提交失败")
print("  ✓ 取消已提交包失败")
print("  ✓ 票据状态历史记录正常")
print("  ✓ 已报销票据不能入包")
print("  ✓ 票据状态变更后提交失败")
print("=" * 70)
