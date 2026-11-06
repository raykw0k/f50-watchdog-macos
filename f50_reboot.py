#!/usr/bin/env python3
"""F50 B16 HTTP reboot; no browser, ADB, or third-party packages required."""
import argparse
import getpass
import hashlib
import http.cookiejar
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


class F50Error(Exception):
    pass


def sha256(text):
    # Match util.js: normalize CRLF, encode UTF-16 code units as UTF-8 (CESU-8).
    raw = text.replace('\r\n', '\n').encode('utf-16-be', 'surrogatepass')
    units = ''.join(chr(int.from_bytes(raw[i:i+2], 'big'))
                    for i in range(0, len(raw), 2))
    return hashlib.sha256(units.encode('utf-8', 'surrogatepass')).hexdigest().upper()


class F50:
    def __init__(self, base, timeout=8):
        self.base = base.rstrip('/')
        self.timeout = timeout
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def request(self, path, data=None):
        headers = {'Referer': self.base + '/index.html',
                   'X-Requested-With': 'XMLHttpRequest'}
        payload = None if data is None else urllib.parse.urlencode(data).encode()
        req = urllib.request.Request(self.base + path, data=payload, headers=headers)
        with self.opener.open(req, timeout=self.timeout) as response:
            raw = response.read()
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            raise F50Error('后台返回空内容或非 JSON；不能视为成功。') from None
        if not isinstance(result, dict):
            raise F50Error('后台返回了意外格式。')
        return result

    def get(self, commands):
        query = urllib.parse.urlencode({'isTest': 'false', 'cmd': commands,
                                        'multi_data': '1', '_': time.time_ns()})
        return self.request('/goform/goform_get_cmd_process?' + query)

    def post(self, command, **fields):
        return self.request('/goform/goform_set_cmd_process',
                            dict(isTest='false', goformId=command, **fields))

    def login(self, password):
        nonce = self.get('LD').get('LD')
        if not isinstance(nonce, str) or not nonce:
            raise F50Error('没有取得登录随机数 LD，已停止。')
        result = self.post('LOGIN', password=sha256(sha256(password) + nonce))
        if str(result.get('result')) not in ('0', '4'):
            raise F50Error('登录失败，返回代码 %s；不自动重试，避免锁定。'
                           % result.get('result', '<缺失>'))
        if self.get('loginfo').get('loginfo') != 'ok':
            raise F50Error('登录会话验证失败，已停止。')

    def reboot(self, password):
        self.login(password)
        versions = self.get('wa_inner_version,cr_version')
        inner, outer = versions.get('wa_inner_version'), versions.get('cr_version')
        if not all(isinstance(v, str) and v for v in (inner, outer)):
            raise F50Error('没有取得签名所需的固件版本，已停止。')
        nonce = self.get('RD').get('RD')
        if not isinstance(nonce, str) or not nonce:
            raise F50Error('没有取得请求随机数 RD，已停止。')
        signature = sha256(sha256(inner + outer) + nonce)
        result = self.post('REBOOT_DEVICE', AD=signature)
        if result.get('result') != 'success':
            raise F50Error('重启请求未确认成功：%s' % json.dumps(result))
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='http://192.168.0.1')
    parser.add_argument('--reboot', action='store_true', help='登录并发送一次重启请求')
    parser.add_argument('--wait', type=int, default=120, help='等待管理接口恢复的秒数；0 表示不等待')
    args = parser.parse_args()
    device = F50(args.host)
    try:
        info = device.get('wa_inner_version,cr_version')
        version = info.get('wa_inner_version', '')
        print('设备固件：' + version, flush=True)
        if version != 'F50_FLYMODEM_ZYV1.0.0B16':
            raise F50Error('当前脚本仅实测普通版 F50 B16，固件不匹配，已停止。')
        if not args.reboot:
            print('管理接口可达。加 --reboot 才会重启。')
            return 0
        password = os.environ.get('F50_PASSWORD')
        if password is None:
            if not sys.stdin.isatty():
                raise F50Error('无人值守运行需要设置 F50_PASSWORD 环境变量。')
            password = getpass.getpass('F50 后台管理密码：')
        device.reboot(password)
        del password
        print('重启请求已接受：success（只发送一次）。', flush=True)
        if args.wait <= 0:
            return 0
        deadline = time.monotonic() + args.wait
        time.sleep(min(10, args.wait))
        while time.monotonic() < deadline:
            try:
                state = device.get('wa_inner_version,network_type,ppp_status')
                if state.get('wa_inner_version') == version:
                    print('管理接口已可达；移动网络状态：%s / %s'
                          % (state.get('network_type', '?'), state.get('ppp_status', '?')))
                    print('接口可达不等于外网已恢复；本脚本不检测 Google。')
                    return 0
            except (OSError, F50Error):
                pass
            time.sleep(2)
        raise F50Error('重启请求已接受，但等待管理接口恢复超时；未重复重启。')
    except (OSError, F50Error) as exc:
        print('失败：' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
