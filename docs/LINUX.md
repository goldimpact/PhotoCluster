# Linux / WSL Android guide / 使用说明

The supported development focus is Windows and Linux with Android. macOS and iOS
are deferred until suitable hardware is available. Linux CI uses Ubuntu; this is
not a guarantee for every Linux distribution, USB driver or phone vendor.

当前重点是 Windows / Linux 操作 Android；macOS、iOS 等具备设备后再推进。

## Native Linux / 原生 Linux

Use Python **3.11+**, ADB, FFmpeg and FFprobe. For Ubuntu 24.04:

```bash
sudo apt update
sudo apt install python3 python3-venv adb ffmpeg
git clone https://github.com/goldimpact/PhotoCluster.git
cd PhotoCluster
bash start.sh --check
bash start.sh --no-install
```

Ubuntu 22.04 ships Python 3.10, which is too old. Install Python 3.11+ separately
(for example using a Python version manager); do not replace `/usr/bin/python3`.
Choose it for the first launch:

```bash
PHOTOCLUSTER_PYTHON=python3.11 bash start.sh --check
```

The launcher creates `.venv-linux`, then reuses its interpreter on subsequent
launches. Windows uses `.venv`; do not copy virtual environments between systems.
For better WSL installation/cache I/O performance, prefer a clone inside the Linux
filesystem (for example `~/projects/PhotoCluster`); `/mnt/c` and `/mnt/d` work but
many small dependency/cache files can be slower there.
`--no-install` avoids pip/network installation after setup. `--check` checks tools
and counts authorized devices without printing device IDs or media paths.

Linux USB access may require your distribution's Android udev rules and user group
membership. If `adb devices` reports permission errors, install/configure those
rules, sign in again if necessary, reconnect and authorize the phone. Do not run
the whole web application as root to bypass USB permissions.

Linux 需要配置本机的 USB / udev 权限。手机解锁并允许 USB 调试后再同步；不要用 root
运行整个程序来绕过 USB 权限。原生 USB 连接与 WSL 借用 Windows ADB 是两种不同链路。

## WSL: reuse Windows ADB / 复用 Windows 已连接的手机

Windows connecting to a phone does not automatically attach its USB device to WSL.
The simplest path when Windows ADB is already authorized is WSL interoperability:
run the **Linux Python/backend/FFmpeg** with the existing **Windows adb.exe**.
This does not require exposing an ADB server on a network interface.

Windows 已经连上手机时，可让 Linux 后端调用 Windows 的 `adb.exe`，无需重新配置 USB
透传，也不需要把 ADB 服务暴露到局域网。

```bash
# Run inside WSL from this project's directory.
# Native Linux adb is preferred if installed; specify adb.exe to reuse Windows.
bash start.sh --adb '/mnt/c/Tools/platform-tools/adb.exe' --check
bash start.sh --adb '/mnt/c/Tools/platform-tools/adb.exe' --no-install --port 8766
```

Replace the example path with your actual Windows ADB path. If only `adb.exe` is
on the WSL PATH, it is discovered automatically. `PHOTOCLUSTER_ADB` can also specify
one executable path (not a shell command with extra arguments). `adb pull` local
destinations are converted with `wslpath -w`, including Linux temporary directories.
Original bytes and tar streams are read without text/newline conversion.

Use Linux FFmpeg/FFprobe, not Windows executables against untranslated Linux paths.
If Windows PhotoCluster already uses port 8765, use **8766** for WSL. Open
`http://127.0.0.1:8766` in your Windows browser using WSL localhost forwarding.
If forwarding is unavailable, open from a browser inside WSL; do not change the
application to listen on `0.0.0.0` as a workaround.

WSL calls are checked with the phone as a read-only source. Do not operate on the
same phone concurrently from Windows and WSL: locks are local to each process, not
distributed between operating systems.

如果已有 Linux `adb` 却看不到手机，请显式指定 `--adb .../adb.exe`；程序不会擅自切换
ADB 服务或重新连接设备。也可自行使用 usbipd-win 透传 USB，再走原生 Linux ADB，
但那是不同的连接配置，不能把 adb.exe 实测等同于原生 USB 透传已验证。

## Starting and quitting / 启动与退出

With a graphical Linux session or WSLg and Python Tk support, `bash PhotoCluster.sh`
opens the control window. Ubuntu system Python typically needs `python3-tk`; a
version-manager Python needs a Tk-enabled build of that interpreter. The window
has Start/Open/Exit buttons and does not require a system tray implementation.

`bash start.sh --no-install` also starts the managed service and opens the browser
when ready; add `--no-browser` for remote/headless use. Quit using the page's **Exit
PhotoCluster** button or Ctrl+C in the launching terminal. The managed server waits
for active work to finish safely; closing a browser tab leaves it running. Repeated
launches on the same port open the existing matching instance, and a cache lock
prevents two managed instances from writing the same data directory.

Direct `python -m uvicorn ...` remains an advanced externally managed option. Its
page offers the desktop launcher's **Switch to managed startup** action (or Ctrl+C
for CLI users). Migration validates process identity and idle status, then requests
normal exit before starting the new instance. It refuses unsupported supervisor or
shared-console arrangements rather than forcing termination. The new cache lock
does not cover old/direct Uvicorn processes: do not bypass them with another port.

## Cache and network / 缓存与代理

Defaults: Windows/native Linux use `data/`; WSL uses `data/wsl/`. Windows caches
contain host-specific feature paths, so they are not reused by WSL. Existing
Windows caches stay untouched; WSL's first classification computes its own cache.
Do not point multiple running instances at the same writable data directory.

```bash
bash start.sh --data-dir "$PWD/data/linux-test" --port 8766
bash start.sh --install-model
bash start.sh --install-gpu     # optional NVIDIA/CUDA 12 environment only
bash start.sh --accelerator cpu --no-install
```

`PHOTOCLUSTER_DATA_DIR` applies to direct Python/Uvicorn launches too.
`PHOTOCLUSTER_MODEL` optionally points to an existing local model file, allowing
read-only model sharing without sharing writable caches. Explicit `--install-model`
installs/verifies the pinned model at that configured location.

WSL NAT mode's `127.0.0.1` is not necessarily the Windows proxy's loopback. Try direct
downloads first or use a proxy address reachable from WSL. `--proxy URL` affects
dependency/model downloads only; do not modify proxy/firewall settings just to run
classification. Never commit proxy credentials or private environment configuration.

## Verification / 验证

```bash
.venv-linux/bin/python -m pytest -q
npm ci
npm test
# Optional: reads a phone inventory and at most three small media samples.
.venv-linux/bin/python scripts/check_android.py
```

The explicit phone check requires exactly one authorized device. It reads images,
GIFs and video when available, compares `pull`/stream bytes, classifies the sample
and tests original/video HTTP previews using temporary caches. It never deletes or
moves phone files and does not overwrite the user's saved classification results.
It prints aggregate counts only. It is not a full-library accuracy/performance test
or browser visual validation. Automated deletion/move tests always use mocks.

Validated in this change: Windows Python 3.11 and WSL2 Ubuntu 22.04 with Linux Python
3.11 / FFmpeg and Windows adb.exe. Both read the connected Android inventory and
passed image/GIF/video sample classification, matching stream/pull bytes, original
preview, video HTTP range and lease cleanup checks. No real phone file was mutated.
Native Linux USB/udev attachment was not tested; Ubuntu CI covers CPU code and
synthetic media separately. WSL CUDA acceleration and browser visuals were not validated.
