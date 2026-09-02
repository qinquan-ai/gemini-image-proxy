"""
完整的 Cookie 过期检测与自动刷新流程测试
模拟真实场景：Cookie 过期 → 检测失败 → 自动刷新 → 验证成功
"""
import subprocess
import time
from pathlib import Path

def run_command(cmd: list[str], cwd: Path) -> tuple[int, str]:
    """运行命令并返回退出码和输出"""
    result = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace'
    )
    return result.returncode, result.stdout + result.stderr

def main():
    project_root = Path(__file__).parent.parent
    env_file = project_root / ".env"
    backup_file = project_root / ".env.backup"
    
    print("\n" + "=" * 60)
    print("Cookie 过期检测与自动刷新完整流程测试")
    print("=" * 60 + "\n")
    
    start_time = time.time()
    
    # 1. 备份当前有效 Cookie
    print("[1/5] 备份当前有效 Cookie...")
    env_content = env_file.read_text(encoding='utf-8')
    backup_file.write_text(env_content, encoding='utf-8')
    
    # 2. 写入格式正确但已过期的假 Cookie
    print("[2/5] 写入假的过期 Cookie（模拟真实过期场景）\n")
    fake_cookie = "__Secure-1PSID=fake_expired_value; __Secure-1PSIDTS=expired_timestamp"
    modified_env = ""
    for line in env_content.splitlines():
        if line.startswith("GOOGLE_COOKIES="):
            modified_env += f"GOOGLE_COOKIES={fake_cookie}\n"
        else:
            modified_env += line + "\n"
    env_file.write_text(modified_env, encoding='utf-8')
    
    # 3. 检测登录状态（预期失败）
    print("[3/5] 检测登录状态（预期：FAILED）")
    check1_start = time.time()
    exit_code1, output1 = run_command(
        ["python", "scripts/check_gemini_login.py"],
        project_root
    )
    check1_time = time.time() - check1_start
    
    status1 = "FAILED" if exit_code1 == 1 else "AUTHENTICATED"
    status1_ok = status1 == "FAILED"
    print(f"  检测结果: {status1} {'(符合预期)' if status1_ok else '(异常)'}")
    print(f"  耗时: {check1_time:.2f} 秒\n")
    
    # 4. 自动刷新 Cookie
    print("[4/5] 自动刷新 Cookie（选择 Profile 1: qin16778@gmail.com）")
    refresh_start = time.time()
    exit_code2, output2 = run_command(
        ["python", "scripts/update_cookies.py"],
        project_root
    )
    # 通过 stdin 传入选择
    proc = subprocess.Popen(
        ["python", "scripts/update_cookies.py"],
        cwd=project_root,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding='utf-8',
        errors='replace'
    )
    output2, _ = proc.communicate(input="1\n")
    refresh_time = time.time() - refresh_start
    
    refresh_success = "Updated" in output2 and "Google cookies" in output2
    print(f"  刷新结果: {'SUCCESS' if refresh_success else 'FAILED'}")
    print(f"  耗时: {refresh_time:.2f} 秒\n")
    
    # 5. 重新验证登录状态（预期成功）
    print("[5/5] 重新验证登录状态（预期：AUTHENTICATED）")
    check2_start = time.time()
    exit_code3, output3 = run_command(
        ["python", "scripts/check_gemini_login.py"],
        project_root
    )
    check2_time = time.time() - check2_start
    
    status2 = "AUTHENTICATED" if exit_code3 == 0 else "FAILED"
    status2_ok = status2 == "AUTHENTICATED"
    print(f"  检测结果: {status2} {'(符合预期)' if status2_ok else '(异常)'}")
    print(f"  耗时: {check2_time:.2f} 秒\n")
    
    # 总结
    total_time = time.time() - start_time
    print("=" * 60)
    print("流程完成")
    print("=" * 60)
    print(f"总耗时: {total_time:.2f} 秒 (约 {total_time/60:.2f} 分钟)\n")
    print("分项耗时:")
    print(f"  [检测失效] {check1_time:.2f} 秒")
    print(f"  [刷新Cookie] {refresh_time:.2f} 秒")
    print(f"  [验证成功] {check2_time:.2f} 秒\n")
    
    within_2min = total_time < 120
    conclusion_text = "可在 2 分钟内完成" if within_2min else f"超过 2 分钟 ({total_time/60:.1f} 分钟)"
    print(f"结论: {conclusion_text}\n")
    
    # 恢复备份
    print("[清理] 恢复原始 Cookie...")
    backup_content = backup_file.read_text(encoding='utf-8')
    env_file.write_text(backup_content, encoding='utf-8')
    backup_file.unlink()
    print("已恢复\n")

if __name__ == "__main__":
    main()
