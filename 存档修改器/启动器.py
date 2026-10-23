# -*- coding: utf-8 -*-
"""三国存档修改器 · 桌面启动器

作用：
  1. 起一个「只在本机」的小服务，把修改器页面放进浏览器跑（不联网、不监听外网，只绑 127.0.0.1）；
  2. 提供「一键更新物品库」：读取游戏 Json + MODs + MODProjects，重新生成物品库，
     页面点按钮即可完成，不用再去命令行跑脚本。

用法：双击 三国存档修改器.exe（或 python 启动器.py）
可选参数：
  --game <游戏根目录>   指定游戏目录（含 ThreeKingdom_Data 的那一层）
  --port <端口>         指定端口（默认自动挑一个空闲端口）
  --no-browser          不自动打开浏览器
"""
import io
import json
import os
import socket
import sys
import threading
import traceback
import webbrowser
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

APP_TITLE = '三国存档修改器'

# 常见游戏目录（按顺序探测）
GAME_CANDIDATES = [
    r'E:\SteamLibrary\steamapps\common\LegendOfHeros',
    r'F:\BaiduNetdiskDownload\LegendOfHeros\LegendOfHeros',
    r'D:\SteamLibrary\steamapps\common\LegendOfHeros',
    r'C:\Program Files (x86)\Steam\steamapps\common\LegendOfHeros',
]


def base_dir():
    """打包后是解包目录；源码运行时是脚本所在目录。"""
    if getattr(sys, 'frozen', False):
        return getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def exe_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def find_asset(name):
    """先找 exe 旁边的同名文件（方便用户自己替换/魔改），再找打包内的资源。"""
    for d in (exe_dir(), base_dir()):
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    return None


def detect_game_root():
    for p in GAME_CANDIDATES:
        if os.path.isdir(os.path.join(p, 'ThreeKingdom_Data')):
            return p
    # 再从 exe 旁边的 config.json 里读
    cfg = find_asset('config.json')
    if cfg:
        try:
            d = json.loads(io.open(cfg, encoding='utf-8').read())
            g = d.get('game')
            if g and os.path.isdir(os.path.join(g, 'ThreeKingdom_Data')):
                return g
        except Exception:
            pass
    return GAME_CANDIDATES[0]


GAME_ROOT = detect_game_root()
STATE = {
    'catalog': '',          # 物品库.js 的文本（内存里，更新后即时生效）
    'html': '',
    'game': GAME_ROOT,
    'last_update': '',
}


def load_initial():
    p = find_asset('物品库.js')
    if p:
        STATE['catalog'] = io.open(p, encoding='utf-8').read()
    p = find_asset('存档修改器.html')
    if p:
        STATE['html'] = io.open(p, encoding='utf-8').read()


def run_catalog_update():
    """调用打包进来的 update_item_catalog.py，重新生成物品库并写进内存。"""
    src_path = find_asset('update_item_catalog.py')
    if not src_path:
        raise RuntimeError('找不到 update_item_catalog.py（打包资源缺失）')
    out_path = os.path.join(exe_dir(), '物品库.js')      # 顺便在 exe 旁边留一份，方便查看
    src = io.open(src_path, encoding='utf-8').read()

    argv_bak = sys.argv[:]
    sys.argv = [src_path, STATE['game'], out_path]
    buf = io.StringIO()
    stdout_bak = sys.stdout
    sys.stdout = buf
    ns = {'__name__': '__main__', '__file__': src_path}
    try:
        exec(compile(src, src_path, 'exec'), ns)
    finally:
        sys.stdout = stdout_bak
        sys.argv = argv_bak

    if os.path.exists(out_path):
        STATE['catalog'] = io.open(out_path, encoding='utf-8').read()
    # 物品库换了 → 统计缓存必须失效（否则页面刷新后还显示旧条目数）
    STATE['catalog_gen'] = STATE.get('catalog_gen', 0) + 1
    STATE['stats_val'] = None
    import time
    STATE['last_update'] = time.strftime('%H:%M:%S')
    return buf.getvalue()


def catalog_stats():
    txt = STATE['catalog']
    # 2026-10-22 提速：原来每次 /api/info 都要对 25 万字的物品库做 3 次
    # json.loads（ITEM_CAT / PET_CAT / TITLE_CAT），纯 Python 解析一次 ~0.2 秒，
    # 页面刷新、状态栏轮询都会踩到。缓存按物品库文本本身做 key，内容不变就直接返回。
    if STATE.get('stats_key') == (len(txt), STATE.get('catalog_gen')) \
            and STATE.get('stats_val') is not None:
        return STATE['stats_val']
    def cnt(key):
        i = txt.find('window.' + key + '=')
        if i < 0:
            return 0
        j = txt.find(';\n', i)
        try:
            return len(json.loads(txt[i + len('window.' + key + '='):j]))
        except Exception:
            return 0
    val = {'item': cnt('ITEM_CAT'), 'pet': cnt('PET_CAT'),
           'title': cnt('TITLE_CAT') if 'TITLE_CAT' in txt else None}
    STATE['stats_key'] = (len(txt), STATE.get('catalog_gen'))
    STATE['stats_val'] = val
    return val


class Handler(BaseHTTPRequestHandler):
    server_version = 'SG3K'

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype='text/plain; charset=utf-8', extra=None):
        if isinstance(body, str):
            body = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass

    def do_GET(self):
        from urllib.parse import unquote
        path = unquote(self.path.split('?')[0])
        if path in ('/', '/index.html', '/存档修改器.html'):
            html = STATE['html']
            # 在标题栏注入「更新物品库」按钮（只注入一次）
            if 'updCatBtn' not in html:
                inject = (
                    '<style>#updCatBtn{position:fixed;right:14px;top:10px;z-index:99;'
                    'background:var(--ac,#2563eb);color:#fff;border:0;border-radius:8px;'
                    'padding:7px 13px;font-size:13px;cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,.18)}'
                    '#updCatBtn:disabled{opacity:.6;cursor:default}</style>'
                    '<button id="updCatBtn" title="读取游戏 Json + MODs + MODProjects，重新生成物品库">'
                    '更新物品库</button>'
                    '<script>(function(){var b=document.getElementById("updCatBtn");'
                    'b.onclick=async function(){b.disabled=true;var o=b.textContent;b.textContent="更新中…";'
                    'try{var r=await fetch("/api/update-catalog",{method:"POST"});'
                    'var j=await r.json();'
                    'if(!j.ok)throw new Error(j.error||"更新失败");'
                    'alert("物品库已更新：\\n"+j.summary);location.reload();}'
                    'catch(e){alert("更新失败："+e.message+"\\n\\n（需要用「三国存档修改器.exe」启动才行）");}'
                    'finally{b.disabled=false;b.textContent=o;}};})();</script>'
                )
                idx = html.find('</body>')
                html = (html[:idx] + inject + html[idx:]) if idx > 0 else (html + inject)
            self._send(200, html, 'text/html; charset=utf-8')
            return
        if path.endswith('物品库.js') or path == '/物品库.js':
            self._send(200, STATE['catalog'], 'application/javascript; charset=utf-8')
            return
        if path == '/api/info':
            st = catalog_stats()
            self._send(200, json.dumps({
                'game': STATE['game'],
                'items': st['item'], 'pets': st['pet'],
                'lastUpdate': STATE['last_update'],
            }, ensure_ascii=False), 'application/json; charset=utf-8')
            return
        if path == '/favicon.ico':
            self._send(204, b'')
            return
        # 其它同目录文件（用户自己放的东西）
        name = os.path.basename(path)
        p = find_asset(name)
        if p and os.path.isfile(p):
            ct = 'text/plain; charset=utf-8'
            if name.endswith(('.html', '.htm')):
                ct = 'text/html; charset=utf-8'
            elif name.endswith('.js'):
                ct = 'application/javascript; charset=utf-8'
            self._send(200, io.open(p, 'rb').read(), ct)
            return
        self._send(404, 'not found')

    def do_POST(self):
        path = self.path.split('?')[0]
        if path == '/api/update-catalog':
            try:
                log = run_catalog_update()
                st = catalog_stats()
                tail = '\n'.join([l for l in log.strip().splitlines() if l.strip()][-3:])
                self._send(200, json.dumps({
                    'ok': True,
                    'summary': '条目 %d 条 · 宠物 %d 条\n%s' % (st['item'], st['pet'], tail),
                }, ensure_ascii=False), 'application/json; charset=utf-8')
            except Exception as e:
                self._send(200, json.dumps({
                    'ok': False, 'error': str(e), 'trace': traceback.format_exc()[-1500:],
                }, ensure_ascii=False), 'application/json; charset=utf-8')
            return
        self._send(404, 'not found')


def free_port(prefer=8788):
    for p in [prefer] + list(range(prefer + 1, prefer + 40)):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(('127.0.0.1', p))
                return p
            except OSError:
                continue
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def main():
    args = sys.argv[1:]
    port = None
    no_browser = False
    for i, a in enumerate(args):
        if a == '--game' and i + 1 < len(args):
            STATE['game'] = args[i + 1]
        elif a == '--port' and i + 1 < len(args):
            port = int(args[i + 1])
        elif a == '--no-browser':
            no_browser = True

    load_initial()
    port = port or free_port()
    srv = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    url = 'http://127.0.0.1:%d/' % port

    print('=' * 56)
    print(' %s 已启动' % APP_TITLE)
    print(' 页面地址 : %s' % url)
    print(' 游戏目录 : %s' % STATE['game'])
    print(' 物品库   : %d 条' % catalog_stats()['item'])
    print(' 关闭本窗口即退出。')
    print('=' * 56)

    if not no_browser:
        threading.Timer(0.7, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


if __name__ == '__main__':
    main()
