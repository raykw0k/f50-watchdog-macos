# F50 Watchdog for macOS

中兴 F50 无人值守断网重启脚本。通过 **Web API** 自动登录、计算请求签名并重启设备，不依赖浏览器或 ADB，不会重置 USB 或切断供电。

## 工作方式

1. 每次启动先等待 180 秒，让 Mac、USB 网卡和移动网络就绪。
2. 通过 F50 的网络接口 ping Google DNS `8.8.8.8`。
3. 连续失败满 20 秒，发送一次 F50 重启请求。
4. 请求完成后等待 5 分钟；此时仍不通就再次重启，再等 5 分钟，持续循环。
5. 5 分钟到时若已通网，恢复正常监控，下一次连续失败 20 秒再重启。

ping 绑定通往 F50 的网络接口，避免其他 Wi-Fi 连接掩盖 F50 的故障。探测与调度有约一至数秒误差，并非硬实时计时器。等待状态保存到磁盘：进程意外退出或 Mac 重启后，若之前在等待，会重新等满 5 分钟。

## 适用环境

- macOS，Python 3.9 或更新版本，无第三方 Python 依赖。
- 普通版中兴 F50，实测固件：`F50_FLYMODEM_ZYV1.0.0B16`。
- F50 通过 USB 数据线连接，管理地址为 `192.168.0.1`，后台密码已知。
- 安装和管理系统服务需要 Mac 管理员权限。

脚本会检查固件，其他型号、F50 Pro 或其他固件尚未验证。

## 安装并开机运行

在最终运行监控的 Mac 上操作。先连接 F50，并确认它能正常上网。

从本仓库的 **Code → Download ZIP** 下载并解压，在终端进入解压后的目录：

```bash
python3 --version
bash install.sh
```

按提示先输入 Mac 管理员密码，再输入 F50 后台管理密码。F50 密码直接回车使用出厂默认值 `admin`；输入过程不显示字符。

安装器先检查固件、通过 F50 ping Google，以及管理后台登录，检查通过才安装并启动。安装本身不会发送重启请求。更新已有安装时，也运行同一条命令。

服务使用系统级 LaunchDaemon，磁盘解锁后随 Mac 开机启动，不需要登录桌面，以安装账户身份运行。启用 FileVault 的 Mac 冷启动可能需要人工解锁磁盘；脚本不更改 FileVault 或睡眠设置。无人值守监控需要 Mac 保持唤醒。

安装位置：

```text
/Library/Application Support/F50Watchdog/
/Library/LaunchDaemons/local.f50.watchdog.plist
```

## 查看状态和日志

```bash
sudo launchctl print system/local.f50.watchdog
tail -n 50 "/Library/Application Support/F50Watchdog/state/watchdog.log"
```

服务状态应显示 `state = running`。主日志每份 1 MB，保留三份旧日志；启动异常另见同目录的 `service.err`。

## 手动重启

```bash
python3 f50_reboot.py --reboot
```

按提示输入后台密码。自动化调用可通过 `F50_PASSWORD` 环境变量传入密码。不加 `--reboot` 时仅检查管理接口，不重启。

## 停止并移除开机启动

在源码目录执行：

```bash
bash install.sh --uninstall
```

配置、日志和等待状态会保留，便于排查和重新安装。

## 重启接口与限制

脚本获取 `LD`，使用固件的双重 SHA256 算法登录并维持 Cookie 会话，再利用固件版本和 `RD` 计算 `AD` 签名，向 `/goform/goform_set_cmd_process` 发送 `goformId=REBOOT_DEVICE`。

- 移动网络断开但本地 Web API 仍可达时，可以重启。
- 整机卡死、Web API 无响应时，脚本无法强制断电，只会每 5 分钟再次尝试。
- Google DNS 的 ICMP 被拦截也会被视为断网；安装前会检查目标可达。
- 重启请求失败、超时或密码错误，也会等待 5 分钟后重试。请从日志排查密码和固件问题。
- `config.json` 包含管理密码，权限为 `600`，仅安装账户及 root 可读；不要上传配置、日志或设备标识。管理接口使用设备原生 HTTP，适合可信的本地网络。

## 测试

```bash
python3 -m unittest discover -v
```

12 项自动测试覆盖失败计时、5 分钟重复重试、恢复监控、磁盘状态恢复、错误密码、空响应和网络接口选择。Web API 重启及绑定 F50 网卡 ping 已做实机验证；LaunchDaemon 的运行情况仍需在目标 Mac 上安装后确认。

项目与中兴官方无关联。
