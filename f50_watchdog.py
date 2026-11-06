#!/usr/bin/env python3
"""macOS F50 watchdog. Retry every five minutes until Google responds."""
import argparse
import fcntl
import ipaddress
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import os
import re
import subprocess
import sys
import time

from f50_reboot import F50, F50Error

EXPECTED_VERSION = 'F50_FLYMODEM_ZYV1.0.0B16'


class Policy:
    def __init__(self, locked=False, started=0, startup_grace=180):
        self.locked = locked
        self.ready_at = started + startup_grace
        self.cool_until = started + 300 if locked else 0
        self.failed_since = None

    def observe(self, healthy, now):
        if now < self.ready_at:
            return False
        if self.locked:
            if now < self.cool_until:
                return False
            if healthy:
                self.locked = False
                self.failed_since = None
                return False
            self.cool_until = now + 300
            return True
        if healthy:
            self.failed_since = None
            return False
        if self.failed_since is None:
            self.failed_since = now
        if now - self.failed_since < 20:
            return False
        self.locked = True
        self.cool_until = now + 300
        return True


def save_state(path, locked):
    """Commit the lock BEFORE any reboot HTTP request; never store credentials."""
    temp = path.with_suffix('.tmp')
    with temp.open('w') as stream:
        os.chmod(temp, 0o600)
        json.dump({'locked': locked, 'updated_at': time.time()}, stream)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def load_state(path):
    if not path.exists():
        return False
    try:
        state = json.loads(path.read_text())
        if type(state['locked']) is not bool:
            raise ValueError('Invalid locked field')
        return state['locked']
    except (ValueError, KeyError, OSError):
        # Corrupt state must not cause a reboot loop.
        logging.error('状态文件异常；先等待300秒，再根据网络情况决定是否重启。')
        return True


def interface_for(host):
    result = subprocess.run(['/sbin/route', '-n', 'get', host],
                            capture_output=True, text=True, timeout=4)
    match = re.search(r'^\s*interface:\s*(\S+)', result.stdout, re.M)
    if result.returncode or not match:
        raise F50Error('无法确定 F50 的网络接口。')
    # The gateway must be directly connected, not reached via Wi-Fi's router.
    gateway = re.search(r'^\s*gateway:\s*(\S+)', result.stdout, re.M)
    if gateway:
        try:
            ipaddress.ip_address(gateway.group(1))
        except ValueError:
            pass  # link#N or MAC address means an on-link route
        else:
            raise F50Error('F50 地址当前经其他网关转发，请先连接 F50 的 USB 网络。')
    return match.group(1)


def ping(target, interface):
    try:
        result = subprocess.run(
            ['/sbin/ping', '-n', '-c', '1', '-W', '1000', '-t', '2',
             '-b', interface, target],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        return False


def validate_device(host):
    device = F50('http://' + host, timeout=4)
    info = device.get('wa_inner_version')
    if info.get('wa_inner_version') != EXPECTED_VERSION:
        raise F50Error('固件不是已验证的 F50 B16，拒绝发送重启请求。')
    return device


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--check', action='store_true', help='只检查接口与 ping，不重启')
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    host = str(ipaddress.IPv4Address(config['host']))
    target = str(ipaddress.IPv4Address(config['target']))
    if args.check:
        validate_device(host)
        interface = interface_for(host)
        healthy = ping(target, interface)
        print('F50 B16 可达；接口=%s；ping %s=%s' %
              (interface, target, '成功' if healthy else '失败'))
        return 0 if healthy else 1

    state_dir = Path(config['state_dir'])
    state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock = (state_dir / 'process.lock').open('a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print('监控已经在运行。', file=sys.stderr)
        return 1
    handler = RotatingFileHandler(state_dir / 'watchdog.log',
                                  maxBytes=1024 * 1024, backupCount=3)
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    state_path = state_dir / 'state.json'
    policy = Policy(locked=load_state(state_path), started=time.monotonic())
    logging.info('启动：目标=%s；开机宽限180秒；失败20秒；重启后等待300秒再检查；等待中=%s',
                 target, policy.locked)
    next_reminder = 0
    last_interface = None
    while True:
        tick = time.monotonic()
        try:
            interface = interface_for(host)
            if interface != last_interface:
                logging.info('检测接口：%s（ping 绑定该接口）', interface)
                last_interface = interface
            healthy = ping(target, interface)
        except (OSError, subprocess.SubprocessError, F50Error) as exc:
            healthy = False
            if tick >= next_reminder:
                logging.warning('检测不可用：%s', exc)
                next_reminder = tick + 300
        was_locked = policy.locked
        trigger = policy.observe(healthy, time.monotonic())
        if trigger:
            # If disk persistence fails, fail closed before contacting the device.
            save_state(state_path, True)
            logging.warning('网络仍不通，尝试重启 F50（%s）。',
                            '等待5分钟后重试' if was_locked else '连续失败20秒')
            try:
                device = validate_device(host)
                device.reboot(config['password'])
                logging.warning('F50 接受重启请求。等5分钟，届时仍不通就再次重启。')
            except (OSError, F50Error) as exc:
                logging.error('重启尝试失败或结果不确定：%s。等5分钟后重新检查并重试。', exc)
            # Always give a full five minutes after the HTTP attempt finishes.
            policy.cool_until = time.monotonic() + 300
            next_reminder = time.monotonic() + 300
        elif was_locked and not policy.locked:
            save_state(state_path, False)
            logging.info('5分钟等待结束，ping 已恢复；回到连续失败20秒的正常监控。')
        elif policy.locked and tick >= next_reminder:
            logging.info('正在等待5分钟恢复时间，暂不发送重启请求。')
            next_reminder = tick + 300
        time.sleep(max(0.05, 1 - (time.monotonic() - tick)))


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
