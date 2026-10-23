# -*- coding: utf-8 -*-
"""基准档快照 / 重新适配检查。

背景：小K 每次改完版本，会重新载入 Save4 / Save5 并保存，然后要判断
「换档后还能不能正确读到人物 / 背包 / 称号 / 资源」。
这个脚本把这两个档的**逻辑内容 + 定位结果**拍成基线快照，日后重读档直接对比。

用法（python38 跑，不需要 tkinter）：
    python 存档快照.py 生成                    # 读游戏存档目录的 Save4.dat / Save5.dat 拍基线
    python 存档快照.py 生成 Save4 <档路径>      # 只拍一个槽位
    python 存档快照.py 对比                    # 重新读档，与基线比对，输出报告
    python 存档快照.py 对比 Save4 <档路径>
    python 存档快照.py 列表                    # 看已有基线

产物：
    快照/Save4_基线.json     逻辑内容 + 定位锚点（脚本用）
    快照/Save4_基线.md       人看的中文摘要
    快照/对比报告_<时间>.md   对比结论（对比时生成）
"""
import io
import json
import os
import hashlib
import struct
import sys
import time

ROOT = r'F:/WB/2026-10-07-16-23-32'
APP = os.path.join(ROOT, 'App')
SNAP_DIR = os.path.join(ROOT, '快照')
CAT_JS = os.path.join(ROOT, '存档修改器', '物品库.js')
GAME_SAVE = os.path.join(os.environ.get('USERPROFILE') or '', 'AppData', 'LocalLow',
                         'FreeWing', 'ThreeKingdom', 'SaveData')
SLOTS = ('Save4', 'Save5')

sys.path.insert(0, APP)
import savecore as sc                                              # noqa: E402


# ---------------------------------------------------------------- 物品库
def load_catalog():
    """从 物品库.js 里抽 window.XXX=... 的 JSON（和界面 Catalog.load 同一套规则）。"""
    out = {}
    if not os.path.exists(CAT_JS):
        return out
    src = io.open(CAT_JS, encoding='utf-8').read()
    for key in ('CITY_ID', 'CITY_NAME', 'GRP_LABEL', 'ITEM_CAT', 'PET_CAT'):
        i = src.find('window.%s=' % key)
        if i < 0:
            continue
        i += len('window.%s=' % key)
        j = src.find(';\n', i)
        try:
            out[key] = json.loads(src[i:j])
        except Exception:
            out[key] = {}
    return out


def cat_for_engine(C):
    cat = {'__CITY_ID__': C.get('CITY_ID') or {}, '__CITY_NAME__': C.get('CITY_NAME') or {},
           '__PET_CAT__': C.get('PET_CAT') or {}}
    cat.update({k: 1 for k in (C.get('ITEM_CAT') or {})})
    return cat


def name_of(C, iid):
    v = (C.get('ITEM_CAT') or {}).get(iid)
    return v[0] if v else iid


# ---------------------------------------------------------------- 拍快照
def hero_snap(raw, h):
    d = {'id': h['id'], 'name': h.get('name'), 'kind': h['kind'],
         'six_off': h.get('six_off'), 'cs': h.get('six_cs')}
    so = h.get('six_off')
    if so is not None and so + sc.O_PROF + 96 <= len(raw):
        d['six'] = list(struct.unpack_from('<6i', raw, so))
        d['soul'] = list(struct.unpack_from('<3i', raw, so + sc.O_SOULPT))
        d['lv'] = list(struct.unpack_from('<3i', raw, so + sc.O_SOULLV))
        d['master'] = list(struct.unpack_from('<8i', raw, so + sc.O_MASTER))
        d['prof'] = list(struct.unpack_from('<24i', raw, so + sc.O_PROF))
    t = h.get('tal_off')
    if t is not None and t + 0x60 <= len(raw):
        d['tal'] = list(struct.unpack_from('<6i', raw, t))
        d['moral'] = sc.i32(raw, t + sc.O_MORAL)
        d['compat'] = sc.i32(raw, t + sc.O_COMPAT)
        d['birth'] = sc.i32(raw, t + sc.O_BIRTH)
        d['show'] = sc.i32(raw, t + sc.O_SHOW)
        d['death'] = sc.i32(raw, t + sc.O_DEATH)
    return d


def make_snapshot(path, slot, C):
    data = open(path, 'rb').read()
    s = sc.SaveFile(data, cat_for_engine(C))
    raw = s.raw
    bag = s.bag or {}
    groups = bag.get('groups') or []
    tit = s.titles or None
    fac = s.faction or {}
    pets = s.pets or None

    snap = {
        'slot': slot,
        'src': os.path.abspath(path),
        'size': len(data),
        'sha256': hashlib.sha256(data).hexdigest(),
        'mtime': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(os.path.getmtime(path))),
        'made_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        'ver': s.ver, 'slot_num': s.slot,
        'role': s.role, 'is_ruler': s.is_ruler, 'place': s.place,
        'strings': [x[1] for x in s.strings[:14]],
        'money': s.money, 'money_head_off': s.money_off,
        'loc': {
            'money2': s.money2,
            'bag': None if not bag else {
                'start': bag['start'], 'end': bag['end'], 'ngroups': len(groups),
                'items': sum(len(g['items']) for g in groups),
                'sizes': [len(g['items']) for g in groups]},
            'titles': None if not tit else {
                'count_off': tit['count_off'], 'start': tit['start'], 'end': tit['end'],
                'n': len(tit['ids']), 'on_catalog': tit['nt'], 'ratio': round(tit['ratio'], 3)},
            'res': {'kind': fac.get('kind'), 'tech': fac.get('tech'), 'strat': fac.get('strat'),
                    'treasury': fac.get('treasury'), 'tech_off': fac.get('tech_off'),
                    'strat_off': fac.get('strat_off'), 'treasury_off': fac.get('treasury_off'),
                    'note': fac.get('note')},
            'cities': len(s.cities),
            'pets': None if not pets else {'count': pets.get('count'), 'off': pets.get('off')},
        },
        'heroes': [hero_snap(raw, h) for h in s.heroes],
        'bag': [[gi, e['id'], e['qty'], e['f2'], e['f3']]
                for gi, g in enumerate(groups) for e in g['items']],
        'titles': list(tit['ids']) if tit else [],
    }
    return snap


# ---------------------------------------------------------------- 写基线
def hexo(v):
    return 'None' if v is None else '0x%X' % v


def write_md(snap, path, C):
    loc = snap['loc']
    L = ['# %s 基线快照' % snap['slot'], '',
         '拍于 %s ｜ 来源 `%s`' % (snap['made_at'], snap['src']), '',
         '## 文件与身份', '',
         '| 项目 | 值 |', '| --- | --- |',
         '| 大小 | %s B |' % format(snap['size'], ','),
         '| sha256 | `%s` |' % snap['sha256'][:16] + '…',
         '| 版本戳 / 槽位 | %s / %s |' % (snap['ver'], snap['slot_num']),
         '| 身份 | %s（%s） |' % (snap['role'], '已自立势力' if snap['is_ruler'] else '未自立势力'),
         '| 当前地点 | %s |' % snap['place'],
         '| 头部串 | %s |' % ' / '.join(snap['strings'][:8]), '',
         '## 定位结果（重读档时这几项必须命中）', '',
         '| 项目 | 偏移 | 内容 |', '| --- | --- | --- |',
         '| 个人金钱 | %s（头部） | %s |' % (hexo(snap['money_head_off']), format(snap['money'], ',')),
         '| 资产块金钱 money2 | %s | 背包起点 - 4 |' % hexo(loc['money2'])]
    b = loc['bag']
    if b:
        lines = ['| 背包 | %s ~ %s | %s 组 / %s 件，各组 %s |'
                 % (hexo(b['start']), hexo(b['end']), b['ngroups'], b['items'], b['sizes'])]
    else:
        lines = ['| 背包 | 未定位 | |']
    L += lines
    t = loc['titles']
    if t:
        L.append('| 称号列表 | %s ~ %s | %s 条（物品库里认得 %s 条） |'
                 % (hexo(t['start']), hexo(t['end']), t['n'], t['on_catalog']))
    else:
        L.append('| 称号列表 | 未定位 | |')
    r = loc['res']
    if r['kind'] == 'faction':
        L.append('| 势力资源 | 科技 %s / 策略 %s / 国库 %s | 科技 %s、策略 %s、国库 %s |'
                 % (hexo(r['tech_off']), hexo(r['strat_off']), hexo(r['treasury_off']),
                    r['tech'], r['strat'], r['treasury']))
    else:
        L.append('| 家族资源 | 科技 %s / 策略 %s | 科技 %s、策略 %s、国库 %s |'
                 % (hexo(r['tech_off']), hexo(r['strat_off']), r['tech'], r['strat'],
                    '无' if r['treasury'] is None else r['treasury']))
    L.append('| 城市 | — | %s 座 |' % loc['cities'])
    p = loc['pets']
    if p:
        L.append('| 宠物 | %s | %s 只 |' % (hexo(p['off']), p['count']))
    else:
        L.append('| 宠物 | 该档没有宠物列表 | — |')

    L += ['', '## 武将（%d 条）' % len(snap['heroes']), '',
          '按六维和排序取前 15 条，方便肉眼比对：', '',
          '| ID | 姓名 | 类型 | 统率 | 武力 | 智略 | 政略 | 魅力 | 意志 | 特性(非零) |',
          '| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |']
    hs = [h for h in snap['heroes'] if h.get('six')]
    hs.sort(key=lambda h: -sum(h['six']))
    for h in hs[:15]:
        L.append('| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |'
                 % (h['id'], h['name'], h['kind'], *h['six'],
                    ' '.join('%d:%d' % (i + 1, v) for i, v in enumerate(h.get('prof') or []) if v)))
    L += ['', '## 称号（%d 条）' % len(snap['titles']), '']
    if snap['titles']:
        L.append('| # | 称号 ID | 名称 | 价格 |')
        L.append('| --- | --- | --- | --- |')
        for i, t in enumerate(snap['titles'], 1):
            v = (C.get('ITEM_CAT') or {}).get('HTC' + t)
            L.append('| %d | %s | %s | %s |' % (i, t, v[0] if v else '（物品库无）',
                                                v[4] if v and len(v) > 4 else '—'))
    else:
        L.append('（未定位到称号列表）')
    L += ['', '## 背包（%d 件）' % len(snap['bag']), '']
    if snap['bag']:
        L.append('| 组 | 物品 ID | 名称 | 数量 | f2 | f3 |')
        L.append('| --- | --- | --- | --- | --- | --- |')
        for gi, iid, qty, f2, f3 in snap['bag'][:120]:
            L.append('| %d | %s | %s | %d | 0x%X | %d |' % (gi, iid, name_of(C, iid), qty, f2 & 0xFFFFFFFF, f3))
        if len(snap['bag']) > 120:
            L.append('')
            L.append('（只列前 120 件，完整内容见同名 .json）')
    else:
        L.append('（未定位到背包）')
    io.open(path, 'w', encoding='utf-8').write('\n'.join(L) + '\n')


def cmd_make(slots, C):
    made = []
    for slot, path in slots:
        if not os.path.exists(path):
            print('  [跳过] %s：找不到 %s' % (slot, path))
            continue
        print('  拍快照 %s <- %s ...' % (slot, path))
        snap = make_snapshot(path, slot, C)
        os.makedirs(SNAP_DIR, exist_ok=True)
        jp = os.path.join(SNAP_DIR, '%s_基线.json' % slot)
        mp = os.path.join(SNAP_DIR, '%s_基线.md' % slot)
        io.open(jp, 'w', encoding='utf-8').write(json.dumps(snap, ensure_ascii=False, indent=1))
        write_md(snap, mp, C)
        loc = snap['loc']
        print('    -> %s（武将 %d / 背包 %s 件 / 称号 %s 条 / 资源 %s %s）'
              % (os.path.basename(jp), len(snap['heroes']),
                 loc['bag']['items'] if loc['bag'] else '未定位',
                 loc['titles']['n'] if loc['titles'] else '未定位',
                 loc['res']['kind'], loc['res']['tech']))
        made.append(jp)
    print('基线已生成 %d 份，目录：%s' % (len(made), SNAP_DIR))


# ---------------------------------------------------------------- 对比
def diff_bag(base, cur):
    def agg(rows):
        m = {}
        for gi, iid, qty, f2, f3 in rows:
            m[iid] = m.get(iid, 0) + qty
        return m
    a, b = agg(base), agg(cur)
    add = [(k, b[k]) for k in b if k not in a]
    rm = [(k, a[k]) for k in a if k not in b]
    ch = [(k, a[k], b[k]) for k in a if k in b and a[k] != b[k]]
    return add, rm, ch


def cmd_check(slots, C):
    lines, fails, warns = [], [], []
    for slot, path in slots:
        jp = os.path.join(SNAP_DIR, '%s_基线.json' % slot)
        if not os.path.exists(jp):
            print('  [跳过] %s：还没有基线，先跑「生成」' % slot)
            continue
        if not os.path.exists(path):
            print('  [跳过] %s：找不到存档 %s' % (slot, path))
            continue
        base = json.loads(io.open(jp, encoding='utf-8').read())
        print('  对比 %s <- %s ...' % (slot, path))
        cur = make_snapshot(path, slot, C)
        bl, cl = base['loc'], cur['loc']
        lines += ['## %s' % slot, '',
                  '- 存档：`%s`' % path,
                  '- 大小 %s B（基线 %s B，差 %+d）｜ sha256 %s'
                  % (format(cur['size'], ','), format(base['size'], ','),
                     cur['size'] - base['size'],
                     '一致' if cur['sha256'] == base['sha256'] else '已变化（正常，游戏里存过盘）'),
                  '- 身份 %s / %s ｜ 地点 %s（基线 %s）'
                  % (cur['role'], '自立' if cur['is_ruler'] else '未自立', cur['place'], base['place']), '']
        lines += ['| 定位项 | 结果 | 本次 | 基线 | 漂移 |', '| --- | --- | --- | --- | --- |']
        # 背包
        if cl['bag']:
            drift = cl['bag']['start'] - bl['bag']['start'] if bl['bag'] else None
            lines.append('| 背包 | 命中 | %s 件 / %s 组 | %s 件 / %s 组 | %s |'
                         % (cl['bag']['items'], cl['bag']['ngroups'],
                            bl['bag']['items'] if bl['bag'] else '—',
                            bl['bag']['ngroups'] if bl['bag'] else '—',
                            '%+d 字节' % drift if drift is not None else '—'))
            if cl['bag']['items'] == 0:
                warns.append('%s：背包命中但 0 件' % slot)
        else:
            lines.append('| 背包 | **未定位** | — | — | — |')
            fails.append('%s：背包未定位' % slot)
        # 称号
        if cl['titles']:
            lines.append('| 称号列表 | 命中 | %s 条（认得 %s） | %s 条 | %+d 字节 |'
                         % (cl['titles']['n'], cl['titles']['on_catalog'],
                            bl['titles']['n'] if bl['titles'] else '—',
                            cl['titles']['start'] - bl['titles']['start'] if bl['titles'] else 0))
            if bl['titles'] and cl['titles']['n'] == 0:
                warns.append('%s：称号列表命中但 0 条' % slot)
        else:
            lines.append('| 称号列表 | **未定位** | — | — | — |')
            fails.append('%s：称号列表未定位' % slot)
        # 资源
        cr, br = cl['res'], bl['res']
        if cr['kind'] == 'faction' and cr['tech'] is None:
            fails.append('%s：势力资源未定位' % slot)
            lines.append('| 资源 | **未定位** | — | — | — |')
        elif cr['kind'] == 'family' and cr['tech'] is None and br.get('tech') is not None:
            warns.append('%s：家族资源这次没读到（基线读到 %s）' % (slot, br['tech']))
            lines.append('| 资源 | 降级 | 未读到 | %s / %s | — |' % (br['tech'], br['strat']))
        else:
            lines.append('| 资源 | 命中 | 科技 %s / 策略 %s / 国库 %s | 科技 %s / 策略 %s / 国库 %s | %s |'
                         % (cr['tech'], cr['strat'], cr['treasury'],
                            br['tech'], br['strat'], br['treasury'],
                            '%+d 字节' % ((cr['tech_off'] or 0) - (br['tech_off'] or 0))
                            if (cr['tech_off'] and br['tech_off']) else '—'))
        if cl['pets'] or bl['pets']:
            lines.append('| 宠物 | %s | %s 只 | %s 只 | — |'
                         % ('命中' if cl['pets'] else '未定位',
                            cl['pets']['count'] if cl['pets'] else '—',
                            bl['pets']['count'] if bl['pets'] else '—'))
        else:
            lines.append('| 宠物 | 该档没有宠物列表（基线也没有，正常） | — | — | — |')
        if not cl['pets'] and bl['pets']:
            warns.append('%s：宠物列表这次没定位到' % slot)

        # ---- 内容变化
        lines += ['', '### 内容变化（游戏里正常推进也会变）', '']
        lines.append('- 个人金钱：%s（基线 %s，%+d）'
                     % (format(cur['money'], ','), format(base['money'], ','), cur['money'] - base['money']))
        add, rm, ch = diff_bag(base['bag'], cur['bag'])
        lines.append('- 背包：新增 %d 种 / 移除 %d 种 / 数量变化 %d 种' % (len(add), len(rm), len(ch)))
        for k, q in add[:10]:
            lines.append('    - ＋ %s（%s）× %d' % (k, name_of(C, k), q))
        for k, q in rm[:10]:
            lines.append('    - － %s（%s）× %d' % (k, name_of(C, k), q))
        for k, a, b in ch[:10]:
            lines.append('    - ± %s（%s）%d → %d' % (k, name_of(C, k), a, b))
        ta, tb = set(base['titles']), set(cur['titles'])
        lines.append('- 称号：新增 %d / 移除 %d' % (len(tb - ta), len(ta - tb)))
        for t in sorted(tb - ta)[:10]:
            lines.append('    - ＋ %s' % t)
        for t in sorted(ta - tb)[:10]:
            lines.append('    - － %s' % t)
        bh = {h['id']: h for h in base['heroes']}
        chs, offs_only = [], 0
        for h in cur['heroes']:
            o = bh.get(h['id'])
            if not o or not h.get('six') or not o.get('six'):
                continue
            f = []
            if h['six'] != o['six']:
                f.append('六维 %s→%s' % (o['six'], h['six']))
            for key, lab in (('tal', '资质'), ('soul', '三魂点'), ('lv', '炼魂'), ('master', '熟练'), ('prof', '特性')):
                if h.get(key) and o.get(key) and h[key] != o[key]:
                    f.append('%s 变了' % lab)
            if f:
                chs.append('%s(%s)：%s' % (h['id'], h.get('name'), '；'.join(f)))
            elif h.get('six_off') != o.get('six_off'):
                offs_only += 1
        lines.append('- 武将：%d 条（基线 %d 条），**属性值有变化 %d 条**；另有 %d 条只是六维块偏移漂移（正常）'
                     % (len(cur['heroes']), len(base['heroes']), len(chs), offs_only))
        for c in chs[:15]:
            lines.append('    - %s' % c)
        lines.append('')

    # ---- 结论
    if fails:
        verdict = '需要重新适配'
        lines += ['## 结论：需要重新适配', '',
                  '下面这些定位失败了，把这份报告发给我，我按新档重新找锚点：', '']
        lines += ['- %s' % f for f in fails]
        lines += ['', '（同时把该存档复制一份给我：`%s`）' % GAME_SAVE]
    elif warns:
        verdict = '定位都命中了，但有可疑项'
        lines += ['## 结论：定位都命中，但有几项可疑（先别改代码）', '']
        lines += ['- %s' % w for w in warns]
    else:
        verdict = '定位全部命中，不需要重新适配'
        lines += ['## 结论：定位全部命中，不需要重新适配', '',
                  '人物 / 背包 / 称号 / 资源 / 宠物 都按同一套不变量命中了。',
                  '偏移有漂移是正常的（存档内容变了偏移就变），只要命中就不需要改代码。']
    report = ['# 存档重新适配检查报告', '',
              '生成于 %s ｜ 物品库 `%s`' % (time.strftime('%Y-%m-%d %H:%M:%S'), CAT_JS), '']
    report += lines
    os.makedirs(SNAP_DIR, exist_ok=True)
    out = os.path.join(SNAP_DIR, '对比报告_%s.md' % time.strftime('%Y%m%d_%H%M%S'))
    io.open(out, 'w', encoding='utf-8').write('\n'.join(report) + '\n')
    print('')
    print('结论：%s' % verdict)
    if fails:
        for f in fails:
            print('  [失败] %s' % f)
    for w in warns:
        print('  [可疑] %s' % w)
    print('报告已写入：%s' % out)
    return 0 if not fails else 1


# ---------------------------------------------------------------- 入口
def parse_args(argv):
    """返回 (模式, [(slot, path)])。"""
    mode = argv[1] if len(argv) > 1 else '对比'
    rest = argv[2:]
    if not rest:
        return mode, [(s, os.path.join(GAME_SAVE, '%s.dat' % s)) for s in SLOTS]
    if len(rest) >= 2:
        return mode, [(rest[0], rest[1])]
    raise SystemExit('只给一个参数时请写「槽位名 存档路径」')


def main():
    mode, slots = parse_args(sys.argv)
    C = load_catalog()
    if not C.get('ITEM_CAT'):
        print('提示：没读到物品库（%s），称号识别会打折扣' % CAT_JS)
    if mode in ('生成', 'make'):
        cmd_make(slots, C)
    elif mode in ('对比', 'check'):
        return cmd_check(slots, C)
    elif mode in ('列表', 'list'):
        if not os.path.isdir(SNAP_DIR):
            print('还没有任何基线（目录不存在）')
            return 0
        for f in sorted(os.listdir(SNAP_DIR)):
            if f.endswith('_基线.json'):
                s = json.loads(io.open(os.path.join(SNAP_DIR, f), encoding='utf-8').read())
                print('%-22s %s ｜ %s' % (f, s['made_at'], s['src']))
        return 0
    else:
        raise SystemExit(__doc__)
    return 0


if __name__ == '__main__':
    sys.exit(main())
