# -*- coding: utf-8 -*-
"""三国存档修改器 · 原生版（Python + Tkinter，真窗口程序，不是套壳网页）

2026-10-14 按小K 要求重写：不用浏览器、不用 HTML，全部原生控件。
  常用功能 / 人物修改 / 各种添加 / 背包管理 / 称号与资源 / 城市属性修改 / 使用方法
引擎在 savecore.py（纯 Python 移植，已与 HTML 版逐项对齐）。
"""
import io
import json
import os
import platform
import re
import shutil
import sys
import threading
import time
import traceback
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import savecore as sc
import updater as UP

APP = '英雄立志传·三国志 存档修改器 V1.0.10（By Kin）'
# 界面顶部第二行：标题下面那行换成免责声明（原来与窗口标题重复，2026-10-22 改）
DISCLAIMER = '本软件完全免费，仅供个人学习使用 · 严禁倒卖或商用'

_ICON_KEEPALIVE = []   # 持有 iconphoto 的 PhotoImage 引用，防被垃圾回收
# ---------------------------------------------------------------- 路径探测
# 存档目录是 Unity 的 LocalLow 约定：「用户名」自动取（USERPROFILE 环境变量），
# 「AppData\LocalLow\发布者\产品名\SaveData」那段是游戏的固定标识（FreeWing / ThreeKingdom）。
# 标准位置找不到时，会自动扫 LocalLow 下的所有子目录；再找不到可在界面上手动指定（记进 config.json）。
SAVE_TAIL = ('AppData', 'LocalLow', 'FreeWing', 'ThreeKingdom', 'SaveData')
GAME_SUBPATHS = [
    os.path.join('steamapps', 'common', 'LegendOfHeros'),
    os.path.join('SteamLibrary', 'steamapps', 'common', 'LegendOfHeros'),
    os.path.join('Steam', 'steamapps', 'common', 'LegendOfHeros'),
    os.path.join('Program Files (x86)', 'Steam', 'steamapps', 'common', 'LegendOfHeros'),
    os.path.join('Program Files', 'Steam', 'steamapps', 'common', 'LegendOfHeros'),
    'LegendOfHeros',
    os.path.join('LegendOfHeros', 'LegendOfHeros'),
    os.path.join('BaiduNetdiskDownload', 'LegendOfHeros', 'LegendOfHeros'),
    os.path.join('Games', 'LegendOfHeros'),
]


def user_home():
    return os.environ.get('USERPROFILE') or os.path.expanduser('~')


def config_path():
    return os.path.join(exe_dir(), 'config.json')


def load_config():
    fp = config_path()
    if os.path.exists(fp):
        try:
            return json.loads(io.open(fp, encoding='utf-8').read())
        except Exception:
            return {}
    return {}


def save_config(cfg):
    try:
        io.open(config_path(), 'w', encoding='utf-8').write(
            json.dumps(cfg, ensure_ascii=False, indent=2))
    except Exception:
        pass


def has_saves(d):
    try:
        return any(n.lower().startswith('save') and n.lower().endswith('.dat')
                   for n in os.listdir(d))
    except Exception:
        return False


def detect_save_dir():
    """自动找存档目录：config → 标准 LocalLow 路径 → 扫 LocalLow 下所有子目录。"""
    cfg = load_config()
    d = cfg.get('saveDir')
    if d and os.path.isdir(d):
        return d
    std = os.path.join(user_home(), *SAVE_TAIL)
    if os.path.isdir(std):
        return std
    low = os.path.join(user_home(), 'AppData', 'LocalLow')
    if os.path.isdir(low):
        for a in sorted(os.listdir(low)):
            pa = os.path.join(low, a)
            if not os.path.isdir(pa):
                continue
            for b in os.listdir(pa):
                cand = os.path.join(pa, b, 'SaveData')
                if os.path.isdir(cand) and has_saves(cand):
                    return cand
    return std


def drive_letters():
    return [c + ':' for c in 'CDEFGHIJK' if os.path.isdir(c + ':' + os.sep)]


def detect_game():
    """自动找游戏根目录（含 ThreeKingdom_Data 的那一层）：config → 各盘常见路径。"""
    cfg = load_config()
    g = cfg.get('game')
    if g and os.path.isdir(os.path.join(g, 'ThreeKingdom_Data')):
        return g
    for d in drive_letters():
        for sub in GAME_SUBPATHS:
            p = os.path.join(d + os.sep, sub)
            if os.path.isdir(os.path.join(p, 'ThreeKingdom_Data')):
                return p
    return ''


SAVE_DIR = None      # 真正的值在 App.__init__ 里算（那时 exe_dir() 已定义）
LAB_SOULPT = ['军魂点', '武魂点', '智魂点']
LAB_SOULLV = ['军魂炼魂等级', '武魂炼魂等级', '智魂炼魂等级']
LAB_MASTER = ['长柄穿刺', '长柄挥砍', '短柄穿刺', '短柄挥砍', '远程', '文官', '艺术', '盾']
LAB_PROF = ['短兵', '枪兵', '骑兵', '弓兵', '器械', '水军', '军学', '商业', '农业', '建造', '征兵', '练兵',
            '治安', '巡访', '城防', '探索', '外交', '辩才', '潜伏', '科研', '医术', '酒力', '旅游', '驯兽']
MAX_SOULPT, MAX_SOULLV, MAX_MASTER, MAX_PROF = 999999, 10, 300, 6
CHR_KEY_RE = re.compile(r'^chr(\d+)(id|lv)$')   # 人物性格：chr<槽位>id / chr<槽位>lv
CHR_NEW_RE = re.compile(r'^chrnew(\d+)$')       # 新增性格：chrnew<序号>
CHAR_NOADD = '（点这里选要加的性格）'
CHAR_DEL = '（删除这个性格）'


def chars_from_picks(picks, base):
    """把性格界面上的下拉选择换算成整段重建要用的 [(id, 等级), ...]。

    picks: [(槽位序号, 下拉文字), ...]（下拉文字形如 "62 放荡"，或 CHAR_DEL / CHAR_NOADD）
    base : 该武将原本的性格列表 find_character_cell() 的结果
    规则：选「删除这个性格」的丢掉；现有槽位沿用原等级；超出原本数量的槽位=新加的，等级给 1。
    返回 (chars, dup)：dup 是重复出现的性格 id（同一个人不能有两种相同性格）。
    """
    chars, seen, dup = [], set(), []
    for i, txt in picks:
        txt = (txt or '').strip()
        if txt == CHAR_DEL or txt == CHAR_NOADD:
            continue
        m = re.match(r'^\s*(\d+)', txt)
        if not m:
            continue
        cid = int(m.group(1))
        if cid in seen:
            dup.append(cid)
            continue
        seen.add(cid)
        chars.append((cid, base[i]['lv'] if i < len(base) else 1))
    return chars, sorted(set(dup))
GRP_LABEL = {0: '武器', 1: '防具', 2: '佩饰', 3: '坐骑', 4: '头盔', 5: '盾牌', 6: '任务道具/特殊',
             7: '礼物珍玩', 8: '书籍', 9: '称号证书/丹药/制造书', 10: '话题',
             11: '魂与技（军/武/智）', 12: '材料货物'}
# 这几个页签里「价值 0 / 没有价值」的行是占位垃圾数据（如「***军魂数据规则***」），不显示
ZERO_PRICE_TABS = {'军魂军技', '武魂武技', '智魂智技'}
# 「各种添加」的分类页签（对应 HTML 版）
ADD_TABS = [
    ('武器', ['武器', 'MOD武器']),
    ('防具', ['防具', 'MOD防具', '头盔', 'MOD头盔', '盾牌', 'MOD盾牌']),
    ('饰品', ['佩饰', 'MOD佩饰', '坐骑', 'MOD坐骑']),
    ('道具', ['丹药符箓']),
    ('重要', ['任务道具', '地图藏宝图']),
    ('材料', ['材料']),          # 建筑(JZ*)不能进背包，已去掉
    ('其它', ['书籍', '礼物珍玩', '话题']),
    ('称号证书', ['称号证书', 'MOD称号证书']),
    ('制造书', ['制造书', 'MOD制造书']),
    ('军魂军技', ['军魂', 'MOD军魂', '军技']),
    ('武魂武技', ['武魂', 'MOD武魂', '武技']),
    ('智魂智技', ['智魂', '智技']),
]


def base_dir():
    return getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))


def exe_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def find_asset(name):
    dirs = [exe_dir(), base_dir(),
            os.path.dirname(exe_dir()), os.path.dirname(base_dir()),
            os.path.join(os.path.dirname(exe_dir()), '存档修改器'),
            r'F:/WB/2026-10-07-16-23-32/存档修改器']
    for d in dirs:
        if not d: continue
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    return None


# ------------------------------------------------------------------ 物品库
def _looks_like_game(p):
    """判断某个目录是不是游戏根目录（认 ThreeKingdom_Data/StreamingAssets/Json 这层）。"""
    return bool(p) and os.path.isfile(os.path.join(
        p, 'ThreeKingdom_Data', 'StreamingAssets', 'Json', 'CityTechnology.json'))


def find_game_root():
    """自动找游戏根目录 —— **不写死盘符**，换电脑、换安装位置都能找到。

    探测顺序：① 上次记住的路径（exe 旁的「游戏路径.txt」）→ ② 修改器自己所在目录及往上两级
    （万一把修改器放进游戏目录）→ ③ Steam：注册表 SteamPath/InstallPath + libraryfolders.vdf
    里登记的所有库 → ④ C~H 盘的常见安装路径。
    找到后把结果写回「游戏路径.txt」，下次直接命中。找不到返回 None（界面显示 CT id，不影响改）。
    """
    here = exe_dir()
    mem = os.path.join(here, '游戏路径.txt')
    cands = []
    try:
        if os.path.isfile(mem):
            cands.append(io.open(mem, encoding='utf-8').read().strip())
    except Exception:
        pass
    p = here
    for _ in range(3):                      # 修改器就在游戏里/旁边的情况
        cands.append(p)
        p = os.path.dirname(p)
    try:                                    # Steam
        import winreg
        for hive, key in ((winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam'),
                          (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node\Valve\Steam')):
            try:
                with winreg.OpenKey(hive, key) as k:
                    for name in ('SteamPath', 'InstallPath'):
                        try:
                            sp = winreg.QueryValueEx(k, name)[0]
                        except Exception:
                            continue
                        cands.append(sp)
                        vdf = os.path.join(sp, 'steamapps', 'libraryfolders.vdf')
                        try:
                            for line in io.open(vdf, encoding='utf-8', errors='ignore'):
                                m = re.search(r'"path"\s+"([^"]+)"', line)
                                if m:
                                    cands.append(m.group(1).replace('\\\\', '\\'))
                        except Exception:
                            pass
            except Exception:
                pass
    except Exception:
        pass
    for drv in 'CDEFGH':                    # 常见路径兜底
        for sub in (r'SteamLibrary\steamapps\common\LegendOfHeros',
                    r'Steam\steamapps\common\LegendOfHeros',
                    r'Program Files (x86)\Steam\steamapps\common\LegendOfHeros',
                    r'Program Files\Steam\steamapps\common\LegendOfHeros',
                    r'Games\LegendOfHeros', r'LegendOfHeros'):
            cands.append('%s:/%s' % (drv, sub))
    seen = set()
    for c in cands:
        if not c:
            continue
        c = c.replace('\\', '/').rstrip('/')
        if c in seen:
            continue
        seen.add(c)
        for root in (c,
                     os.path.join(c, 'steamapps', 'common', 'LegendOfHeros'),
                     os.path.join(c, 'common', 'LegendOfHeros')):
            if _looks_like_game(root):
                try:
                    io.open(mem, 'w', encoding='utf-8').write(root)
                except Exception:
                    pass
                return root
    return None


class Catalog:
    def __init__(self):
        self.items = {}       # id -> [名称,分类,推荐组,等级,价格,简述(,魂占用)]
        self.pets = {}
        self.city_id = {}
        self.city_name = {}
    def load(self, path):
        src = io.open(path, encoding='utf-8').read()
        for key, dst in (('CITY_ID', 'city_id'), ('CITY_NAME', 'city_name'),
                         ('GRP_LABEL', 'grp_label'), ('ITEM_CAT', 'items'), ('PET_CAT', 'pets')):
            i = src.find('window.%s=' % key)
            if i < 0: continue
            i += len('window.%s=' % key)
            j = src.find(';\n', i)
            try:
                setattr(self, dst, json.loads(src[i:j]))
            except Exception:
                pass
        self.loaded = bool(self.items)
        return self.loaded

    # ---- 查询
    def info(self, iid):
        v = self.items.get(iid)
        if v: return v
        m = re.match(r'^(.+)_FORGE_(\d+)$', iid or '')
        if m and m.group(1) in self.items:
            b = self.items[m.group(1)]
            return [b[0] + '（锻造件 %s）' % m.group(2)] + list(b[1:]) + [-1]
        return None

    def name(self, iid):
        v = self.info(iid)
        return v[0] if v else iid

    def kind(self, iid):
        v = self.info(iid)
        return v[1] if v else ''

    def grp(self, iid):
        v = self.info(iid)
        try:
            return int(v[2])
        except Exception:
            return 12

    def level(self, iid):
        v = self.info(iid)
        try:
            return int(v[3])
        except Exception:
            return None

    def price(self, iid):
        v = self.info(iid)
        try:
            return int(v[4])
        except Exception:
            return None

    def soul(self, iid):
        v = self.info(iid)
        if v and len(v) > 6 and isinstance(v[6], int) and v[6] >= 0:
            return v[6]
        return None

    def group_label(self, g):
        return self.grp_label.get(str(g)) or self.grp_label.get(g) or ('组 %s' % g)


CAT = Catalog()


def update_catalog(game_root):
    """调用打包进来的 update_item_catalog.py 重新生成物品库。"""
    src_path = find_asset('update_item_catalog.py')
    if not src_path:
        raise RuntimeError('找不到 update_item_catalog.py')
    out = os.path.join(exe_dir(), '物品库.js')
    src = io.open(src_path, encoding='utf-8').read()
    argv_bak = sys.argv[:]
    sys.argv = [src_path, game_root, out]
    buf = io.StringIO()
    so_bak, sys.stdout = sys.stdout, buf
    try:
        exec(compile(src, src_path, 'exec'), {'__name__': '__main__', '__file__': src_path})
    finally:
        sys.stdout = so_bak
        sys.argv = argv_bak
    CAT.load(out)
    return out, buf.getvalue()

# ------------------------------------------------------------------ 诊断
class Diag:
    """运行时日志 + 异常捕获 + 一键导出诊断包（给开发者定位 bug 用）。"""
    def __init__(self):
        self.lines = []
        self.errors = []
        self.started = time.strftime('%Y-%m-%d %H:%M:%S')
        self.ops = []

    def log(self, msg):
        t = time.strftime('%H:%M:%S')
        self.lines.append('[%s] %s' % (t, msg))
        if len(self.lines) > 4000:
            self.lines = self.lines[-2000:]

    def op(self, kind, detail=''):
        self.ops.append('%s\t%s\t%s' % (time.strftime('%Y-%m-%d %H:%M:%S'), kind, detail))
        self.log('%s %s' % (kind, detail))

    def err(self, where, exc=None):
        tb = traceback.format_exc() if exc is None else ''.join(
            traceback.format_exception(type(exc), exc, exc.__traceback__))
        self.errors.append('===== %s @ %s =====\n%s' % (where, time.strftime('%Y-%m-%d %H:%M:%S'), tb))
        self.log('!! 出错(%s): %s' % (where, tb.strip().splitlines()[-1] if tb.strip() else '?'))


DIAG = Diag()


def hex_dump(b, off, before=0x40, after=0x80, tag=''):
    """把 off 附近的一段字节 dump 成文本（诊断包里用，避免直接传整个存档）。"""
    s = max(0, off - before)
    e = min(len(b), off + after)
    out = ['--- %s  %#x ~ %#x（★ = 关注点 %#x）---' % (tag, s, e, off)]
    for r in range(s - (s % 16), e, 16):
        c = bytes(b[r:min(r + 16, len(b))])
        txt = ''.join(chr(x) if 32 <= x < 127 else '.' for x in c)
        star = ' <<<' if r <= off < r + 16 else ''
        out.append('%#010x: %-47s  %s%s' % (r, ' '.join('%02x' % x for x in c), txt, star))
    return '\n'.join(out)


def env_report(app=None, save=None):
    """环境 + 定位结果报告（纯文本）。"""
    L = []
    L.append('===== 环境 =====')
    L.append('程序版本 : %s' % APP)
    L.append('导出时间 : %s' % time.strftime('%Y-%m-%d %H:%M:%S'))
    L.append('启动时间 : %s' % DIAG.started)
    L.append('操作系统 : %s' % platform.platform())
    L.append('Python   : %s' % sys.version.replace('\n', ' '))
    L.append('可执行   : %s' % sys.executable)
    L.append('打包模式 : %s' % ('PyInstaller 单文件' if getattr(sys, 'frozen', False) else '源码运行'))
    L.append('程序目录 : %s' % exe_dir())
    L.append('物品库   : %s（%d 条 / 宠物 %d 条）' % (
        (find_asset('物品库.js') or '未找到'), len(CAT.items), len(CAT.pets)))
    if app is not None:
        L.append('存档目录 : %s（存在=%s）' % (app.save_dir, os.path.isdir(app.save_dir)))
        L.append('游戏目录 : %s' % (app.game_root or '未自动找到'))
    cfg = load_config()
    L.append('config   : %s' % json.dumps(cfg, ensure_ascii=False))
    L.append('')
    sv = save if save is not None else (app.save if app else None)
    L.append('===== 存档 =====')
    if not sv:
        L.append('（当前没有载入存档）')
        return '\n'.join(L)
    b = sv.raw
    L.append('文件     : %s' % (app.save_path if app else '?'))
    L.append('大小     : %d 字节' % len(b))
    L.append('版本戳   : %d（槽位 %d）' % (sv.ver, sv.slot))
    L.append('当前地点 : %s' % sv.place)
    L.append('头部字符串: %s' % [s2 for _, s2 in sv.strings][:12])
    L.append('')
    L.append('--- 金钱 ---')
    L.append('值 %d   偏移 %s   副本 %s' % (sv.money, hex(sv.money_off),
                                        [hex(x) for x in sv.money_copies]))
    L.append('')
    L.append('--- 武将 ---')
    located = sum(1 for h in sv.heroes if h.get('six_off') is not None)
    L.append('记录数 %d   六维已定位 %d' % (len(sv.heroes), located))
    for h in sv.heroes[:5]:
        six = [sc.i32(b, h['six_off'] + j * 4) for j in range(6)] if h.get('six_off') is not None else None
        L.append('   %-10s %-6s tal=%#010x six=%s %s' % (
            h['id'], h.get('name', ''), h['tal_off'],
            hex(h['six_off']) if h.get('six_off') is not None else '未定位', six))
    L.append('')
    L.append('--- 背包 ---')
    if sv.bag:
        g = sv.bag['groups']
        L.append('区间 %s ~ %s   共 %d 件' % (hex(sv.bag['start']), hex(sv.bag['end']),
                                           sum(len(x['items']) for x in g)))
        L.append('各组件数: %s' % ' '.join('%d:%d' % (i, len(x['items'])) for i, x in enumerate(g)))
        first = next((it['id'] for x in g for it in x['items']), '?')
        L.append('首条物品: %s' % first)
    else:
        L.append('未定位 ✗')
    L.append('')
    L.append('--- 称号 ---')
    if sv.titles:
        L.append('count@%s  条数 %d  前 8 条: %s' % (hex(sv.titles['count_off']), len(sv.titles['ids']),
                                                 ' '.join(sv.titles['ids'][:8])))
        L.append('候选列表数 %d（占比 %s）' % (len(sv.title_lists),
                                          [round(x['ratio'], 2) for x in sv.title_lists[:5]]))
    else:
        L.append('未定位 ✗')
    L.append('')
    L.append('--- 势力资源 ---')
    f = sv.faction or {}
    L.append('判定 %s  科技 %s@%s  策略 %s@%s' % (
        f.get('kind'), f.get('tech'), hex(f.get('tech_off') or 0), f.get('strat'),
        hex(f.get('strat_off') or 0)))
    L.append('')
    L.append('--- 城市 ---')
    L.append('定位 %d 座' % len(sv.cities))
    for cid, c in list(sorted(sv.cities.items()))[:6]:
        L.append('   %-8s money=%-9d food=%-9d pop=%-8d sec=%.1f @%s' % (
            cid, c['money'], c['food'], c['pop'], c['security'], hex(c['sec'])))
    L.append('')
    L.append('--- 宠物 ---')
    if sv.pets:
        L.append('count@%s  共 %d 只' % (hex(sv.pets['count_off']), sv.pets['count']))
        for p in sv.pets['recs']:
            L.append('   %-12s %-8s 族=%-4s 上限=%-3d 攻=%-4d 血=%d @%s' % (
                p['id'], p['name'], p['fam'], p['lv_limit'], p['atk'], p['hp'], hex(p['off'])))
    else:
        L.append('未定位 ✗')
    return '\n'.join(L)


def export_diag(app, problem, include_save=False, out_dir=None, out_path=None):
    """导出诊断包（zip）：环境 + 定位结果 + 日志 + 报错 + 关键区域字节 + 可选完整存档。"""
    import zipfile
    stamp = time.strftime('%Y%m%d_%H%M%S')
    out_dir = out_dir or exe_dir()
    path = out_path or os.path.join(out_dir, '诊断_%s.zip' % stamp)
    sv = app.save if app else None
    parts = {}
    parts['环境与定位.txt'] = env_report(app, sv)
    parts['运行日志.txt'] = '\n'.join(DIAG.lines) or '（无）'
    parts['操作记录.txt'] = '\n'.join(DIAG.ops) or '（无）'
    if DIAG.errors:
        parts['报错.txt'] = '\n\n'.join(DIAG.errors)
    parts['问题描述.txt'] = problem or '（用户没有填写）'
    parts['说明.txt'] = (
        '这个压缩包是「%s」自动导出的诊断数据，用于定位 bug。\n\n'
        '请把：\n  1) 这个 zip\n  2) 你遇到的问题（怎么操作、期望什么、实际什么）\n'
        '一起发给开发者。\n\n包内文件：\n'
        '  环境与定位.txt —— 系统环境 + 存档解析结果（各字段的偏移与数值）\n'
        '  运行日志.txt / 操作记录.txt —— 你操作时程序记录的过程\n'
        '  报错.txt —— 程序捕获到的异常堆栈（没有则为空）\n'
        '  字节片段/*.txt —— 关键位置附近的原始字节（便于核对结构）\n'
        '  config.json —— 你的路径设置\n'
        '  save/ 目录 —— 只有你勾选「附带完整存档」时才有\n' % APP)
    if sv:
        b = sv.raw
        seg = []
        seg.append(hex_dump(b, 0x00, 0x00, 0x100, '文件头'))
        if sv.money_off >= 0:
            seg.append(hex_dump(b, sv.money_off, 0x40, 0x40, '头部金钱'))
        for c in sv.money_copies[1:2]:
            seg.append(hex_dump(b, c, 0x40, 0x40, '资产块金钱'))
        for h in sv.heroes[:3]:
            seg.append(hex_dump(b, h['tal_off'], 0x20, 0x60, '武将 %s 资质块' % h['id']))
            if h.get('six_off') is not None:
                seg.append(hex_dump(b, h['six_off'], 0x30, 0x90, '武将 %s 六维块' % h['id']))
        if sv.bag:
            seg.append(hex_dump(b, sv.bag['start'], 0x00, 0x100, '背包起点'))
            seg.append(hex_dump(b, sv.bag['end'], 0x40, 0x40, '背包终点'))
        if sv.titles:
            seg.append(hex_dump(b, sv.titles['count_off'], 0x20, 0x80, '称号列表'))
        if sv.faction and sv.faction.get('tech_off'):
            seg.append(hex_dump(b, sv.faction['tech_off'], 0x40, 0x80, '科技/策略'))
        if sv.faction and sv.faction.get('strat_off'):
            seg.append(hex_dump(b, sv.faction['strat_off'], 0x40, 0x60, '势力资源'))
        for cid, c in list(sorted(sv.cities.items()))[:2]:
            seg.append(hex_dump(b, c['sec'] - 0x14, 0x00, 0x60, '城市 %s' % cid))
        if sv.pets:
            seg.append(hex_dump(b, sv.pets['list_start'], 0x20, 0x100, '宠物首条'))
        parts['字节片段/关键区域.txt'] = '\n\n'.join(seg)
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, txt in parts.items():
            z.writestr(name, txt)
        cp = config_path()
        if os.path.exists(cp):
            z.write(cp, 'config.json')
        if include_save and app and app.save_path and os.path.exists(app.save_path):
            z.write(app.save_path, 'save/' + os.path.basename(app.save_path))
    return path



# ------------------------------------------------------------------ 主界面
class App:
    def __init__(self, root):
        self.root = root
        self.save = None
        self.save_path = None
        self.game_root = detect_game()
        self.save_dir = detect_save_dir()
        self.bag_edit = None          # 背包编辑用副本 [{id,qty}]
        self.hero_edits = {}          # 武将索引 -> {key: 值}
        self.hero_chars = {}
        self.hero_title_edits = {}    # 武将 id -> [称号 id, ...]（记录内第一条，整段重建）          # 武将索引 -> [(性格id, 等级), ...]：性格整段重建（和称号同一套路）
        self.pet_edits = {}           # 宠物下标 -> {key: 值}
        root.title(APP)
        root.geometry('1180x820')
        root.minsize(1020, 700)
        self._style()
        self._load_catalog_initial()
        self._build_ui()
        # 上次自动更新留下的 .old 文件，启动后顺手删掉
        try:
            UP.cleanup_old()
        except Exception:
            pass
        if not self.game_root:
            self.status('没自动找到游戏目录（「更新物品库」需要它，可在常用功能里手动指定）')

    # -------------------------------------------------- 杂项
    def _style(self):
        st = ttk.Style()
        try:
            st.theme_use('vista')
        except Exception:
            pass
        st.configure('TNotebook.Tab', padding=(16, 8), font=('Microsoft YaHei', 10))
        st.configure('Treeview', font=('Microsoft YaHei', 9), rowheight=22)
        st.configure('Treeview.Heading', font=('Microsoft YaHei', 9, 'bold'))
        self.root.option_add('*Font', ('Microsoft YaHei', 9))

    def _load_catalog_initial(self):
        p = find_asset('物品库.js')
        if p:
            CAT.load(p)
        if not CAT.loaded:
            # 没有物品库就先尝试用游戏目录生成一次（首次运行会稍慢）
            try:
                update_catalog(self.game_root)
            except Exception:
                pass

    # -------------------------------------------------- 统一列表风格
    def make_table(self, parent, cols, height=16, tips=None):
        """所有列表统一的样式：表头与单元格居中、自带纵向滚动条、支持鼠标滚轮、可带悬停提示。
        cols = [(列key, 表头, 宽度), ...]；tips = {列key: 提示取值函数}（可选）"""
        wrap = ttk.Frame(parent)
        tv = ttk.Treeview(wrap, columns=[c[0] for c in cols], show='headings',
                          selectmode='extended', height=height)
        for key, title, width in cols:
            tv.heading(key, text=title, anchor='center')
            tv.column(key, width=width, anchor='center', stretch=True)
        vs = ttk.Scrollbar(wrap, orient='vertical', command=tv.yview)
        tv.configure(yscrollcommand=vs.set)
        tv.pack(side='left', fill='both', expand=True)
        vs.pack(side='right', fill='y')
        tv.bind('<MouseWheel>', lambda e: tv.yview_scroll(-1 if e.delta > 0 else 1, 'units'))
        if tips:
            self._bind_tip(tv, tips)
        return wrap, tv

    def _bind_tip(self, tv, tips):
        tip = {'win': None}
        def hide(_=None):
            if tip['win']:
                tip['win'].destroy(); tip['win'] = None
        def show(e):
            row = tv.identify_row(e.y)
            if not row: return hide()
            vals = tv.item(row, 'values')
            col = tv.identify_column(e.x)
            try:
                idx = int(col.replace('#', '')) - 1
            except Exception:
                idx = 0
            keys = [c for c in tips if tv['columns'].index(c) == idx]
            txt = None
            if keys:
                fn = tips[keys[0]]
                txt = fn(vals) if callable(fn) else fn
            if not txt: return hide()
            if tip['win']:
                tip['win'].destroy()
            w = tk.Toplevel(self.root)
            w.wm_overrideredirect(True)
            w.attributes('-topmost', True)
            tk.Label(w, text=txt, justify='left', background='#ffffe0', relief='solid',
                     borderwidth=1, font=('Microsoft YaHei', 9), wraplength=460, padx=8, pady=5
                     ).pack()
            w.geometry('+%d+%d' % (e.x_root + 14, e.y_root + 18))
            tip['win'] = w
        tv.bind('<Motion>', show)
        tv.bind('<Leave>', hide)

    def make_scroll(self, parent, height=260):
        """可滚动容器（Canvas + 内嵌 Frame），返回 (外层控件, 放内容的 Frame)。"""
        wrap = ttk.Frame(parent)
        canvas = tk.Canvas(wrap, height=height, highlightthickness=0, background='#f5f6f8')
        vs = ttk.Scrollbar(wrap, orient='vertical', command=canvas.yview)
        inner = ttk.Frame(canvas)
        win = canvas.create_window((0, 0), window=inner, anchor='nw')
        canvas.configure(yscrollcommand=vs.set)
        canvas.pack(side='left', fill='both', expand=True)
        vs.pack(side='right', fill='y')
        inner.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda e: canvas.itemconfigure(win, width=e.width))
        for w in (canvas, inner):
            w.bind('<MouseWheel>', lambda e: canvas.yview_scroll(-1 if e.delta > 0 else 1, 'units'))
        return wrap, inner

    def status(self, text):
        self.lbl_status.configure(text=text)
        self.root.update_idletasks()

    # -------------------------------------------------- 界面骨架
    def _build_ui(self):
        top = ttk.Frame(self.root, padding=(10, 8, 10, 0))
        top.pack(fill='x')
        # 程序名只在窗口标题栏显示，界面里不再重复（2026-10-22 按用户要求去掉）
        head = ttk.Frame(top); head.pack(fill='x')
        ttk.Label(head, text=DISCLAIMER, font=('Microsoft YaHei', 9, 'bold'),
                  foreground='#c0392b').pack(side='left')
        self.lbl_status = ttk.Label(head, text='未载入存档', foreground='#666')
        self.lbl_status.pack(side='right')

        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill='both', expand=True, padx=10, pady=8)
        self.tab_common = ttk.Frame(self.nb); self.nb.add(self.tab_common, text='常用功能')
        self.tab_hero = ttk.Frame(self.nb);   self.nb.add(self.tab_hero, text='人物修改')
        self.tab_add = ttk.Frame(self.nb);    self.nb.add(self.tab_add, text='各种添加')
        self.tab_bag = ttk.Frame(self.nb);    self.nb.add(self.tab_bag, text='背包管理')
        self.tab_title = ttk.Frame(self.nb);  self.nb.add(self.tab_title, text='称号与资源')
        self.tab_city = ttk.Frame(self.nb);   self.nb.add(self.tab_city, text='城市属性修改')
        self.tab_pet = ttk.Frame(self.nb);    self.nb.add(self.tab_pet, text='宠物修改')
        self.tab_help = ttk.Frame(self.nb);   self.nb.add(self.tab_help, text='使用方法')
        self.tab_log = ttk.Frame(self.nb);    self.nb.add(self.tab_log, text='更新日志')
        self._ui_common(); self._ui_hero(); self._ui_add(); self._ui_bag()
        self._ui_title(); self._ui_city(); self._ui_pet(); self._ui_help(); self._ui_log()

    # -------------------------------------------------- 常用功能
    def _ui_common(self):
        f = self.tab_common
        box = ttk.LabelFrame(f, text='存档', padding=12)
        box.pack(fill='x', padx=8, pady=8)
        row = ttk.Frame(box); row.pack(fill='x')
        ttk.Button(row, text='读取存档…', command=self.open_save, width=16).pack(side='left')
        ttk.Button(row, text='备份存档…', command=self.backup_save, width=16).pack(side='left', padx=6)
        ttk.Button(row, text='生成并保存新存档…', command=self.save_new, width=22).pack(side='left')
        ttk.Button(row, text='撤销全部修改', command=self.revert_all, width=14).pack(side='left', padx=6)
        ttk.Button(row, text='导出诊断数据…', command=self.diag_dialog, width=16).pack(side='left', padx=6)
        row2 = ttk.Frame(box); row2.pack(fill='x', pady=(8, 0))
        ttk.Label(row2, text='存档目录：', foreground='#666').pack(side='left')
        self.lbl_savedir = ttk.Label(row2, text=self.save_dir, foreground='#666')
        self.lbl_savedir.pack(side='left')
        ttk.Button(row2, text='浏览…', width=8, command=self.pick_save_dir).pack(side='left', padx=6)
        ttk.Label(row2, text='（自动探测，可手动指定；会记住）', foreground='#999').pack(side='left')
        self.lbl_saveinfo = ttk.Label(box, text='（还没有载入存档）', justify='left')
        self.lbl_saveinfo.pack(anchor='w', pady=(6, 0))

        box2 = ttk.LabelFrame(f, text='物品库（更新后新 MOD / 新物品才会出现在「各种添加」里）', padding=12)
        box2.pack(fill='x', padx=8, pady=8)
        r2 = ttk.Frame(box2); r2.pack(fill='x')
        ttk.Button(r2, text='更新物品库', command=self.do_update_catalog, width=16).pack(side='left')
        ttk.Label(r2, text='游戏目录：').pack(side='left', padx=(14, 2))
        self.var_game = tk.StringVar(value=self.game_root)
        ttk.Entry(r2, textvariable=self.var_game, width=52).pack(side='left')
        ttk.Button(r2, text='浏览…', command=self.pick_game, width=8).pack(side='left', padx=6)
        self.lbl_cat = ttk.Label(box2, text=self.cat_text(), foreground='#666')
        self.lbl_cat.pack(anchor='w', pady=(8, 0))
        if not self.game_root:
            ttk.Label(box2, text='⚠ 没自动找到游戏目录，请点「浏览…」手动指定后再点「更新物品库」',
                      foreground='#bf3a2b').pack(anchor='w', pady=(4, 0))

        # 版本 / 检查更新（2026-10-23 新增：GitHub Releases + 国内镜像，用户点了才联网）
        box_u = ttk.LabelFrame(f, text='版本', padding=12)
        box_u.pack(fill='x', padx=8, pady=8)
        ru = ttk.Frame(box_u); ru.pack(fill='x')
        self.btn_upd = ttk.Button(ru, text='检查更新', command=self.do_check_update, width=16)
        self.btn_upd.pack(side='left')
        self.lbl_upd = ttk.Label(ru, text=self._upd_text(), foreground='#666')
        self.lbl_upd.pack(side='left', padx=(14, 0))
        self._upd_latest = None

        box3 = ttk.LabelFrame(f, text='存档信息', padding=12)
        box3.pack(fill='both', expand=True, padx=8, pady=8)
        self.txt_info = tk.Text(box3, height=10, wrap='none', font=('Consolas', 9))
        self.txt_info.pack(fill='both', expand=True)

    def cat_text(self):
        return '物品库：%d 条%s' % (len(CAT.items), '' if CAT.loaded else '（未载入）')

    # -------------------------------------------------- 检查更新
    def _upd_text(self):
        if not UP.is_frozen():
            return '当前 V%s · 源码运行模式，不参与自动更新' % UP.VERSION_STR
        if not UP.norm_repo(UP.config_repo() or UP.GITHUB_REPO):
            return '当前 V%s · 还没有配置更新地址' % UP.VERSION_STR
        return '当前 V%s' % UP.VERSION_STR

    def do_check_update(self):
        """检查更新（后台线程查 GitHub API，避免卡界面）。"""
        if not UP.is_frozen():
            messagebox.showinfo('检查更新',
                                '当前是以源码方式运行的，没有可替换的程序文件。\n\n'
                                '请用打包后的 exe 才能使用自动更新。')
            return
        if not UP.norm_repo(UP.config_repo() or UP.GITHUB_REPO):
            messagebox.showinfo('还没有配置更新地址',
                                '自动更新需要先把程序发布到 GitHub Releases，'
                                '再在 config.json 里填 update_repo（形如 "用户名/仓库名"）。')
            return
        if getattr(self, '_upd_busy', False):
            return
        self._upd_busy = True
        self.btn_upd.configure(state='disabled', text='检查中…')
        self.lbl_upd.configure(text='正在查询最新版本…', foreground='#666')
        self.status('正在检查更新…')

        def work():
            try:
                info = UP.check_latest()
            except Exception as e:
                self.root.after(0, lambda: self._upd_failed(e))
                return
            self.root.after(0, lambda: self._upd_got(info))

        threading.Thread(target=work, daemon=True).start()

    def _upd_reset(self):
        self._upd_busy = False
        try:
            self.btn_upd.configure(state='normal', text='检查更新')
        except Exception:
            pass

    def _upd_failed(self, err):
        self._upd_reset()
        self.lbl_upd.configure(text='当前 V%s · 检查失败' % UP.VERSION_STR, foreground='#bf3a2b')
        self.status('检查更新失败')
        messagebox.showwarning('检查更新失败',
                               '没能查到最新版本：\n\n%s\n\n（可以稍后再试，或手动去发布页下载）' % (err,))

    def _upd_got(self, info):
        self._upd_reset()
        latest = info['version']
        if not UP.is_newer(latest, UP.VERSION):
            self.lbl_upd.configure(text='当前 V%s · 已是最新版本' % UP.VERSION_STR, foreground='#2e7d32')
            self.status('已是最新版本')
            messagebox.showinfo('已是最新版本', '当前 V%s 就是最新版本。' % UP.VERSION_STR)
            return
        new_ver = '.'.join(str(x) for x in latest)
        self._upd_latest = info
        self.lbl_upd.configure(text='当前 V%s · 发现新版本 V%s' % (UP.VERSION_STR, new_ver),
                               foreground='#c0392b')
        self.status('发现新版本 V%s' % new_ver)
        self._upd_confirm(info)

    def _upd_confirm(self, info):
        """弹窗展示新版本信息，用户确认后下载并替换。"""
        new_ver = '.'.join(str(x) for x in info['version'])
        try:
            asset = UP.pick_asset(info['assets'])
        except Exception as e:
            messagebox.showwarning('这个版本没有可用的安装包', str(e))
            return
        win = tk.Toplevel(self.root)
        win.title('发现新版本 V%s' % new_ver)
        win.geometry('620x440')
        try:
            win.transient(self.root); win.grab_set()
        except Exception:
            pass
        ttk.Label(win, text='当前版本：V%s    最新版本：V%s' % (UP.VERSION_STR, new_ver),
                  font=('Microsoft YaHei', 10, 'bold')).pack(anchor='w', padx=16, pady=(14, 6))
        ttk.Label(win, text='安装包：%s（%.1f MB）' % (asset['name'], asset['size'] / 1048576.0),
                  foreground='#666').pack(anchor='w', padx=16)
        ttk.Label(win, text='更新说明：').pack(anchor='w', padx=16, pady=(10, 2))
        body = tk.Text(win, height=10, wrap='word', font=('Microsoft YaHei', 9))
        body.pack(fill='both', expand=True, padx=16, pady=(0, 6))
        body.insert('1.0', info['notes'] or '（这个版本没有写说明）')
        body.configure(state='disabled')
        lbl = ttk.Label(win, text='', foreground='#666')
        lbl.pack(anchor='w', padx=16)
        bar = ttk.Progressbar(win, length=560, mode='determinate')
        bar.pack(fill='x', padx=16, pady=(4, 10))
        rowb = ttk.Frame(win); rowb.pack(fill='x', padx=16, pady=(0, 14))
        btn_now = ttk.Button(rowb, text='下载并更新', width=16)
        btn_now.pack(side='right')
        ttk.Button(rowb, text='以后再说', width=10, command=win.destroy).pack(side='right', padx=8)

        def start():
            btn_now.configure(state='disabled', text='下载中…')
            lbl.configure(text='正在下载…')

            def work():
                dest = UP.new_file_placeholder(asset['name'])
                def prog(got, total, msg):
                    def apply():
                        if msg:
                            lbl.configure(text=msg)
                            return
                        if total:
                            bar.configure(maximum=100,
                                          value=min(100, got * 100.0 / total))
                            lbl.configure(text='正在下载… %.1f / %.1f MB'
                                          % (got / 1048576.0, total / 1048576.0))
                    self.root.after(0, apply)
                try:
                    UP.download(asset['url'], dest, expect_size=asset['size'],
                                on_progress=prog)
                except Exception as e:
                    self.root.after(0, lambda: self._upd_dl_failed(win, btn_now, lbl, e))
                    return
                self.root.after(0, lambda: self._upd_dl_done(win, dest))

            threading.Thread(target=work, daemon=True).start()

        btn_now.configure(command=start)

    def _upd_dl_failed(self, win, btn, lbl, err):
        try:
            btn.configure(state='normal', text='重新下载')
        except Exception:
            pass
        lbl.configure(text='下载失败', foreground='#bf3a2b')
        messagebox.showerror('下载失败',
                             '没能下载新版本：\n\n%s\n\n可以稍后再试。' % (err,), parent=win)

    def _upd_dl_done(self, win, dest):
        try:
            win.destroy()
        except Exception:
            pass
        exe = UP.app_path()
        if not messagebox.askyesno('下载完成',
                                   '新版本已下载完成。\n\n'
                                   '现在会替换当前程序并重新启动（大约几秒）。\n'
                                   '如果程序装在受保护目录（如 Program Files），可能没有写权限。\n\n'
                                   '现在就更新？'):
            try:
                os.remove(dest)
            except Exception:
                pass
            self.lbl_upd.configure(text='当前 V%s · 已下载但未安装' % UP.VERSION_STR,
                                   foreground='#666')
            return
        try:
            UP.apply_and_restart(dest, exe)
        except Exception as e:
            messagebox.showerror('更新失败',
                                 '替换程序失败：\n\n%s\n\n'
                                 '下载好的新版本还在：\n%s\n可以手动替换。' % (e, dest))
            return
        self.status('正在重启…')
        try:
            self.root.destroy()
        except Exception:
            pass
        sys.exit(0)

    def diag_dialog(self):
        """导出诊断包：填问题描述（可选带走完整存档）。"""
        win = tk.Toplevel(self.root)
        win.title('导出诊断数据')
        win.geometry('620x430')
        try:
            win.transient(self.root)
        except Exception:
            pass
        ttk.Label(win, text='把遇到的问题写清楚（怎么操作 / 期望什么 / 实际什么），会和诊断数据一起打包：',
                  wraplength=580, justify='left').pack(anchor='w', padx=14, pady=(12, 4))
        txt = tk.Text(win, height=9, font=('Microsoft YaHei', 9))
        txt.pack(fill='both', expand=True, padx=14, pady=4)
        var_save = tk.BooleanVar(value=False)
        ttk.Checkbutton(win, text='附带完整存档（只在你愿意时才勾；能让定位更准，但包含你的整个游戏存档）',
                        variable=var_save).pack(anchor='w', padx=14, pady=(2, 0))
        info = ttk.Label(win, text='', foreground='#666', wraplength=580, justify='left')
        info.pack(anchor='w', padx=14, pady=(6, 0))
        qb = ttk.Frame(win); qb.pack(fill='x', padx=14, pady=(8, 12))

        def do_export():
            p = None
            default = '诊断_%s.zip' % time.strftime('%Y%m%d_%H%M%S')
            path = filedialog.asksaveasfilename(
                title='诊断包保存到…', initialfile=default,
                initialdir=exe_dir(), defaultextension='.zip',
                filetypes=[('压缩包', '*.zip'), ('全部', '*.*')])
            if not path:
                return
            try:
                p = export_diag(self, txt.get('1.0', 'end').strip(), var_save.get(), out_path=path)
            except Exception as err:
                DIAG.err('导出诊断包')
                messagebox.showerror('导出失败', str(err)); return
            DIAG.op('导出诊断包', p)
            info.configure(text='已导出：%s\n把「这个文件 + 你的问题描述」发给开发者即可。' % p)
            if messagebox.askyesno('导出完成', '已导出：\n%s\n\n现在打开它所在的文件夹？' % p):
                try:
                    os.startfile(os.path.dirname(p))
                except Exception:
                    pass

        ttk.Button(qb, text='导出诊断包', command=do_export).pack(side='left')
        ttk.Button(qb, text='关闭', command=win.destroy).pack(side='right')
        self.diag_dlg = win
        return win

    def pick_save_dir(self):
        d = filedialog.askdirectory(title='选择存档目录（含 Save0.dat / Save1.dat 的那个文件夹）',
                                    initialdir=self.save_dir if os.path.isdir(self.save_dir) else None)
        if not d:
            return
        self.save_dir = d
        cfg = load_config(); cfg['saveDir'] = d; save_config(cfg)
        self.lbl_savedir.configure(text=d)
        self.status('存档目录已记住：%s' % d)

    def pick_game(self):
        p = filedialog.askdirectory(title='选择游戏根目录（含 ThreeKingdom_Data 的那一层）')
        if p:
            self.var_game.set(p)
            cfg = load_config(); cfg['game'] = p; save_config(cfg)

    def do_update_catalog(self):
        self.game_root = self.var_game.get().strip() or self.game_root
        self.status('正在更新物品库…')
        try:
            out, log = update_catalog(self.game_root)
        except Exception as e:
            messagebox.showerror('更新失败', str(e)); self.status('更新失败'); return
        self.lbl_cat.configure(text=self.cat_text())
        self._refresh_add_tabs()
        self.status('物品库已更新：%d 条' % len(CAT.items))
        messagebox.showinfo('更新完成', '物品库已重新生成：\n%s\n共 %d 条物品、%d 种宠物。'
                            % (out, len(CAT.items), len(CAT.pets)))

    def open_save(self):
        p = filedialog.askopenfilename(title='选择存档（Save0.dat / Save1.dat …）',
                                       initialdir=self.save_dir if os.path.isdir(self.save_dir) else None,
                                       filetypes=[('存档', '*.dat'), ('全部', '*.*')])
        if not p: return
        self.load_file(p)

    def load_file(self, path):
        DIAG.op('载入存档', os.path.basename(path))
        self.status('正在解析存档…')
        try:
            data = open(path, 'rb').read()
            cat = {'__CITY_ID__': CAT.city_id, '__CITY_NAME__': CAT.city_name,
                   '__PET_CAT__': CAT.pets}
            cat.update({k: 1 for k in CAT.items})
            # 自建武将的定义在存档目录的 NewNPC 里（存档里只有用到的实例），
            # 不读它的话玩家/自建武将的名字会显示成 id（以前还写死成"陈平安"）
            npc = {}
            try:
                npc = sc.parse_new_npc(os.path.join(os.path.dirname(path), 'NewNPC'))
            except Exception:
                pass
            self.save = sc.SaveFile(data, cat, npc)
        except Exception as e:
            DIAG.err('解析存档')
            messagebox.showerror('解析失败', str(e)); self.status('解析失败'); return
        self.save_path = path
        DIAG.log('解析完成：金钱 %s / 武将 %d / 背包 %s / 称号 %s / 城市 %d / 宠物 %s' % (
            self.save.money, len(self.save.heroes),
            (sum(len(g['items']) for g in self.save.bag['groups']) if self.save.bag else '未定位'),
            (len(self.save.titles['ids']) if self.save.titles else '未定位'),
            len(self.save.cities),
            (self.save.pets['count'] if self.save.pets else '未定位')))
        self.bag_edit = None
        self.hero_edits = {}
        self.hero_chars = {}
        self.hero_title_edits = {}    # 武将 id -> [称号 id, ...]（记录内第一条，整段重建）
        self.pet_edits = {}
        self._after_load()

    def _after_load(self):
        s = self.save
        sm = s.summary()
        f = s.faction or {}
        res_lab = '势力科技点' if s.is_ruler else '家族科技点'
        res_lab2 = '势力策略点' if s.is_ruler else '家族策略点'
        _tr_line = ''
        if s.is_ruler and f.get('treasury') is not None:
            _tr_line = ' · 国库金 %s' % format(f['treasury'], ',')
        # 2026-10-23：定位依据不唯一时如实标注，避免把「猜的」当成「读到的」。
        # 参照「英雄立志傳存檔編輯器」v1.03 —— 它无法唯一确认玩家身份时宁可拒绝，
        # 我们这里不拒绝（资源是核心功能），但必须让用户看得出哪个数字不可靠。
        _res_note = ''
        if f.get('tech') is not None and not f.get('confident'):
            _res_note = '（定位依据不唯一，仅供参考，改动前请先在游戏内核对）'
        lines = [
            '文件：%s（%s 字节）' % (os.path.basename(self.save_path), format(len(s.raw), ',')),
            '版本戳 %d · 槽位 %d · 当前地点 %s · 身份 %s' % (s.ver, s.slot, s.place or '—', s.role or '—'),
            '金钱 %s' % format(s.money, ','),
            '%s %s · %s %s%s%s'
            % (res_lab, format(f.get('tech') or 0, ','), res_lab2, format(f.get('strat') or 0, ','),
               _tr_line, _res_note),
            '武将 %d 条 · 背包 %d 件（%d 组）· 称号 %d 条 · 城市 %d 座'
            % (sm['heroes'], sm['bag'], 13 if s.bag else 0, sm['titles'], sm['cities']),
        ]
        self.txt_info.delete('1.0', 'end')
        self.txt_info.insert('1.0', '\n'.join(lines))
        self.lbl_saveinfo.configure(text='已载入：%s' % self.save_path)
        self.status('载入完成')
        self._refresh_hero(); self._refresh_add(); self._refresh_bag()
        self._refresh_title(); self._refresh_city(); self._refresh_pet()

    def revert_all(self):
        if not self.save: return
        if not messagebox.askyesno('确认', '放弃全部改动并重新解析原存档？'):
            return
        self.load_file(self.save_path)

    def backup_save(self):
        if not self.save or not self.save_path:
            messagebox.showwarning('提示', '先读取存档。'); return
        name = os.path.basename(self.save_path)
        p = filedialog.asksaveasfilename(title='备份到…', initialfile=name + '.bak',
                                         defaultextension='.bak')
        if not p: return
        shutil.copyfile(self.save_path, p)
        messagebox.showinfo('备份完成', '已备份到：\n%s' % p)

    def save_new(self):
        if not self.save:
            messagebox.showwarning('提示', '先读取存档。'); return
        # 把界面上的编辑先落到引擎
        self._collect_all()
        try:
            data, ch = self.save.build()
        except Exception as e:
            DIAG.err('生成存档')
            messagebox.showerror('生成失败', str(e)); return
        name = os.path.basename(self.save_path)
        p = filedialog.asksaveasfilename(title='保存新存档', initialfile=name, defaultextension='.dat')
        if not p: return
        # 覆盖已有文件前，先自动备份一份（写坏了还能回头）
        if os.path.exists(p):
            bak = '%s.bak_%s' % (p, time.strftime('%Y%m%d_%H%M%S'))
            try:
                shutil.copyfile(p, bak)
                DIAG.op('覆盖前自动备份', bak)
            except Exception:
                DIAG.err('自动备份')
                bak = None
            tip = ('\n\n已经自动把原文件备份为：\n%s' % bak) if bak else '\n\n自动备份失败，请自己先备份！'
            if not messagebox.askyesno('确认覆盖', '目标文件已存在：\n%s%s\n\n继续覆盖？' % (p, tip)):
                return
        with open(p, 'wb') as f:
            f.write(data)
        DIAG.op('保存新存档', '%s（%d 字节，变更：%s）' % (p, len(data), '；'.join(ch) or '无'))
        # 生成完之后把状态刷新成新写出的文件：否则同一批改动（尤其是「添加性格」这种
        # 会插入字节的操作）再点一次生成就会被写第二遍。
        try:
            self.load_file(p)
        except Exception:
            self.hero_edits = {}
            self.bag_edit = None
        messagebox.showinfo('完成', '已写出：\n%s\n\n变更：\n%s' % (p, '\n'.join(ch) or '（无改动）'))

    def _collect_all(self):
        s = self.save
        if not s: return
        # 背包：只有内容真的变了才重建（f2/f3 必须原样带过去，那是游戏自己的二进制字段）
        if self.bag_edit is not None and s.bag:
            new_groups = [{'off': g['off'], 'n': g['n'], 'end': g['end'],
                           'items': [dict(id=i['id'], qty=i['qty'], f2=i.get('f2', 0),
                                          f3=i.get('f3', 0), off=-1) for i in items]}
                          for g, items in zip(s.bag['groups'], self.bag_edit)]
            if sc.ser_bag(new_groups) != s.bag_sig:
                s.bag['groups'] = new_groups
                s.bag_dirty = True
                DIAG.op('背包将被重写', '%d 组 / %d 件'
                        % (len(new_groups), sum(len(g['items']) for g in new_groups)))
        # 武将（六维 / 资质 / 其他 / 三魂点 / 炼魂 / 熟练 / 特性）
        OFF_OTH = {'moral': sc.O_MORAL, 'compat': sc.O_COMPAT, 'birth': sc.O_BIRTH,
                   'show': sc.O_SHOW, 'death': sc.O_DEATH}
        for idx, e in self.hero_edits.items():
            h = s.heroes[idx]
            so = h.get('six_off')
            for k, v in e.items():
                v = int(v)
                if k.startswith('six') and so is not None:
                    s.edits[so + int(k[3:]) * 4] = ('i32', v)
                elif k.startswith('tal'):
                    s.edits[h['tal_off'] + int(k[3:]) * 4] = ('i32', v)
                elif k.startswith('spt') and so is not None:
                    s.edits[so + sc.O_SOULPT + int(k[3:]) * 4] = ('i32', v)
                elif k.startswith('slv') and so is not None:
                    s.edits[so + sc.O_SOULLV + int(k[3:]) * 4] = ('i32', v)
                elif k.startswith('mst') and so is not None:
                    s.edits[so + sc.O_MASTER + int(k[3:]) * 4] = ('i32', v)
                elif k.startswith('prf') and so is not None:
                    s.edits[so + sc.O_PROF + int(k[3:]) * 4] = ('i32', v)
                elif k in OFF_OTH:
                    s.edits[h['tal_off'] + OFF_OTH[k]] = ('i32', v)
        # 人物性格：整段重建（和称号列表同一套思路 —— 读出来、改、整段换回去）
        for idx, pairs in (getattr(self, 'hero_chars', None) or {}).items():
            if 0 <= idx < len(s.heroes) and pairs:
                s.char_edits[idx] = list(pairs)
        # 武将称号：整段重建（漏了这一步的话，弹窗里改了也会显示"无改动"）
        s.hero_title_edits = dict(getattr(self, 'hero_title_edits', None) or {})
        # 城市特性：整段重建（同一套思路）

        # 宠物（等级上限/月饲养费/价值/攻击/防御/速度/生命）
        if s.pets:
            for k, e in self.pet_edits.items():
                if not (0 <= k < len(s.pets['recs'])): continue
                base = s.pets['recs'][k]['field_off']
                for key, lab, off in self.PET_FIELDS:
                    if key in e:
                        s.edits[base + off] = ('i32', int(e[key]))
        # 称号：同样只在真的改了才重建
        if s.titles is not None and sc.ser_title_list(s.titles['ids']) != s.titles_sig:
            s.titles_dirty = True
            DIAG.op('称号列表将被重写', '%d 条' % len(s.titles['ids']))

    # -------------------------------------------------- 各种添加
    def _ui_add(self):
        f = self.tab_add
        self.add_tabs_frame = ttk.Frame(f); self.add_tabs_frame.pack(fill='x', padx=8, pady=(8, 4))
        self.add_tab_btns = []
        self.add_tab = 0
        for i, (nm, _) in enumerate(ADD_TABS):
            b = ttk.Button(self.add_tabs_frame, text=nm, width=10,
                           command=lambda i=i: self.set_add_tab(i))
            b.pack(side='left', padx=2)
            self.add_tab_btns.append(b)

        body = ttk.Frame(f); body.pack(fill='both', expand=True, padx=8, pady=4)
        left = ttk.Frame(body); left.pack(side='left', fill='both', expand=True)
        holder, self.tv_add = self.make_table(
            left, [('name', '名称', 300), ('id', 'ID', 150), ('kind', '分类', 100),
                   ('level', '等级', 70), ('price', '价格', 100), ('grp', '归到哪一组', 200)], height=20)
        holder.pack(fill='both', expand=True)

        right = ttk.Frame(body, width=280); right.pack(side='right', fill='y', padx=(10, 0))
        ttk.Label(right, text='名称 / ID 关键词').pack(anchor='w')
        r1 = ttk.Frame(right); r1.pack(fill='x', pady=3)
        self.var_q = tk.StringVar()
        e = ttk.Entry(r1, textvariable=self.var_q); e.pack(side='left', fill='x', expand=True)
        e.bind('<Return>', lambda ev: self.refresh_add_list())
        ttk.Button(r1, text='查找', width=6, command=self.refresh_add_list).pack(side='left', padx=4)

        ttk.Label(right, text='等级（不限 / 不限）').pack(anchor='w', pady=(10, 0))
        r2 = ttk.Frame(right); r2.pack(fill='x', pady=3)
        self.var_lvlo, self.var_lvhi = tk.StringVar(), tk.StringVar()
        self.cb_lvlo = ttk.Combobox(r2, textvariable=self.var_lvlo, width=10, state='readonly')
        self.cb_lvhi = ttk.Combobox(r2, textvariable=self.var_lvhi, width=10, state='readonly')
        self.cb_lvlo.pack(side='left'); self.cb_lvhi.pack(side='left', padx=4)

        ttk.Label(right, text='价值（下限 / 上限）').pack(anchor='w', pady=(10, 0))
        r3 = ttk.Frame(right); r3.pack(fill='x', pady=3)
        self.var_vllo, self.var_vlhi = tk.StringVar(), tk.StringVar()
        for var in (self.var_vllo, self.var_vlhi):
            ttk.Entry(r3, textvariable=var, width=11).pack(side='left', padx=2)

        ttk.Label(right, text='数量（自动按类型归组）').pack(anchor='w', pady=(10, 0))
        r4 = ttk.Frame(right); r4.pack(fill='x', pady=3)
        self.var_qty = tk.StringVar(value='1')
        ttk.Entry(r4, textvariable=self.var_qty, width=8).pack(side='left')
        ttk.Button(r4, text='添加', width=12, command=self.do_add).pack(side='left', padx=8)

        r5 = ttk.Frame(right); r5.pack(fill='x', pady=(12, 0))
        ttk.Button(r5, text='全选', width=8, command=lambda: self.tv_add.selection_set(
            self.tv_add.get_children())).pack(side='left')
        ttk.Button(r5, text='清空选择', width=10,
                   command=lambda: self.tv_add.selection_remove(self.tv_add.get_children())).pack(side='left', padx=6)
        ttk.Button(right, text='清除（筛选 + 选择 + 数量）', command=self.clear_add).pack(fill='x', pady=(10, 0))
        self.lbl_add = ttk.Label(right, text='', foreground='#666', wraplength=270, justify='left')
        self.lbl_add.pack(anchor='w', pady=(8, 0))

    def set_add_tab(self, i):
        self.add_tab = i
        for k, b in enumerate(self.add_tab_btns):
            b.configure(style='TButton')
        self.refresh_add_list()

    def _add_rows(self):
        cats = ADD_TABS[self.add_tab][1]
        q = self.var_q.get().strip().lower()
        lvlo = self._num(self.var_lvlo.get(), int)
        lvhi = self._num(self.var_lvhi.get(), int)
        vllo = self._num(self.var_vllo.get(), float)
        vlhi = self._num(self.var_vlhi.get(), float)
        out = []
        drop_zero = ADD_TABS[self.add_tab][0] in ZERO_PRICE_TABS
        for iid, v in CAT.items.items():
            if not sc.ID_RE.match(iid): continue
            if iid.startswith('JZ'): continue              # 建筑永远不进背包
            if v[1] not in cats: continue
            if drop_zero:
                pr = CAT.price(iid)
                if pr is None or pr <= 0: continue
            if q and q not in iid.lower() and q not in str(v[0]).lower(): continue
            lv = CAT.level(iid)
            if lvlo is not None and (lv is None or lv < lvlo): continue
            if lvhi is not None and (lv is None or lv > lvhi): continue
            if vllo is not None or vlhi is not None:
                pr = CAT.price(iid)
                if pr is None: continue
                if vllo is not None and pr < vllo: continue
                if vlhi is not None and pr > vlhi: continue
            out.append(iid)
        out.sort(key=lambda i: CAT.name(i))
        return out

    @staticmethod
    def _num(s, typ):
        s = (s or '').strip()
        if s in ('', '不限'):
            return None
        m = re.search(r'-?\d+(?:\.\d+)?', s)      # 下拉里是「≥ 3」「≤ 2」这种，取其中的数字
        if not m:
            return None
        try:
            return typ(float(m.group(0)))
        except Exception:
            return None

    def _refresh_add_tabs(self):
        lvs = sorted({CAT.level(i) for i in CAT.items if CAT.level(i) is not None})
        self.cb_lvlo['values'] = ['不限'] + ['≥ %d' % n for n in lvs]
        self.cb_lvhi['values'] = ['不限'] + ['≤ %d' % n for n in lvs]
        for var in (self.var_lvlo, self.var_lvhi):
            var.set('不限')

    def _refresh_add(self):
        self._refresh_add_tabs()
        self.refresh_add_list()

    def refresh_add_list(self):
        rows = self._add_rows()
        tv = self.tv_add
        tv.delete(*tv.get_children())
        self.add_rows = rows[:2000]
        for iid in self.add_rows:
            lv, pr = CAT.level(iid), CAT.price(iid)
            g = CAT.grp(iid)
            tv.insert('', 'end', iid=iid, values=(
                CAT.name(iid), iid, CAT.kind(iid),
                lv if lv is not None else '—',
                format(pr, ',') if pr is not None else '—',
                '组 %d · %s' % (g, CAT.group_label(g))))
        self.lbl_add.configure(text='本页 %d 条（按住 Ctrl / Shift 可多选）%s'
                               % (len(self.add_rows), '' if self.save else ' · 未载入存档'))

    def clear_add(self):
        self.var_q.set('')
        self.var_vllo.set(''); self.var_vlhi.set('')
        for var in (self.var_lvlo, self.var_lvhi):
            var.set('不限')
        self.var_qty.set('1')
        self.tv_add.selection_remove(self.tv_add.get_children())
        self.refresh_add_list()

    def do_add(self):
        if not self.save:
            messagebox.showwarning('提示', '先读取存档。'); return
        sel = self.tv_add.selection()
        if not sel:
            messagebox.showwarning('提示', '先在左边列表里选物品（按住 Ctrl / Shift 可多选）。'); return
        try:
            qty = max(1, int(float(self.var_qty.get() or '1')))
        except Exception:
            qty = 1
        if self.bag_edit is None:
            self.bag_edit = [[dict(id=it['id'], qty=it['qty'], f2=it['f2'], f3=it['f3'])
                             for it in g['items']] for g in self.save.bag['groups']]
        n = 0
        for iid in sel:
            gi = CAT.grp(iid)
            if not (0 <= gi < len(self.bag_edit)): gi = 12
            hit = next((x for x in self.bag_edit[gi] if x['id'] == iid), None)
            if hit:
                hit['qty'] += qty
            else:
                self.bag_edit[gi].append({'id': iid, 'qty': qty})
            n += 1
        self._refresh_bag()
        DIAG.op('添加物品', '%d 种 × %d 件' % (n, qty))
        self.status('已添加 %d 种物品（每种 %d 件）' % (n, qty))
        messagebox.showinfo('已加入', '加入 %d 种物品（每种 %d 件）。\n去「常用功能 → 生成并保存新存档」写出。' % (n, qty))

    # -------------------------------------------------- 背包管理
    def _ui_bag(self):
        f = self.tab_bag
        bar = ttk.Frame(f); bar.pack(fill='x', padx=8, pady=(8, 4))
        ttk.Label(bar, text='筛选：').pack(side='left')
        self.var_bagq = tk.StringVar()
        e = ttk.Entry(bar, textvariable=self.var_bagq, width=20)
        e.pack(side='left'); e.bind('<Return>', lambda ev: self.refresh_bag_list())
        self.var_bagkind = tk.StringVar(value='全部')
        self.cb_bagkind = ttk.Combobox(bar, textvariable=self.var_bagkind, state='readonly', width=14)
        self.cb_bagkind.pack(side='left', padx=6)
        self.cb_bagkind.bind('<<ComboboxSelected>>', lambda ev: self.refresh_bag_list())
        self.var_baggrp = tk.StringVar(value='全部')
        self.cb_baggrp = ttk.Combobox(bar, textvariable=self.var_baggrp, state='readonly', width=24)
        self.cb_baggrp.pack(side='left')
        self.cb_baggrp.bind('<<ComboboxSelected>>', lambda ev: self.refresh_bag_list())
        ttk.Button(bar, text='查找', width=6, command=self.refresh_bag_list).pack(side='left', padx=4)
        ttk.Button(bar, text='修改', command=self.bag_set_qty).pack(side='left', padx=6)
        ttk.Button(bar, text='删除所选', command=self.bag_del).pack(side='left')
        ttk.Button(bar, text='还原背包', command=self.bag_revert).pack(side='left', padx=6)
        self.lbl_bag = ttk.Label(bar, text='', foreground='#666'); self.lbl_bag.pack(side='left', padx=8)

        holder, self.tv_bag = self.make_table(f, [
            ('grp', '组', 58), ('name', '名称', 250), ('id', 'ID', 160), ('kind', '分类', 110),
            ('qty', '数量', 80), ('soul', '魂占用', 80), ('price', '价值', 100)], height=22)
        holder.pack(fill='both', expand=True, padx=8, pady=(0, 8))

    def _refresh_bag(self):
        vals = ['全部'] + ['组 %d · %s' % (i, CAT.group_label(i)) for i in range(13)]
        self.cb_baggrp['values'] = vals
        if self.var_baggrp.get() not in vals:
            self.var_baggrp.set('全部')
        kinds = sorted({v[1] for v in CAT.items.values() if len(v) > 1}) if CAT.items else []
        self.cb_bagkind['values'] = ['全部'] + kinds
        self.refresh_bag_list()

    def _bag_rows(self):
        """返回 [(gi, idx, item), ...]，默认全背包。"""
        if not (self.save and self.save.bag):
            return []
        if self.bag_edit is None:
            self.bag_edit = [[dict(id=it['id'], qty=it['qty'], f2=it['f2'], f3=it['f3'])
                             for it in g['items']] for g in self.save.bag['groups']]
        q = (self.var_bagq.get() or '').strip().lower()
        gsel = self.var_baggrp.get()
        gwant = None
        m = re.match(r'组 (\d+)', gsel or '')
        if m: gwant = int(m.group(1))
        ksel = self.var_bagkind.get()
        out = []
        for gi, items in enumerate(self.bag_edit):
            if gwant is not None and gi != gwant: continue
            for idx, it in enumerate(items):
                iid = it['id']
                if ksel and ksel != '全部' and CAT.kind(iid) != ksel: continue
                if q and q not in iid.lower() and q not in CAT.name(iid).lower(): continue
                out.append((gi, idx, it))
        return out

    def refresh_bag_list(self):
        tv = self.tv_bag
        tv.delete(*tv.get_children())
        if not (self.save and self.save.bag):
            self.lbl_bag.configure(text='背包未定位'); return
        rows = self._bag_rows()
        for gi, idx, it in rows:
            iid = it['id']
            sp, pr = CAT.soul(iid), CAT.price(iid)
            tv.insert('', 'end', iid='g%d#%d' % (gi, idx), values=(
                gi, CAT.name(iid), iid, CAT.kind(iid), it['qty'],
                sp if sp is not None else '—', format(pr, ',') if pr is not None else '—'))
        total = sum(len(x) for x in self.bag_edit)
        self.lbl_bag.configure(text='显示 %d / 全包 %d 件' % (len(rows), total))

    def bag_set_qty(self):
        sel = self.tv_bag.selection()
        if not sel: return
        from tkinter import simpledialog
        v = simpledialog.askinteger('改数量', '新数量：', initialvalue=1, minvalue=0, maxvalue=999999)
        if v is None: return
        for iid in sel:
            gi, idx = self._parse_bag_iid(iid)
            if gi is None: continue
            self.bag_edit[gi][idx]['qty'] = v
        self.refresh_bag_list()

    @staticmethod
    def _parse_bag_iid(iid):
        m = re.match(r'g(\d+)#(\d+)$', iid or '')
        return (int(m.group(1)), int(m.group(2))) if m else (None, None)

    def bag_del(self):
        sel = self.tv_bag.selection()
        if not sel:
            messagebox.showwarning('提示', '先选要删的物品。'); return
        pairs = [self._parse_bag_iid(x) for x in sel]
        pairs = [(g, i) for g, i in pairs if g is not None]
        if not pairs: return
        if not messagebox.askyesno('确认', '删除选中的 %d 件物品？' % len(pairs)): return
        for gi, idx in sorted(pairs, key=lambda t: (t[0], -t[1])):
            if 0 <= idx < len(self.bag_edit[gi]):
                del self.bag_edit[gi][idx]
        self.refresh_bag_list()

    def bag_revert(self):
        self.bag_edit = None
        self.refresh_bag_list()
        self.status('背包改动已还原')

    # -------------------------------------------------- 称号与资源
    def _ui_title(self):
        f = self.tab_title
        self.res_box = ttk.LabelFrame(f, text='资源（可直接改，保存时写入）', padding=10)
        self.res_box.pack(fill='x', padx=8, pady=8)
        # 布局：第一行 = 金钱 / 灵蕴（玩家个人资源）
        #       第二行 = 科技点 / 策略点 / 国库金（前两项是势力/家族资源，国库金只有君主档才有）
        self.res_vars = {}
        self.res_labels = {}
        layout = [('money', '金钱', 'money_off', 0, 0),
                  ('lingyun', '灵蕴', 'lingyun_off', 0, 2),
                  ('tech', '科技点', 'tech_off', 1, 0),
                  ('strat', '策略点', 'strat_off', 1, 2),
                  ('treasury', '国库金', 'treasury_off', 2, 0)]
        for key, lab, off_key, r, c in layout:
            lb = ttk.Label(self.res_box, text=lab, width=8)
            lb.grid(row=r, column=c, sticky='w', pady=3)
            v = tk.StringVar()
            en = ttk.Entry(self.res_box, textvariable=v, width=16)
            en.grid(row=r, column=c + 1, sticky='w', padx=(0, 20))
            self.res_vars[key] = v
            self.res_labels[key] = (lb, en)
        ttk.Button(self.res_box, text='修改', command=self.apply_res).grid(row=3, column=0, pady=(8, 0), sticky='w')
        self.lbl_res_note = ttk.Label(self.res_box, text='', foreground='#a00', justify='left')
        self.lbl_res_note.grid(row=3, column=1, columnspan=3, sticky='w', pady=(8, 0))

        # 武将称号：列表里点武将 → 弹出窗口改他的称号（增删改都支持）
        box2 = ttk.LabelFrame(f, text='武将称号（双击一行武将，弹出窗口修改他的称号）', padding=10)
        box2.pack(fill='both', expand=True, padx=8, pady=8)
        bar = ttk.Frame(box2); bar.pack(fill='x', pady=(0, 6))
        ttk.Label(bar, text='搜索武将').pack(side='left')
        self.var_htq = tk.StringVar()
        eh = ttk.Entry(bar, textvariable=self.var_htq, width=18); eh.pack(side='left', padx=4)
        eh.bind('<Return>', lambda ev: self._refresh_htitles())
        ttk.Button(bar, text='筛选', command=self._refresh_htitles).pack(side='left')
        self.lbl_htitle = ttk.Label(bar, text='', foreground='#666'); self.lbl_htitle.pack(side='left', padx=10)
        holder, self.tv_htitle = self.make_table(
            box2, [('name', '武将', 130), ('id', 'ID', 100), ('cnt', '称号数', 70),
                   ('titles', '现有称号', 560)], height=15)
        holder.pack(fill='both', expand=True)
        self.tv_htitle.bind('<Double-1>', lambda ev: self.hero_title_open())
        tip = ttk.Label(box2, text='提示：双击武将打开编辑窗口；改了之后点「生成并保存新存档」写出。',
                        foreground='#666')
        tip.pack(anchor='w', pady=(6, 0))

    # -------------------------------------------------- 武将称号：列表 + 弹窗编辑
    def _refresh_htitles(self):
        tv = getattr(self, 'tv_htitle', None)
        if not tv:
            return
        tv.delete(*tv.get_children())
        if not self.save:
            return
        q = (self.var_htq.get() or '').strip()
        n = 0
        for h in self.save.heroes:
            nm = h.get('name') or h['id']
            if q and (q not in nm) and (q != h['id']):
                continue
            info = self.save.hero_titles.get(h['id'])
            ids = list((self.hero_title_edits or {}).get(h['id'], info['ids'] if info else []))
            short = ' / '.join(CAT.name('HTC' + x) for x in ids[:4])
            if len(ids) > 4:
                short += ' …'
            tv.insert('', 'end', iid=h['id'],
                      values=(nm, h['id'], len(ids), short))
            n += 1
        if getattr(self, 'lbl_htitle', None) is not None:
            self.lbl_htitle.configure(text='共 %d 位武将（按搜索条件）' % n)

    def hero_title_open(self):
        if not self.save:
            return
        sel = self.tv_htitle.selection()
        if not sel:
            messagebox.showwarning('提示', '先双击/选中一位武将。'); return
        self._hero_title_dialog(sel[0])

    def _hero_title_dialog(self, hid, modal=True):
        s = self.save
        hero = next((h for h in s.heroes if h['id'] == hid), None)
        if not hero:
            return
        info = s.hero_titles.get(hid)
        base = list(info['ids']) if info else []
        cur = (self.hero_title_edits or {}).get(hid)
        state = {'list': list(cur if cur is not None else base), 'base': base, 'hid': hid}

        dlg = tk.Toplevel(self.root)
        dlg.title('武将称号 · %s' % (hero.get('name') or hid))
        dlg.transient(self.root)
        dlg.geometry('760x520')
        pg = ttk.Frame(dlg, padding=10); pg.pack(fill='both', expand=True)

        top = ttk.Frame(pg); top.pack(fill='x', pady=(0, 8))
        ttk.Label(top, text='%s' % (hero.get('name') or hid),
                  font=('Microsoft YaHei UI', 11, 'bold')).pack(side='left')
        lbl = ttk.Label(top, text='', foreground='#666'); lbl.pack(side='left', padx=10)

        body = ttk.Frame(pg); body.pack(fill='both', expand=True)
        lf = ttk.Frame(body); lf.pack(side='left', fill='both', expand=True)
        th, tv = self.make_table(lf, [('name', '称号', 260), ('id', 'ID', 150)], height=14)
        th.pack(fill='both', expand=True)
        tv.bind('<Double-1>', lambda ev: do_del())

        rf = ttk.Frame(body); rf.pack(side='right', fill='y', padx=(10, 0))
        ttk.Label(rf, text='搜索称号').pack(anchor='w')
        vq = tk.StringVar()
        e = ttk.Entry(rf, textvariable=vq, width=22); e.pack(fill='x', pady=3)
        cb = ttk.Combobox(rf, state='readonly', width=24); cb.pack(fill='x', pady=3)

        def refresh():
            tv.delete(*tv.get_children())
            for k, x in enumerate(state['list']):
                tv.insert('', 'end', iid=str(k), values=(CAT.name('HTC' + x), x))
            lbl.configure(text='共 %d 个称号' % len(state['list']))

        def pick(*_):
            q = (vq.get() or '').strip()
            seen, names = set(), []
            for k in CAT.items:
                if not k.startswith('HTC'):
                    continue
                nm2 = CAT.name(k)
                if nm2 in seen:
                    continue
                if q and (q not in nm2) and (q != k[3:]):
                    continue
                seen.add(nm2)
                names.append(nm2)
            names.sort()
            cb['values'] = names[:500]
            if names:
                cb.current(0)

        def do_add():
            t = (cb.get() or '').strip()
            if not t:
                messagebox.showwarning('提示', '先搜索并选一个称号。', parent=dlg); return
            tid = next((k[3:] for k in CAT.items
                        if k.startswith('HTC') and CAT.name(k) == t), None)
            if not tid:
                messagebox.showwarning('提示', '找不到这个称号。', parent=dlg); return
            if tid in state['list']:
                messagebox.showwarning('已经有了', '这个称号已经在列表里。', parent=dlg); return
            state['list'].append(tid)
            refresh()

        def do_del():
            sel = tv.selection()
            if not sel:
                messagebox.showwarning('提示', '先选中要删的称号（双击也能删）。', parent=dlg); return
            for k in sorted((int(x) for x in sel), reverse=True):
                if 0 <= k < len(state['list']):
                    del state['list'][k]
            refresh()

        def do_revert():
            state['list'] = list(state['base'])
            refresh()

        e.bind('<Return>', pick)
        ttk.Button(rf, text='查找', command=pick).pack(fill='x')
        ttk.Button(rf, text='加入称号', command=do_add).pack(fill='x', pady=(6, 2))
        ttk.Button(rf, text='删除选中', command=do_del).pack(fill='x', pady=2)
        ttk.Button(rf, text='恢复原始', command=do_revert).pack(fill='x', pady=(8, 0))

        foot = ttk.Frame(pg); foot.pack(fill='x', pady=(8, 0))

        def ok():
            if state['list'] != state['base']:
                self.hero_title_edits[hid] = list(state['list'])
            else:
                self.hero_title_edits.pop(hid, None)
            self._refresh_htitles()
            dlg.destroy()

        ttk.Button(foot, text='取消', command=dlg.destroy).pack(side='right', padx=(4, 0))
        ttk.Button(foot, text='确定', command=ok).pack(side='right')
        if not base:
            ttk.Label(foot, text='这位武将原本没有称号记录（可加入，保存时会新建）。',
                      foreground='#9a5c08').pack(side='left')

        refresh(); pick()
        self._htitle_dlg = dlg
        if modal:
            try:
                dlg.grab_set()
            except Exception:
                pass

    def _refresh_title(self):
        s = self.save
        ruler = bool(s and s.is_ruler)
        self.res_box.configure(text='势力资源（可直接改，保存时写入）' if ruler
                               else '家族资源（可直接改，保存时写入）')
        for k in ('tech', 'strat'):
            if k in self.res_labels:
                self.res_labels[k][0].configure(
                    text={'tech': '科技点', 'strat': '策略点'}[k]
                    if ruler else
                    {'tech': '家族科技点', 'strat': '家族策略点'}[k])
        if s:
            f = s.faction or {}
            self.res_vars['money'].set(str(s.money))
            # 灵蕴 = 玩家个人资源（独立于势力/家族块）
            ling = getattr(s, 'lingyun', None)
            self.res_vars['lingyun'].set('' if ling is None else str(ling))
            self.res_labels['lingyun'][1].configure(
                state='normal' if getattr(s, 'lingyun_off', 0) else 'disabled')
            self.res_vars['tech'].set('' if f.get('tech') is None else str(f.get('tech')))
            self.res_vars['strat'].set('' if f.get('strat') in (None, '') else str(f.get('strat')))
            # 国库金：只有君主档 + 形态A 块才读得出来，读不到就置灰（绝不显示垃圾值）
            _tr = f.get('treasury')
            if ruler and _tr is not None and f.get('treasury_off'):
                self.res_vars['treasury'].set(str(_tr))
                self.res_labels['treasury'][0].configure(state='normal')
                self.res_labels['treasury'][1].configure(state='normal')
            else:
                self.res_vars['treasury'].set('')
                self.res_labels['treasury'][0].configure(state='disabled')
                self.res_labels['treasury'][1].configure(state='disabled')
            _notes = []
            if not ruler:
                _notes.append('当前身份：%s（未自立势力）—— 只能改家族科技点 / 家族策略点。'
                              % (s.role or '在野'))
            elif f.get('tech') is not None and not f.get('confident'):
                _notes.append('注意：%s定位依据不唯一，以上数值仅供参考，改动前请先在游戏内核对。'
                              % ('势力资源' if ruler else '家族资源'))
            self.lbl_res_note.configure(text='\n'.join(_notes))
        else:
            for v in self.res_vars.values(): v.set('')
            self.lbl_res_note.configure(text='')
        try:
            self._refresh_htitles()      # 武将称号列表
        except Exception:
            pass

    def apply_res(self):
        s = self.save
        if not s:
            messagebox.showwarning('提示', '先读取存档。'); return
        def setv(off, val, typ='i32'):
            if off and off > 0:
                s.edits[off] = (typ, val)
        try:
            setv(s.money_off, int(self.res_vars['money'].get() or 0))
            # 金钱有两个副本，一起写
            for c in s.money_copies[1:]:
                setv(c, int(self.res_vars['money'].get() or 0))
            # 灵蕴（玩家个人资源）
            ling_txt = self.res_vars['lingyun'].get().strip()
            if ling_txt != '' and getattr(s, 'lingyun_off', 0):
                setv(s.lingyun_off, int(float(ling_txt)))
            f = s.faction or {}
            for key in ('tech', 'strat'):
                txt = self.res_vars[key].get().strip()
                if txt == '' or not f.get(key + '_off'):
                    continue
                setv(f[key + '_off'], int(float(txt)))
            # 国库金（只有君主档 + 形态A 块才有 treasury_off）
            tr_txt = self.res_vars['treasury'].get().strip()
            if tr_txt != '' and f.get('treasury_off'):
                setv(f['treasury_off'], int(float(tr_txt)))
            self.status('资源改动已记下，保存时写入')
            messagebox.showinfo('已记下', '资源改动已记下，点「生成并保存新存档」写出。')
        except Exception as e:
            messagebox.showerror('数值不合法', str(e))

    # -------------------------------------------------- 城市属性
    def _ui_city(self):
        f = self.tab_city
        bar = ttk.Frame(f); bar.pack(fill='x', padx=8, pady=(8, 4))
        ttk.Label(bar, text='已选城市：').pack(side='left')
        self.lbl_city = ttk.Label(bar, text='（在下面列表里选一座城）', foreground='#2f6fed')
        self.lbl_city.pack(side='left')
        ttk.Button(bar, text='修改', command=self.apply_city).pack(side='left', padx=12)
        self.lbl_cityn = ttk.Label(bar, text='', foreground='#666'); self.lbl_cityn.pack(side='left', padx=8)

        mid = ttk.Frame(f); mid.pack(fill='x', padx=8, pady=6)
        box = ttk.LabelFrame(mid, text='城市数值（改完点「修改」）', padding=12)
        box.pack(side='left', fill='y')
        self.city_vars = {}
        for k, lab in [('money', '资金'), ('food', '军粮'), ('pop', '人口'), ('security', '治安')]:
            idx = ['money', 'food', 'pop', 'security'].index(k)
            ttk.Label(box, text=lab, width=6).grid(row=idx // 2, column=(idx % 2) * 2, sticky='w', pady=3)
            v = tk.StringVar()
            ttk.Entry(box, textvariable=v, width=18).grid(row=idx // 2, column=(idx % 2) * 2 + 1,
                                                          sticky='w', padx=(0, 24))
            self.city_vars[k] = v

        holder, self.tv_city = self.make_table(
            f, [('name', '城市', 140), ('cid', 'ID', 90), ('money', '资金', 130), ('food', '军粮', 130),
                ('pop', '人口', 110), ('sec', '治安', 90), ('n', '武将', 70)], height=18)
        holder.pack(fill='both', expand=True, padx=8, pady=(0, 8))
        self.tv_city.bind('<<TreeviewSelect>>', lambda e: self.refresh_city_fields())

    def _refresh_city(self):
        tv = self.tv_city
        tv.delete(*tv.get_children())
        if not (self.save and self.save.cities):
            self.lbl_cityn.configure(text='城市未定位'); return
        rows = sorted(self.save.cities.items(), key=lambda kv: -kv[1]['money'])
        for cid, c in rows:
            tv.insert('', 'end', iid=cid, values=(
                CAT.city_name.get(cid, cid), cid, format(c['money'], ','), format(c['food'], ','),
                c['pop'], '%.1f' % c['security'], c['N']))
        self.lbl_cityn.configure(text='共 %d 座城（按资金排序）' % len(rows))
        pick = None
        if self.save.place:
            for cid in self.save.cities:
                if CAT.city_name.get(cid) == self.save.place:
                    pick = cid; break
        if not pick and rows:
            pick = rows[0][0]
        if pick:
            tv.selection_set(pick)
            tv.see(pick)
            self.refresh_city_fields()

    def _cur_city(self):
        if not self.save: return None
        sel = self.tv_city.selection()
        return self.save.cities.get(sel[0]) if sel else None

    def refresh_city_fields(self):
        c = self._cur_city()
        if not c: return
        self.city_vars['money'].set(str(c['money']))
        self.city_vars['food'].set(str(c['food']))
        self.city_vars['pop'].set(str(c['pop']))
        self.city_vars['security'].set('%.1f' % c['security'])
        self.lbl_city.configure(text='%s · %s' % (CAT.city_name.get(c['cid'], c['cid']), c['cid']))
        self.lbl_cityn.configure(text='@%#x · %d 位武将' % (c['sec'], c['N']))

    def apply_city(self):
        c = self._cur_city()
        if not c or not self.save:
            messagebox.showwarning('提示', '先读取存档并选城市。'); return
        try:
            self.save.edits[c['sec'] - 12] = ('i32', int(self.city_vars['money'].get()))
            self.save.edits[c['sec'] - 8] = ('i32', int(self.city_vars['food'].get()))
            self.save.edits[c['sec'] - 4] = ('i32', int(self.city_vars['pop'].get()))
            self.save.edits[c['sec']] = ('f32', float(self.city_vars['security'].get()))
        except Exception as e:
            messagebox.showerror('数值不合法', str(e)); return
        self.status('城市改动已记下')
        messagebox.showinfo('已记下', '城市改动已记下，点「生成并保存新存档」写出。')

    # -------------------------------------------------- 宠物修改
    PET_FIELDS = [('lv_limit', '等级上限', 0x00), ('month_cost', '月饲养费', 0x04),
                  ('value', '价值', 0x08), ('atk', '攻击力', 0x10), ('dfn', '防御力', 0x14),
                  ('spd', '速度', 0x18), ('hp', '生命值', 0x1c)]

    def _ui_pet(self):
        f = self.tab_pet
        bar = ttk.Frame(f); bar.pack(fill='x', padx=8, pady=(8, 4))
        ttk.Label(bar, text='搜索宠物：').pack(side='left')
        self.var_petq = tk.StringVar()
        e = ttk.Entry(bar, textvariable=self.var_petq, width=20)
        e.pack(side='left'); e.bind('<Return>', lambda ev: self.refresh_pet_list())
        ttk.Button(bar, text='查找', command=self.refresh_pet_list).pack(side='left', padx=6)
        ttk.Button(bar, text='修改', command=self.pet_open_selected).pack(side='left', padx=6)
        self.lbl_pet = ttk.Label(bar, text='', foreground='#666'); self.lbl_pet.pack(side='left', padx=10)
        ttk.Label(bar, text='提示：双击某一行即可改数值', foreground='#2f6fed').pack(side='left')

        holder, self.tv_pet = self.make_table(
            f, [('name', '名称', 150), ('id', 'ID', 140), ('fam', '族', 80),
                ('lv', '等级上限', 90), ('cost', '月饲养费', 90), ('value', '价值', 100),
                ('atk', '攻击力', 90), ('dfn', '防御力', 90), ('spd', '速度', 80), ('hp', '生命值', 110)],
            height=22, tips={'name': lambda v: '宠物：%s\n族：%s' % (v[0], v[2])})
        holder.pack(fill='both', expand=True, padx=8, pady=(0, 8))
        self.tv_pet.bind('<Double-1>', lambda ev: self.pet_open_selected())

        ab = ttk.LabelFrame(f, text='添加宠物（选品种 → 加入待添加 → 回「常用功能」保存新存档时写入）', padding=8)
        ab.pack(fill='x', padx=8, pady=(0, 8))
        r1 = ttk.Frame(ab); r1.pack(fill='x')
        ttk.Label(r1, text='品种：').pack(side='left')
        self.var_pet_new = tk.StringVar()
        self.cb_pet_new = ttk.Combobox(r1, textvariable=self.var_pet_new, width=30)
        self.cb_pet_new.pack(side='left')
        ttk.Label(r1, text='  模板：').pack(side='left')
        self.var_pet_tmpl = tk.StringVar()
        self.cb_pet_tmpl = ttk.Combobox(r1, textvariable=self.var_pet_tmpl, state='readonly', width=26)
        self.cb_pet_tmpl.pack(side='left')
        ttk.Button(r1, text='加入待添加', command=self.pet_queue_add).pack(side='left', padx=8)
        ttk.Button(r1, text='清空待添加', command=self.pet_queue_clear).pack(side='left')
        self.lbl_pet_add = ttk.Label(r1, text='待添加 0 只', foreground='#666')
        self.lbl_pet_add.pack(side='left', padx=10)
        ttk.Label(ab, text='说明：宠物按「模板宠物」的记录结构生成，品种数据取自物品库；'
                           '保存时会把新宠物追加到列表末尾，编号自动 +1。',
                  foreground='#666', wraplength=1000, justify='left').pack(anchor='w', pady=(6, 0))

    def pet_queue_add(self):
        if not (self.save and self.save.pets):
            messagebox.showwarning('提示', '先读取有宠物的存档。'); return
        sel = self.cb_pet_new.get().strip()
        m = re.search(r'（(P[0-9A-Za-z_]+)）\s*$', sel)
        tid = m.group(1) if m else sel
        if not tid or tid not in CAT.pets:
            messagebox.showwarning('提示', '先在下拉里选一个宠物品种（输几个字能筛）。'); return
        ti = 0
        ts = self.cb_pet_tmpl.get()
        m2 = re.match(r'#(\d+)\s', ts or '')
        if m2: ti = int(m2.group(1))
        self.save.pet_adds.append({'tgt': tid, 'tmpl': ti})
        self._refresh_pet()
        DIAG.op('待添加宠物', '%s（品种 %s，模板 #%d）' % ((CAT.pets[tid] or [tid])[0], tid, ti))
        self.status('已加入待添加：%s（保存新存档时写入）' % (CAT.pets[tid] or [tid])[0])

    def pet_queue_clear(self):
        if self.save:
            self.save.pet_adds = []
        self._refresh_pet()
        self.status('已清空待添加宠物')

    def _refresh_pet(self):
        tv = self.tv_pet
        tv.delete(*tv.get_children())
        if not (self.save and self.save.pets):
            self.lbl_pet.configure(text='这份存档里没找到宠物列表'); return
        q = (self.var_petq.get() or '').strip().lower()
        n = 0
        for k, p in enumerate(self.save.pets['recs']):
            if q and q not in p['id'].lower() and q not in p['name'].lower(): continue
            e = self.pet_edits.get(k, {})
            g = lambda key: e.get(key, p[key])
            tv.insert('', 'end', iid=str(k), values=(
                p['name'], p['id'], p['fam'], g('lv_limit'), g('month_cost'), g('value'),
                g('atk'), g('dfn'), g('spd'), g('hp')))
            n += 1
        self.lbl_pet.configure(text='共 %d 只（显示 %d）' % (self.save.pets['count'], n))
        self._fill_pet_add_widgets()

    def _fill_pet_add_widgets(self):
        if not hasattr(self, 'cb_pet_new'): return
        if not self.cb_pet_new['values']:
            rows = []
            for pid, v in CAT.pets.items():
                rows.append('%s（%s）%s' % (v[0] if v else pid, pid, '  [MOD]' if len(v) > 13 and v[13] else ''))
            rows.sort()
            self.cb_pet_new['values'] = rows
        trows = []
        if self.save and self.save.pets:
            for k, p in enumerate(self.save.pets['recs']):
                trows.append('#%d %s（%s）' % (k, p['name'], p['id']))
        self.cb_pet_tmpl['values'] = trows
        if trows and not self.cb_pet_tmpl.get():
            self.cb_pet_tmpl.current(0)
        n = len(self.save.pet_adds) if self.save else 0
        self.lbl_pet_add.configure(text='待添加 %d 只%s' % (n, ('：' + '、'.join(
            (CAT.pets.get(a['tgt']) or [a['tgt']])[0] for a in self.save.pet_adds)) if n else ''))

    def refresh_pet_list(self):
        self._refresh_pet()

    def pet_open_selected(self):
        sel = self.tv_pet.selection()
        if not sel:
            messagebox.showwarning('提示', '先在列表里选一只宠物。'); return
        self.pet_edit_dialog(int(sel[0]))

    def pet_edit_dialog(self, k, modal=True):
        p = self.save.pets['recs'][k]
        e = self.pet_edits.get(k, {})
        win = tk.Toplevel(self.root)
        win.title('宠物修改 · %s（%s）' % (p['name'], p['id']))
        win.geometry('560x330')
        try:
            win.transient(self.root)
        except Exception:
            pass
        ttk.Label(win, text='%s · %s · 族 %s' % (p['name'], p['id'], p['fam']),
                  font=('Microsoft YaHei', 12, 'bold')).pack(anchor='w', padx=14, pady=(12, 6))
        body = ttk.LabelFrame(win, text='数值（改完点「修改」）', padding=10)
        body.pack(fill='x', padx=14, pady=6)
        V = {}
        for i, (key, lab, off) in enumerate(self.PET_FIELDS):
            ttk.Label(body, text=lab, width=8).grid(row=i // 2, column=(i % 2) * 2, sticky='w', pady=3)
            v = tk.StringVar(value=str(e.get(key, p[key])))
            ttk.Entry(body, textvariable=v, width=12).grid(row=i // 2, column=(i % 2) * 2 + 1,
                                                           sticky='w', padx=(0, 20))
            V[key] = v
        qb = ttk.Frame(win); qb.pack(fill='x', padx=14, pady=(8, 0))

        def do_save():
            for key, var in V.items():
                txt = var.get().strip()
                if txt == '': continue
                try:
                    e[key] = int(txt)
                except Exception:
                    messagebox.showerror('数值不合法', '%s 不是整数' % key); return
            self.pet_edits[k] = e
            win.destroy()
            self._refresh_pet()
            self.status('已记下 %s 的改动（%d 项）' % (p['name'], len(e)))

        def do_revert():
            self.pet_edits.pop(k, None)
            win.destroy()
            self._refresh_pet()

        ttk.Button(qb, text='修改', command=do_save).pack(side='left')
        ttk.Button(qb, text='还原本宠物', command=do_revert).pack(side='left', padx=8)
        ttk.Button(qb, text='关闭', command=win.destroy).pack(side='right')
        self.pet_vars = V
        self.pet_dlg = win
        if modal:
            win.grab_set()
            win.wait_window()
        return win

    # -------------------------------------------------- 人物修改
    def _ui_hero(self):
        f = self.tab_hero
        bar = ttk.Frame(f); bar.pack(fill='x', padx=8, pady=(8, 4))
        ttk.Label(bar, text='搜索武将：').pack(side='left')
        self.var_hq = tk.StringVar()
        e = ttk.Entry(bar, textvariable=self.var_hq, width=22)
        e.pack(side='left'); e.bind('<Return>', lambda ev: self.refresh_hero_list())
        ttk.Button(bar, text='查找', command=self.refresh_hero_list).pack(side='left', padx=6)
        ttk.Button(bar, text='修改', command=self.hero_open_selected).pack(side='left', padx=6)
        self.lbl_hero = ttk.Label(bar, text='', foreground='#666'); self.lbl_hero.pack(side='left', padx=10)
        self.lbl_hero_note = ttk.Label(bar, text='提示：双击某一行即可弹出该武将的全部属性',
                                       foreground='#2f6fed'); self.lbl_hero_note.pack(side='left')

        holder, self.tv_hero = self.make_table(
            f, [('id', 'ID', 110), ('name', '姓名', 120),
                ('six', '六维（统率/武力/智略/政略/魅力/意志）', 320),
                ('tal', '资质', 200)], height=22)
        holder.pack(fill='both', expand=True, padx=8, pady=(0, 8))
        self.tv_hero.bind('<<TreeviewSelect>>', lambda ev: None)
        self.tv_hero.bind('<Double-1>', lambda ev: self.hero_open_selected())

    def hero_open_selected(self):
        sel = self.tv_hero.selection()
        if not sel:
            messagebox.showwarning('提示', '先在列表里选一个武将。'); return
        self.hero_edit_dialog(int(sel[0]))

    def hero_edit_dialog(self, idx, modal=True):
        """双击武将 → 弹窗里放全部可改属性。"""
        h = self.save.heroes[idx]
        so = h.get('six_off')
        raw = self.save.raw
        cur = self.hero_edits.get(idx, {})
        win = tk.Toplevel(self.root)
        win.title('属性修改 · %s（%s）' % (h.get('name') or h['id'], h['id']))
        win.geometry('1000x640')
        try:
            win.transient(self.root)
        except Exception:
            pass
        hd = ttk.Frame(win, padding=(12, 10, 12, 4)); hd.pack(fill='x')
        ttk.Label(hd, text='%s · %s' % (h.get('name') or h['id'], h['id']),
                  font=('Microsoft YaHei', 12, 'bold')).pack(side='left')
        if so is None:
            ttk.Label(hd, text='  ⚠ 该记录没有六维块：六维 / 魂类不可改', foreground='#9a5c08').pack(side='left')

        wrap, inner = self.make_scroll(win, height=520)
        wrap.pack(fill='both', expand=True, padx=12, pady=4)
        V = {}

        def put(key, val):
            V[key] = tk.StringVar(value=str(cur.get(key, val)))
            return V[key]

        def group(row, title, labels, key, base, n, width=7, per_row=6):
            gf = ttk.LabelFrame(inner, text=title, padding=(8, 4))
            gf.grid(row=row, column=0, sticky='we', padx=4, pady=3)
            for k in range(n):
                c, r = k % per_row, k // per_row
                ttk.Label(gf, text=labels[k]).grid(row=r * 2, column=c, sticky='w', padx=3, pady=(2, 0))
                v = (sc.i32(raw, so + base + k * 4) if so is not None else '')
                ttk.Entry(gf, textvariable=put(key + str(k), v), width=width).grid(row=r * 2 + 1, column=c, padx=3)

        group(0, '六维（统率/武力/智略/政略/魅力/意志，0-300）', sc.LAB_SIX, 'six', 0, 6)
        # 资质 + 其他
        gf = ttk.LabelFrame(inner, text='资质（0-30）与 其他', padding=(8, 4))
        gf.grid(row=1, column=0, sticky='we', padx=4, pady=3)
        for k in range(6):
            ttk.Label(gf, text=sc.LAB_TAL[k]).grid(row=0, column=k, sticky='w', padx=3)
            ttk.Entry(gf, textvariable=put('tal%d' % k, sc.i32(raw, h['tal_off'] + k * 4)),
                      width=7).grid(row=1, column=k, padx=3)
        for k, (key, lb, off) in enumerate([('moral', '道德', sc.O_MORAL), ('compat', '相性', sc.O_COMPAT),
                                            ('birth', '出生年', sc.O_BIRTH), ('show', '登场年', sc.O_SHOW),
                                            ('death', '死亡年', sc.O_DEATH)]):
            ttk.Label(gf, text=lb).grid(row=0, column=6 + k, sticky='w', padx=3)
            ttk.Entry(gf, textvariable=put(key, sc.i32(raw, h['tal_off'] + off)),
                      width=7).grid(row=1, column=6 + k, padx=3)
        group(2, '三魂点（军魂/武魂/智魂，上限 999999）', LAB_SOULPT, 'spt', sc.O_SOULPT, 3, 9, 3)
        group(3, '三魂炼魂等级（上限 10）', LAB_SOULLV, 'slv', sc.O_SOULLV, 3)
        group(4, '武器熟练（8 项，上限 300）', LAB_MASTER, 'mst', sc.O_MASTER, 8)
        group(5, '特性等级（24 项，0-6）', LAB_PROF, 'prf', sc.O_PROF, 24)

        # 性格：做法和「称号与资源」页保持一致 —— 左边当前列表、右边搜索 + 加入/删除/还原。
        # 存盘时整段重建（和称号列表同一套路），所以增删改走同一条路，数量也没有上限。
        cell = sc.find_character_cell(raw, h) or []
        self.hero_char_base = [(c['id'], c['lv']) for c in cell]
        self.hero_char_list = list(self.hero_chars.get(idx) or self.hero_char_base)
        cf = ttk.LabelFrame(inner, text='性格', padding=(8, 6))
        cf.grid(row=6, column=0, sticky='we', padx=4, pady=3)
        if cell:
            lf = ttk.Frame(cf); lf.pack(side='left', fill='both', expand=True)
            th, self.tv_hchar = self.make_table(
                lf, [('name', '性格', 150), ('id', 'ID', 80)], height=7)
            th.pack(fill='both', expand=True)
            self.tv_hchar.bind('<Double-1>', lambda ev: self.hchar_del())
            rf = ttk.Frame(cf); rf.pack(side='right', fill='y', padx=(10, 0))
            ttk.Label(rf, text='搜索性格').pack(anchor='w')
            self.var_hcq = tk.StringVar()
            ent = ttk.Entry(rf, textvariable=self.var_hcq, width=20); ent.pack(fill='x', pady=3)
            ent.bind('<Return>', lambda ev: self.hchar_pick())
            ttk.Button(rf, text='查找', command=self.hchar_pick).pack(fill='x')
            self.cb_hchar = ttk.Combobox(rf, state='readonly', width=22)
            self.cb_hchar.pack(fill='x', pady=(8, 3))
            ttk.Button(rf, text='加入所选性格', command=self.hchar_add).pack(fill='x', pady=2)
            ttk.Button(rf, text='删除列表中选中', command=self.hchar_del).pack(fill='x', pady=2)
            ttk.Button(rf, text='恢复原始性格', command=self.hchar_revert).pack(fill='x', pady=(10, 0))
            self.lbl_hchar = ttk.Label(rf, text='', foreground='#666', wraplength=200, justify='left')
            self.lbl_hchar.pack(anchor='w', pady=(8, 0))
            self.hchar_pick()
            self.hchar_refresh()
        else:
            ttk.Label(cf, text='该武将记录里没找到性格段（可导出诊断数据反馈）',
                      foreground='#9a5c08').pack(anchor='w')

        qb = ttk.Frame(inner); qb.grid(row=7, column=0, sticky='we', padx=4, pady=(8, 2))

        def fill(key, val, n):
            for k in range(n):
                if (key + str(k)) in V:
                    V[key + str(k)].set(str(val))

        def soul_max():
            fill('spt', MAX_SOULPT, 3); fill('slv', MAX_SOULLV, 3)

        def do_revert():
            self.hero_edits.pop(idx, None)
            win.destroy()
            self.refresh_hero_list()
            self.status('已还原该武将')

        def do_save():
            e = self.hero_edits.setdefault(idx, {})
            try:
                for k, var in V.items():
                    txt = var.get().strip()
                    if txt == '': continue
                    e[k] = int(txt)
                # 性格：整段重建（和称号列表同一套思路）—— 列表已经在弹窗里维护好了
                chars = list(getattr(self, 'hero_char_list', None) or [])
                if not chars:
                    messagebox.showerror('至少要留一个', '每个武将至少要保留一个性格。'); return
                if len(set(c for c, _ in chars)) != len(chars):
                    messagebox.showerror('性格重复', '同一个武将不能有两个相同的性格。'); return
                if chars != list(getattr(self, 'hero_char_base', None) or []):
                    self.hero_chars[idx] = chars       # 真的变了才整段重建
                else:
                    self.hero_chars.pop(idx, None)
            except Exception as err:
                messagebox.showerror('数值不合法', str(err)); return
            win.destroy()
            self.refresh_hero_list()
            self.status('已记下 %s 的改动（%d 项）' % (h.get('name') or h['id'], len(e)))

        for txt, fn in (('六维全 100', lambda: fill('six', 100, 6)),
                        ('六维全 300', lambda: fill('six', 300, 6)),
                        ('资质全 30', lambda: fill('tal', 30, 6)),
                        ('三魂拉满', soul_max),
                        ('熟练拉满', lambda: fill('mst', MAX_MASTER, 8)),
                        ('特性拉满', lambda: fill('prf', MAX_PROF, 24))):
            ttk.Button(qb, text=txt, command=fn).pack(side='left', padx=3)
        ttk.Button(qb, text='修改', command=do_save).pack(side='left', padx=14)
        ttk.Button(qb, text='还原本武将', command=do_revert).pack(side='left')
        ttk.Button(qb, text='关闭', command=win.destroy).pack(side='right')

        self.hero_vars = V          # 供自测/调试
        self.hero_dlg = win
        if modal:
            win.grab_set()
            win.wait_window()
        return win

    # -------------------------------------------------- 弹窗里的性格编辑（仿「称号与资源」页）
    def hchar_pick(self):
        """按关键字筛性格，填进右边的下拉。"""
        q = (self.var_hcq.get() or '').strip()
        vals = ['%d %s' % (k, sc.CHAR_NAMES[k]) for k in sorted(sc.CHAR_NAMES)
                if (not q) or (q in sc.CHAR_NAMES[k]) or (q == str(k))]
        self.cb_hchar['values'] = vals
        if vals:
            self.cb_hchar.current(0)
        else:
            self.cb_hchar.set('')
        self.lbl_hchar.configure(text='匹配 %d 个性格%s' % (len(vals), '（换个词试试）' if not vals else ''))

    def hchar_refresh(self):
        """把当前性格列表刷到左边的表格里。"""
        tv = getattr(self, 'tv_hchar', None)
        if not tv:
            return
        tv.delete(*tv.get_children())
        for k, (cid, lv) in enumerate(getattr(self, 'hero_char_list', []) or []):
            tv.insert('', 'end', iid=str(k), values=(sc.char_name(cid), cid))

    def hchar_add(self):
        m = re.match(r'^\s*(\d+)', self.cb_hchar.get() or '')
        if not m:
            messagebox.showwarning('提示', '先在右边搜索，再从下拉里选一个性格。'); return
        cid = int(m.group(1))
        if any(c == cid for c, _ in self.hero_char_list):
            messagebox.showwarning('已经有了', '「%s」已经在列表里了。' % sc.char_name(cid)); return
        self.hero_char_list.append((cid, 1))
        self.hchar_refresh()

    def hchar_del(self):
        sel = self.tv_hchar.selection() if getattr(self, 'tv_hchar', None) else ()
        if not sel:
            messagebox.showwarning('提示', '先在左边选中要删的性格（也可以双击一行直接删）。'); return
        for k in sorted((int(x) for x in sel), reverse=True):
            if 0 <= k < len(self.hero_char_list):
                del self.hero_char_list[k]
        self.hchar_refresh()

    def hchar_revert(self):
        self.hero_char_list = list(getattr(self, 'hero_char_base', None) or [])
        self.hchar_refresh()

    def hero_revert(self):
        sel = self.tv_hero.selection()
        if sel:
            self.hero_edits.pop(int(sel[0]), None)
        self.hero_show_fields()
        self.refresh_hero_list()
        self.status('已还原该武将（未保存前的改动丢弃）')

    def _refresh_hero(self):
        self.refresh_hero_list()

    def refresh_hero_list(self):
        self.tv_hero.delete(*self.tv_hero.get_children())
        if not self.save: return
        q = (self.var_hq.get() or '').strip()
        n = 0
        for idx, h in enumerate(self.save.heroes):
            if q and q not in h['id'] and q not in (h.get('name') or ''): continue
            six = ''
            if h.get('six_off') is not None:
                six = ' / '.join(str(sc.i32(self.save.raw, h['six_off'] + j * 4)) for j in range(6))
            tal = ' / '.join(str(sc.i32(self.save.raw, h['tal_off'] + j * 4)) for j in range(6))
            self.tv_hero.insert('', 'end', iid=str(idx), values=(h['id'], h.get('name', ''), six, tal))
            n += 1
            if n >= 1500: break
        self.lbl_hero.configure(text='共 %d 条记录' % len(self.save.heroes))

    # -------------------------------------------------- 使用方法
    def _ui_help(self):
        txt = tk.Text(self.tab_help, wrap='word', font=('Microsoft YaHei', 10), padx=10, pady=10)
        txt.pack(fill='both', expand=True)
        txt.insert('1.0', HELP_TEXT)
        txt.configure(state='disabled')

    def _ui_log(self):
        """更新日志（内置在 updater.CHANGELOG 里，不依赖外部文件）。"""
        top = ttk.Frame(self.tab_log)
        top.pack(fill='x', padx=10, pady=(10, 0))
        ttk.Label(top, text='更新日志', font=('Microsoft YaHei', 11, 'bold')).pack(side='left')
        ttk.Label(top, text='当前版本 V%s' % UP.VERSION_STR, foreground='#666'
                  ).pack(side='left', padx=(12, 0))
        ttk.Button(top, text='检查更新', width=12,
                   command=self.do_check_update).pack(side='right')

        txt = tk.Text(self.tab_log, wrap='word', font=('Microsoft YaHei', 10),
                      padx=12, pady=10, spacing1=2, spacing3=4)
        vs = ttk.Scrollbar(self.tab_log, orient='vertical', command=txt.yview)
        txt.configure(yscrollcommand=vs.set)
        txt.pack(side='left', fill='both', expand=True, padx=(10, 0), pady=10)
        vs.pack(side='right', fill='y', padx=(0, 10), pady=10)

        txt.tag_configure('head', font=('Microsoft YaHei', 11, 'bold'), spacing1=10, spacing3=4)
        txt.tag_configure('item', font=('Microsoft YaHei', 10), lmargin1=18, lmargin2=30)
        txt.tag_configure('cur', foreground='#c0392b')
        for ver, kind, items in UP.CHANGELOG:
            tags = ('head', 'cur') if ver == UP.VERSION_STR else ('head',)
            txt.insert('end', 'V%s%s\n' % (ver,
                                           '　（当前版本）' if ver == UP.VERSION_STR else ''),
                       tags)
            for it in items:
                txt.insert('end', '· ' + it + '\n', 'item')
        txt.insert('end', '\n以上为历史版本记录。\n')
        txt.configure(state='disabled')


HELP_TEXT = """英雄立志传·三国志 存档修改器 V1.0.10（By Kin） —— 使用方法

【0】完全退出游戏再改，改完再进游戏；游戏运行中改会被覆盖回去。

【常用功能】
  · 读取存档：选择 SaveData 目录下的 Save0.dat / Save1.dat 等文件。
  · 备份存档：把原始存档另存一份，改之前建议先点。
  · 生成并保存新存档：把界面上的改动写回，并做回读校验，保存后用同名文件覆盖回 SaveData。
  · 导出诊断数据：遇到问题时一键打包环境、定位结果、日志与报错，连同问题描述发给开发者。
  · 更新物品库：读取游戏 Json + MODs + MODProjects 重新生成物品库，装了新 MOD 就点一下。
  · 存档目录与游戏目录会自动探测，也可以在界面上手动指定，会记住。

【各种添加】
  · 上面一排是分类：武器 / 防具 / 饰品 / 道具 / 重要 / 材料 / 其它 / 称号证书 / 制造书 / 魂类。
  · 左边是多选列表，按住 Ctrl 或 Shift 可多选；右边是关键词查找、等级筛选、价值筛选、数量、添加、清除。
  · 添加时按物品库里的推荐组自动归组，与游戏实际的背包分类一致：
    0 武器 / 1 防具 / 2 佩饰 / 3 坐骑 / 4 头盔 / 5 盾牌 / 6 任务道具·特殊 / 7 礼物珍玩 /
    8 书籍 / 9 称号证书·丹药·制造书 / 10 话题 / 11 魂与技 / 12 材料货物。

【背包管理】默认列出整个背包的全部物品，可用关键词、分类、组来筛选；可修改数量、删除所选、还原背包。

【称号与资源】称号证书可增删，保存时重写称号列表；金钱 / 灵蕴 / 科技点 / 策略点 / 国库金 改完点「修改」。
  国库金只有已自立势力的君主档才有；武将档（只有家族资源）和自建档读不到时该项置灰，属正常。

【城市属性修改】表格里是全部城市，可滚动；选一座城改资金 / 军粮 / 人口 / 治安，改完点「修改」。

【宠物修改】列出你名下的全部宠物，双击某一行弹出数值窗，可改：
  等级上限 / 月饲养费 / 价值 / 攻击力 / 防御力 / 速度 / 生命值。

【人物修改】搜武将看六维；双击某一行弹出该武将的全部可改属性：
  六维 0-300、资质 0-30、道德·相性·出生年·登场年·死亡年、
  三魂点上限 999999、三魂炼魂等级上限 10、武器熟练 8 项上限 300、特性 24 项 0-6。
  快捷按钮：六维全 100、六维全 300、资质全 30、三魂拉满、熟练拉满、特性拉满、还原本武将。
  性格：弹窗最下面是该武将当前的性格（存档里是「性格id + 等级 0-3」的成对数据，最多 12 个）。
  左格填「id 名称」，也可以直接输入数字改 id；右格是等级。改完点「修改」再生成存档即可。
"""


def _icon_path():
    """assets/icon.ico 的绝对路径；找不到返回 None（打包/源码两种布局都试）。"""
    here = os.path.dirname(os.path.abspath(__file__))
    for p in (os.path.join(here, 'assets', 'icon.ico'),
              os.path.join(here, 'icon.ico')):
        if os.path.isfile(p):
            return p
    return None


def main():
    DIAG.log('启动：%s' % APP)
    DIAG.log('python=%s  frozen=%s' % (sys.version.split()[0], getattr(sys, 'frozen', False)))
    root = tk.Tk()
    # 窗口/任务栏图标（2026-10-23 新增，皮肤头像原图）
    # iconbitmap 只会用 ico 里的 32px 小帧（任务栏上发糊）；
    # iconphoto 传 256px 的 PhotoImage，Windows 用高质量缩放画任务栏图标，清晰得多。
    try:
        _ico = _icon_path()
        _ph = None
        if _ico:
            try:
                from PIL import Image, ImageTk
                _img = Image.open(_ico)
                try:
                    _img.size = (256, 256)   # ico 多帧容器选最大帧
                except ValueError:
                    pass
                _img.load()
                _ph = ImageTk.PhotoImage(_img.convert('RGBA'))
            except Exception:
                _ph = None
        if _ph is not None:
            root.iconphoto(True, _ph)
            _ICON_KEEPALIVE.append(_ph)   # 防 PhotoImage 被 GC
        elif _ico:
            root.iconbitmap(_ico)
    except Exception:
        pass

    def ui_err(exc, val, tb):
        DIAG.err('界面回调', val)
        try:
            messagebox.showerror('出错了',
                '%s\n\n（这个错误已被记录，可以用「常用功能 → 导出诊断数据」发给我）' % val)
        except Exception:
            pass
    root.report_callback_exception = ui_err
    sys.excepthook = lambda t, v, tb: DIAG.err('未捕获异常', v)
    try:
        App(root)
        root.mainloop()
    except Exception:
        DIAG.err('主流程')
        raise


if __name__ == '__main__':
    main()
