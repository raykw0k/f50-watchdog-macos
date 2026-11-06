#!/usr/bin/env python3
"""Install or remove the system LaunchDaemon on the destination Mac only."""
import argparse
import getpass
import json
import os
from pathlib import Path
import plistlib
import pwd
import shutil
import subprocess
import sys

from f50_watchdog import interface_for, ping, validate_device

LABEL = 'local.f50.watchdog'
BASE = Path('/Library/Application Support/F50Watchdog')
PLIST = Path('/Library/LaunchDaemons/' + LABEL + '.plist')


def launch_spec(python, user):
    return {
        'Label': LABEL,
        'ProgramArguments': [python, str(BASE / 'f50_watchdog.py'),
                             '--config', str(BASE / 'config.json')],
        'UserName': user,
        'RunAtLoad': True,
        'KeepAlive': True,
        'ThrottleInterval': 30,
        'ProcessType': 'Background',
        'WorkingDirectory': str(BASE),
        'EnvironmentVariables': {'PYTHONUNBUFFERED': '1', 'PYTHONDONTWRITEBYTECODE': '1'},
        'StandardOutPath': str(BASE / 'state' / 'service.out'),
        'StandardErrorPath': str(BASE / 'state' / 'service.err'),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python', default=sys.executable)
    parser.add_argument('--uninstall', action='store_true')
    args = parser.parse_args()
    if sys.platform != 'darwin' or os.geteuid() != 0:
        raise SystemExit('请在目标 Mac 上运行 bash install.sh（使用 sudo）。')
    if args.uninstall:
        subprocess.run(['/bin/launchctl', 'bootout', 'system/' + LABEL],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        PLIST.unlink(missing_ok=True)
        print('已停止并移除开机启动；配置、日志及保护状态仍保留在 ' + str(BASE))
        return
    user = os.environ.get('SUDO_USER')
    if not user or user == 'root':
        raise SystemExit('请用普通管理员账户运行 bash install.sh，不要从 root 登录会话安装。')
    account = pwd.getpwnam(user)
    python = os.path.abspath(args.python)
    # Ensure launchd can execute the interpreter as the actual service account.
    subprocess.run(['/usr/bin/sudo', '-u', user, python, '-c',
                    'import sys; assert sys.version_info >= (3,9)'], check=True)
    print('安装前检查：请将 F50 插回这台 Mac。不会主动重启设备。')
    device = validate_device('192.168.0.1')
    interface = interface_for('192.168.0.1')
    if not ping('8.8.8.8', interface):
        raise SystemExit('通过 F50 ping 8.8.8.8 未成功；暂不启用监控，请先确认网络可用。')
    password = getpass.getpass('F50 管理密码（直接回车使用 admin）：') or 'admin'
    device.login(password)
    print('设备版本、Google ping 和后台登录均通过。')
    subprocess.run(['/bin/launchctl', 'bootout', 'system/' + LABEL],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    BASE.mkdir(parents=True, exist_ok=True)
    os.chown(BASE, 0, 0)
    os.chmod(BASE, 0o755)
    source = Path(__file__).resolve().parent
    for name in ('f50_reboot.py', 'f50_watchdog.py'):
        dest = BASE / name
        shutil.copyfile(source / name, dest)
        os.chown(dest, 0, 0)
        os.chmod(dest, 0o644)
    state_dir = BASE / 'state'
    state_dir.mkdir(exist_ok=True)
    os.chown(state_dir, account.pw_uid, account.pw_gid)
    os.chmod(state_dir, 0o700)
    config = {'host': '192.168.0.1', 'target': '8.8.8.8',
              'password': password, 'state_dir': str(state_dir)}
    config_path = BASE / 'config.json'
    # Create with restrictive permissions before writing the password.
    fd = os.open(config_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    os.fchown(fd, account.pw_uid, account.pw_gid)
    with os.fdopen(fd, 'w') as stream:
        json.dump(config, stream, indent=2)
    PLIST.write_bytes(plistlib.dumps(launch_spec(python, user)))
    os.chown(PLIST, 0, 0)
    os.chmod(PLIST, 0o644)
    subprocess.run(['/usr/bin/plutil', '-lint', str(PLIST)], check=True)
    subprocess.run(['/bin/launchctl', 'enable', 'system/' + LABEL], check=True)
    subprocess.run(['/bin/launchctl', 'bootstrap', 'system', str(PLIST)], check=True)
    print('已安装并启动；开机自动运行，无需登录桌面。启动后先等待180秒。')
    subprocess.run(['/bin/launchctl', 'print', 'system/' + LABEL], check=True)


if __name__ == '__main__':
    main()
