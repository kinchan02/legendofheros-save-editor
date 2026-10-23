# -*- coding: utf-8 -*-
"""检查更新 / 自动更新（GitHub Releases + 国内镜像）

2026-10-23 新增。设计要点：

1. **版本号用元组比较**。字符串比较会得出 "1.0.10" < "1.0.9" 这种错误结论，
   所以统一用 (1, 10, 0) 这种整数元组。

2. **GitHub 直连不通时走镜像**。实测本机 / 多数国内网络：
   api.github.com 通（300ms），但 github.com 与 raw.githubusercontent.com 都不通。
   因此查版本走 API，下载走 ghfast.top / gh-proxy.com / ghproxy.net 三个镜像轮询
   （实测三者都能完整下到 GitHub Release 资产，大小一致）。

3. **Nuitka onefile 里拿自身路径**：sys.executable 指向临时解压目录的 python.exe，
   os.getcwd() 是启动时的工作目录，sys.frozen 在 Nuitka 下根本不存在。
   唯一可靠的是 __main__.__compiled__.original_argv0 / containing_dir。

4. **运行中可以替换自身**。实测 Nuitka onefile 启动后已把自己解压到临时目录再执行，
   原 exe 文件没有锁，可以改名 + 覆盖 —— 所以「下载 → 原地替换 → 重启」可行。

5. **只做「用户点了才更新」**，并且**版本必须比当前高才更新**（防降级）。
   静默联网 + 自替换会被杀软误报，也容易被塞旧版。

6. **更新日志内置在代码里**（CHANGELOG），不再依赖外部 md 文件。
   发版时只改 CHANGELOG 与 VERSION 两处；「检查更新」查到新版时
   优先显示服务器 release 里的说明，没有说明就回落到内置 CHANGELOG。
"""
import io
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request

# ------------------------------------------------------------------ 常量
VERSION = (1, 0, 10)
VERSION_STR = '%d.%d.%d' % VERSION

# GitHub 仓库（owner/repo）。留空则「检查更新」按钮会提示未配置。
GITHUB_REPO = 'kinchan02/legendofheros-save-editor'

# ------------------------------------------------------------------ 内置更新日志
# 发版时只改这里（新版本插到列表最前面）+ 上面的 VERSION，不再维护外部 md 文件。
# 每项：(版本, 类型, [要点…])；类型沿用「修复 / 新增 / 优化 / 适配 / 调整」。
CHANGELOG = [
    ('1.0.10', '优化', [
        '优化读取存档速度，大存档读档耗时由 4～8 秒降至 1 秒左右。',
        '修复更新物品库时 CPU 占用偏高的问题。',
    ]),
    ('1.0.9', '修复', [
        '修复势力资源定位错误问题。',
        '恢复「国库金」修改项，属于势力资源，仅已自立势力的君主档可修改。',
        '资源区布局调整：第一行「金钱 / 灵蕴」，第二行「科技点 / 策略点」，第三行「国库金」。',
        '未自立势力的武将档与自建武将存档国库金暂无法定位，该项置灰不可编辑，避免写入错误位置。',
    ]),
    ('1.0.8', '修复', [
        '修复部分存档中多名武将的六维属性（统率 / 武力 / 智略 / 政略 / 魅力 / 意志）'
        '被读取成同一组数值的问题。',
    ]),
    ('1.0.7', '修复', [
        '修复自建武将六维属性（统率 / 武力 / 智略 / 政略 / 魅力 / 意志）读取错误的问题。',
    ]),
    ('1.0.6', '修复 / 新增', [
        '修复玩家身份为君主时，资源修改读取数据错误的问题。',
        '新增「灵蕴」修改项，属于玩家个人资源，与金钱并列。',
        '移除「国库金」修改项（该数据定位不可靠，多处存在相同数值无法甄别真伪）。',
    ]),
    ('1.0.5', '修复 / 增强', [
        '修复「人物修改」无法读取自建武将的问题。',
        '「称号修改」升级为支持修改所有武将的称号。',
    ]),
    ('1.0.4', '新增', [
        '新增「人物性格修改」功能，入口位于人物属性修改页内。',
    ]),
    ('1.0.3', '适配', [
        '适配游戏 10.16 晚间更新。',
    ]),
    ('1.0.2', '修复', [
        '修复游戏侧特性上限被修改后，使用「特性一键拉满」导致读档直接报错的问题。',
    ]),
    ('1.0.1', '修复', [
        '修复玩家身份为「在野」时，资源点数读取错位的问题。',
    ]),
    ('1.0.0', '适配', [
        '全部功能已适配游戏 10.12 更新。',
    ]),
]


def changelog_for(version):
    """取某个版本的要点列表；没有该版本返回 []。version 可为元组或 '1.0.10'。"""
    want = '.'.join(str(x) for x in version) if isinstance(version, tuple) else str(version)
    for ver, _kind, items in CHANGELOG:
        if ver == want or ver.lstrip('vV') == want.lstrip('vV'):
            return items
    return []

# 国内可直连的 GitHub 加速镜像（前缀拼接方式）。按顺序尝试。
MIRRORS = (
    'https://ghfast.top/',
    'https://gh-proxy.com/',
    'https://ghproxy.net/',
)

UA = 'HeroesSaveEditor-Updater/1.0'
API_TIMEOUT = 10
DL_TIMEOUT = 90


class UpdateError(Exception):
    pass


# ------------------------------------------------------------------ 自身路径
def app_path():
    """返回当前运行的 exe 绝对路径；源码模式下返回 None（不参与自动更新）。"""
    m = sys.modules.get('__main__')
    c = getattr(m, '__compiled__', None)
    if c is not None:
        p = getattr(c, 'original_argv0', None) or getattr(c, 'process_exe', None)
        if p and os.path.isfile(p):
            return os.path.abspath(p)
    if getattr(sys, 'frozen', False):
        p = sys.executable
        if p and os.path.isfile(p):
            return os.path.abspath(p)
    # 兜底：非 onefile 的 Nuitka standalone 或 PyInstaller onedir
    if sys.argv and sys.argv[0].lower().endswith('.exe'):
        p = os.path.abspath(sys.argv[0])
        if os.path.isfile(p):
            return p
    return None


def is_frozen():
    return app_path() is not None


def _app_dir():
    p = app_path()
    if p:
        return os.path.dirname(p)
    return os.path.dirname(os.path.abspath(__file__))


def parse_version(text):
    """把 'v1.0.11' / '1.0.11' / 'V1.0.11-beta' / 'jq-1.8.2' 解析成版本元组。失败返回 None。

    先按「点分段、每段取前导数字」解析；失败再用正则从整串里找第一个 x.y[.z] 形态。
    （仓库 tag 一般写成 v1.0.11，但别人可能写成 名字-1.2.3，宽容一点更稳。）
    """
    if not text:
        return None
    s = str(text).strip().lstrip('vV')
    parts = []
    for seg in s.split('.'):
        digits = ''
        for ch in seg:
            if ch.isdigit():
                digits += ch
            else:
                break
        if not digits:
            break
        parts.append(int(digits))
        if len(parts) >= 4:
            break
    if len(parts) >= 2:
        return tuple(parts)
    m = re.search(r'(\d{1,4}(?:\.\d{1,4}){1,3})', str(text))
    if m:
        try:
            return tuple(int(x) for x in m.group(1).split('.'))
        except Exception:
            return None
    return tuple(parts) if parts else None


# ------------------------------------------------------------------ 网络
def _opener():
    # 部分机器证书链不全，这里只对 https 放宽验证（GitHub API / 镜像都用 https）
    ctx = ssl.create_default_context()
    try:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    except Exception:
        pass
    return urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))


def _get(url, timeout=API_TIMEOUT):
    req = urllib.request.Request(url, headers={
        'User-Agent': UA,
        'Accept': 'application/vnd.github+json',
    })
    return _opener().open(req, timeout=timeout)


# ------------------------------------------------------------------ 检查
def check_latest(repo=None, timeout=API_TIMEOUT):
    """查最新 Release。返回 dict：
        {'version': (1,0,11), 'tag': 'v1.0.11', 'notes': '...',
         'assets': [{'name':..., 'size':..., 'url':..., 'digest':...}],
         'published': '...'}
    失败抛 UpdateError。repo 传空时读 config.json 的 update_repo，再退 GITHUB_REPO。
    """
    repo = norm_repo(repo or config_repo() or GITHUB_REPO)
    if not repo:
        raise UpdateError('未配置更新仓库地址')
    url = 'https://api.github.com/repos/%s/releases/latest' % repo
    try:
        with _get(url, timeout) as r:
            data = json.loads(r.read().decode('utf-8', 'replace'))
    except urllib.error.HTTPError as e:
        raise UpdateError('查询最新版本失败（HTTP %s）' % e.code)
    except Exception as e:
        raise UpdateError('查询最新版本失败（%s）' % (e.__class__.__name__,))

    tag = data.get('tag_name') or data.get('name') or ''
    ver = parse_version(tag)
    if not ver:
        raise UpdateError('读到的版本号无法解析：%r' % tag)

    assets = []
    for a in data.get('assets') or []:
        assets.append({
            'name': a.get('name') or '',
            'size': a.get('size') or 0,
            'url': a.get('browser_download_url') or '',
            'digest': a.get('digest') or '',
        })
    return {
        'version': ver,
        'tag': tag,
        'notes': (data.get('body') or '').strip(),
        'assets': assets,
        'published': data.get('published_at') or '',
    }


def pick_asset(assets, prefer='.exe'):
    """从 assets 里挑一个 exe（优先名字里带 -Vx.y.z 的）。"""
    cands = [a for a in assets if a['name'].lower().endswith(prefer)]
    if not cands:
        raise UpdateError('这个版本没有可下载的 %s 文件' % prefer)
    return cands[0]


def is_newer(latest, current=None):
    cur = tuple(current or VERSION)
    n = len(max(latest, cur, key=len))
    a = tuple(list(latest) + [0] * (n - len(latest)))
    b = tuple(list(cur) + [0] * (n - len(cur)))
    return a > b


# ------------------------------------------------------------------ 下载
def mirror_urls(gh_url):
    """给 GitHub 下载地址生成「原地址 + 各镜像」的候选列表。"""
    out = [gh_url]
    for m in MIRRORS:
        out.append(m + gh_url)
    return out


def download(url, dest, expect_size=0, on_progress=None, timeout=DL_TIMEOUT):
    """下载到 dest。先试原地址，失败逐个换镜像。返回实际字节数。"""
    cands = mirror_urls(url) if 'github.com' in url else [url]
    last = None
    for idx, u in enumerate(cands):
        try:
            n = _download_one(u, dest, expect_size, on_progress, timeout)
            if expect_size and n != expect_size:
                last = UpdateError('下载不完整（%d / %d 字节）' % (n, expect_size))
                continue
            return n
        except Exception as e:
            last = e
            if on_progress:
                on_progress(-1, 0, '第 %d 个源失败，换下一个…' % (idx + 1))
            continue
    raise UpdateError('下载失败：%s' % (last,))


def _download_one(url, dest, expect_size, on_progress, timeout):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    got = 0
    tmp = dest + '.part'
    with _opener().open(req, timeout=timeout) as r, io.open(tmp, 'wb') as f:
        total = expect_size
        try:
            total = int(r.headers.get('Content-Length') or total or 0)
        except Exception:
            pass
        if total and expect_size and total != expect_size:
            raise UpdateError('源返回的大小不对（%d / %d）' % (total, expect_size))
        while True:
            chunk = r.read(65536)
            if not chunk:
                break
            f.write(chunk)
            got += len(chunk)
            if on_progress:
                on_progress(got, total or expect_size, None)
    if os.path.exists(dest):
        try:
            os.remove(dest)
        except Exception:
            pass
    os.replace(tmp, dest)
    return got


# ------------------------------------------------------------------ 安装
def cleanup_old():
    """删掉上次更新留下的 .old 文件。"""
    p = app_path()
    if not p:
        return
    old = p + '.old'
    if os.path.exists(old):
        for _ in range(3):
            try:
                os.remove(old)
                return
            except Exception:
                time.sleep(0.3)


def apply_and_restart(new_file, exe=None):
    """把 new_file 换成当前 exe，然后启动新进程。失败会回滚并抛 UpdateError。"""
    exe = exe or app_path()
    if not exe:
        raise UpdateError('不是编译后的程序，无法自动更新')
    if not os.path.isfile(new_file):
        raise UpdateError('下载的新版本文件不存在')
    if os.path.getsize(new_file) < 1024:
        raise UpdateError('下载的新版本文件太小，可能不完整')

    d = os.path.dirname(exe)
    # 同目录才能保证 os.replace 是原子改名（跨盘会退化成复制）
    staged = os.path.join(d, '.update_new.exe')
    try:
        if os.path.exists(staged):
            os.remove(staged)
        shutil.move(new_file, staged)
    except Exception as e:
        raise UpdateError('无法把新版本放到程序目录（%s）' % e)

    old = exe + '.old'
    try:
        if os.path.exists(old):
            os.remove(old)
        os.replace(exe, old)
    except Exception as e:
        try:
            os.remove(staged)
        except Exception:
            pass
        raise UpdateError('无法重命名当前程序（可能没有写权限，或程序装在 Program Files）：%s' % e)

    try:
        os.replace(staged, exe)
    except Exception as e:
        try:
            os.replace(old, exe)
        except Exception:
            pass
        raise UpdateError('替换失败，已回滚（%s）' % e)

    try:
        subprocess.Popen([exe], cwd=d, close_fds=True)
    except Exception as e:
        raise UpdateError('新版本已就位，但启动失败，请手动打开：%s' % e)


def new_file_placeholder(name):
    """下载时的临时文件名（放在 exe 同目录，保证同盘）。"""
    return os.path.join(_app_dir(), '.update_dl.exe')


# ------------------------------------------------------------------ 仓库地址配置
def norm_repo(s):
    """把 'https://github.com/o/r'、'github.com/o/r'、'o/r' 统一成 'o/r'。"""
    s = (s or '').strip().strip('/')
    if not s:
        return ''
    for pfx in ('https://', 'http://'):
        if s.lower().startswith(pfx):
            s = s[len(pfx):]
    if s.lower().startswith('github.com/'):
        s = s[11:]
    if s.lower().endswith('.git'):
        s = s[:-4]
    parts = [x for x in s.split('/') if x]
    return '/'.join(parts[:2]) if len(parts) >= 2 else ''


def config_repo():
    """从 config.json 里读 update_repo（用户可在界面里改）。"""
    try:
        p = os.path.join(_app_dir(), 'config.json')
        if os.path.exists(p):
            return (json.loads(io.open(p, encoding='utf-8').read()) or {}).get('update_repo') or ''
    except Exception:
        pass
    return ''
