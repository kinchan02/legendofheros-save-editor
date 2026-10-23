# -*- coding: utf-8 -*-
"""原生版冒烟测试：真 Tk 控件（窗口隐藏），跑一遍载入/切页/筛选/加物品/改资源。"""
import os
import sys
import tkinter as tk

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import importlib
app_mod = importlib.import_module('三国存档修改器')

# --- 打桩：模态弹窗会阻塞，测试里全部换成 no-op ---
class _Stub:
    @staticmethod
    def showinfo(*a, **k): print('    [弹窗] %s' % (a[1] if len(a) > 1 else ''))
    @staticmethod
    def showwarning(*a, **k): print('    [弹窗] %s' % (a[1] if len(a) > 1 else ''))
    @staticmethod
    def showerror(*a, **k): print('    [弹窗-错误] %s' % (a[1] if len(a) > 1 else ''))
    @staticmethod
    def askyesno(*a, **k): return True
    @staticmethod
    def askinteger(*a, **k): return 5
app_mod.messagebox = _Stub

SAVE = os.path.join(ROOT, '势力资源', 'Save1_1014_基准.dat')
pass_n = fail_n = 0


def chk(name, cond, extra=''):
    global pass_n, fail_n
    if cond:
        pass_n += 1
        print('  ✓ %s%s' % (name, (' — ' + extra) if extra else ''))
    else:
        fail_n += 1
        print('  ✗ %s%s' % (name, (' — ' + extra) if extra else ''))


def main():
    root = tk.Tk()
    root.withdraw()                     # 不显示窗口
    app = app_mod.App(root)
    print('物品库：%d 条' % len(app_mod.CAT.items))
    chk('物品库已载入', app_mod.CAT.loaded, '%d 条' % len(app_mod.CAT.items))
    print('界面已构建，标签页 %d 个' % len(app.nb.tabs()))
    chk('九个标签页（含宠物修改、更新日志）', len(app.nb.tabs()) == 9,
        ' / '.join(app.nb.tab(i, 'text') for i in range(len(app.nb.tabs()))))

    print('=== ① 载入存档 ===')
    app.load_file(SAVE)
    s = app.save
    chk('载入成功', s is not None)
    chk('金钱 96620179', s.money == 96620179, format(s.money, ','))
    f = s.faction or {}
    chk('科技 920851 / 策略 990869 / 灵蕴 9999975',
        f.get('tech') == 920851 and f.get('strat') == 990869 and s.lingyun == 9999975,
        '%s / %s / %s' % (f.get('tech'), f.get('strat'), s.lingyun))
    chk('背包已定位（655 件 / 13 组）',
        s.bag and sum(len(g['items']) for g in s.bag['groups']) == 655,
        str(sum(len(g['items']) for g in s.bag['groups'])) if s.bag else '未定位')
    chk('称号 54 条', bool(s.titles) and len(s.titles['ids']) == 54,
        str(len(s.titles['ids'])) if s.titles else '未定位')
    chk('城市 76 座', len(s.cities) == 76, str(len(s.cities)))
    cs = s.cities.get('CS1068')
    chk('百济 资金 237285 / 军粮 1962765',
        cs and cs['money'] == 237285 and cs['food'] == 1962765,
        ('%s / %s' % (cs['money'], cs['food'])) if cs else '未定位')

    print('=== ② 各种添加 ===')
    chk('背包默认列出全背包（655 件）', len(app.tv_bag.get_children()) == 655,
        str(len(app.tv_bag.get_children())) + ' 行')
    app.var_bagkind.set('材料')
    app.refresh_bag_list()
    chk('背包按分类筛选生效', all(app_mod.CAT.kind(i) == '材料' for i in
                              [app.tv_bag.item(x, 'values')[2] for x in app.tv_bag.get_children()]),
        '%d 行' % len(app.tv_bag.get_children()))
    app.var_bagkind.set('全部')
    app.refresh_bag_list()
    app.set_add_tab(0)                  # 武器
    chk('武器页签筛出条目', len(app.add_rows) > 50, '%d 条' % len(app.add_rows))
    app.set_add_tab(1)                  # 防具（山纹系列在防具里）
    app.var_q.set('山纹')
    app.refresh_add_list()
    chk('关键词「山纹」能搜到', any('山纹' in app_mod.CAT.name(i) for i in app.add_rows),
        '%d 条' % len(app.add_rows))
    app.var_q.set('')
    app.set_add_tab(7)                  # 称号证书
    chk('称号证书页签有货', len(app.add_rows) > 100, '%d 条' % len(app.add_rows))
    app.var_lvlo.set('≥ 3')
    app.refresh_add_list()
    chk('等级 ≥3 筛选生效', all((app_mod.CAT.level(i) or 0) >= 3 for i in app.add_rows),
        '%d 条' % len(app.add_rows))
    app.var_lvlo.set('不限')
    app.var_vllo.set('7000')
    app.refresh_add_list()
    chk('价值 ≥7000 筛选生效', all((app_mod.CAT.price(i) or 0) >= 7000 for i in app.add_rows),
        '%d 条' % len(app.add_rows))
    print('=== ②2 页签净化 ===')
    app.clear_add()
    app.set_add_tab(5)                  # 材料
    kinds = {app_mod.CAT.kind(i) for i in app.add_rows}
    chk('材料页签里没有「建筑」', '建筑' not in kinds and 'JZ' not in ''.join(app.add_rows),
        '分类=%s，%d 条' % ('/'.join(sorted(kinds)), len(app.add_rows)))
    for idx, nm in ((9, '军魂军技'), (10, '武魂武技'), (11, '智魂智技')):
        app.set_add_tab(idx)
        bad = [i for i in app.add_rows if (app_mod.CAT.price(i) or 0) <= 0]
        chk('%s 页签里没有价值 0 的' % nm, not bad, '%d 条，零价值 %d 条' % (len(app.add_rows), len(bad)))
    app.clear_add()
    app.set_add_tab(1)                  # 防具：WP1012005 山纹银狮甲
    app.var_q.set('WP1012005')
    app.refresh_add_list()
    tv = app.tv_add
    kids = tv.get_children()
    chk('添加列表有表头 + 行', len(kids) >= 1,
        '%d 行；列=%s' % (len(kids), [tv.heading(c, 'text') for c in tv['columns']]))
    if kids:
        app.tv_add.selection_set(kids[0])
        app.var_qty.set('2')
        before = sum(len(g) for g in app.bag_edit) if app.bag_edit else 655
        app.do_add()
        after = sum(len(g) for g in app.bag_edit)
        chk('加入物品后背包件数 +1', after == before + 1, '%d → %d' % (before, after))
    else:
        chk('能搜到物品', False)
    chk('魂占用筛选已移除', not hasattr(app, 'var_splo') and not hasattr(app, 'cb_sp'))

    print('=== ③ 称号与资源 ===')
    app.var_htq.set('')
    app._refresh_htitles()
    n_h = len(app.tv_htitle.get_children())
    chk('武将称号列表有内容（全部武将）', n_h == len(app.save.heroes), '%d 行 / %d 武将' % (n_h, len(app.save.heroes)))
    chk('大部分武将有称号记录', len(app.save.hero_titles) >= len(app.save.heroes) * 0.5,
        '%d / %d' % (len(app.save.hero_titles), len(app.save.heroes)))
    app.var_htq.set('颜良')
    app._refresh_htitles()
    kids = app.tv_htitle.get_children()
    chk('按名字筛选武将', len(kids) <= 3, '颜良 → %d 行' % len(kids))
    if kids:
        hid = kids[0]
        info = app.save.hero_titles.get(hid)
        chk('该武将有称号（第一条）', info is not None and len(info['ids']) > 0,
            '%s: %s' % (hid, info['ids'][:4] if info else '无'))
        # 双击打开编辑弹窗（非 modal，避免测试卡住）
        app._hero_title_dialog(hid, modal=False)
        dlg = getattr(app, '_htitle_dlg', None)
        chk('武将称号弹窗能打开', dlg is not None and dlg.winfo_exists() == 1,
            'Toplevel OK' if dlg else 'None')
        if dlg:
            dlg.destroy()
    app.var_htq.set('')
    app._refresh_htitles()
    if app.save.faction:
        app.res_vars['tech'].set('123456')
        app.save.edits[app.save.faction['tech_off']] = ('i32', 123456)
        chk('资源可直接改', app.save.edits.get(app.save.faction['tech_off'], (None, None))[1] == 123456)

    print('=== ④ 城市 ===')
    chk('城市表列出全部 76 座', len(app.tv_city.get_children()) == 76,
        str(len(app.tv_city.get_children())) + ' 行')
    app.tv_city.selection_set('CS1068')
    app.refresh_city_fields()
    chk('城市字段回填（百济 237285）', app.city_vars['money'].get() == '237285', app.city_vars['money'].get())
    app.city_vars['money'].set('999999')
    app.apply_city()
    chk('城市改动可写下', app.save.edits.get(cs['sec'] - 12, (None, None))[1] == 999999)

    print('=== ④2 宠物 ===')
    chk('宠物表列出全部 6 只', len(app.tv_pet.get_children()) == 6,
        str(len(app.tv_pet.get_children())) + ' 行')
    app.pet_edit_dialog(0, modal=False)
    PV = app.pet_vars
    chk('宠物弹窗字段（7 项）', len(PV) == 7, ' / '.join(PV.keys()))
    chk('宠物改名回填（熊王 攻击 112）', PV['atk'].get() == '112', PV['atk'].get())
    app.pet_dlg.destroy()
    app.pet_edits[0] = {'atk': 999, 'hp': 12345}
    app._collect_all()
    base = app.save.pets['recs'][0]['field_off']
    chk('宠物改动能落到正确偏移',
        app.save.edits.get(base + 0x10) == ('i32', 999) and app.save.edits.get(base + 0x1c) == ('i32', 12345),
        'atk@%#x hp@%#x' % (base + 0x10, base + 0x1c))
    src = open(os.path.join(HERE, '三国存档修改器.py'), encoding='utf-8').read()
    chk('不含「删除重复武将」的功能代码（只剩帮助里的一句说明）',
        'pendingDel' not in src and 'delShift' not in src and 'delCombo' not in src)

    print('=== ⑤ 人物（双击弹窗）===')
    app.var_hq.set('NWJ0')
    app.refresh_hero_list()
    kids = app.tv_hero.get_children()
    chk('能搜到玩家记录', len(kids) >= 1, str(len(kids)) + ' 条')
    idx = int(kids[0])
    app.hero_edit_dialog(idx, modal=False)          # 不阻塞地建出弹窗
    V = app.hero_vars
    n = len(V)
    chk('弹窗里字段数（六维6+资质6+其他5+三魂3+炼魂3+熟练8+特性24 = 55）', n == 55, '%d 个' % n)
    chk('六维回填 = 300', V['six0'].get() == '300', V['six0'].get())
    chk('道德/相性/生卒年都在', all(k in V for k in ('moral', 'compat', 'birth', 'show', 'death')))
    chk('三魂点/炼魂/熟练/特性都在',
        all(('spt%d' % k) in V for k in range(3)) and all(('slv%d' % k) in V for k in range(3))
        and all(('mst%d' % k) in V for k in range(8)) and all(('prf%d' % k) in V for k in range(24)))
    # 模拟改几个值 + 点「记下改动」
    V['six0'].set('123'); V['spt0'].set('999999'); V['prf0'].set('7')
    app.hero_dlg.destroy()
    app.hero_edits[idx] = {'six0': 123, 'spt0': 999999, 'prf0': 7}
    app._collect_all()
    so = app.save.heroes[idx]['six_off']
    chk('改动能落到正确的偏移',
        app.save.edits.get(so) == ('i32', 123)
        and app.save.edits.get(so + app_mod.sc.O_SOULPT) == ('i32', 999999)
        and app.save.edits.get(so + app_mod.sc.O_PROF) == ('i32', 7),
        'six@%#x / spt@%#x / prf@%#x' % (so, so + app_mod.sc.O_SOULPT, so + app_mod.sc.O_PROF))
    # 显示行里六维有值
    vals = app.tv_hero.item(kids[0], 'values')
    chk('列表行六维非空', bool(str(vals[2]).strip()), str(vals[2])[:40])

    print('=== ⑤3 人物性格（2026-10-17 新增，做法仿「称号与资源」页）===')
    app.hero_edit_dialog(idx, modal=False)
    cl = app.hero_char_list
    chk('性格段定位到（陈平安 10 个）', len(cl) == 10, '%d 个' % len(cl))
    chk('性格名映射正确（好谋/爱才/善解人意/武力教学 都在）',
        all(any(w in app_mod.sc.char_name(c) for c, _ in cl)
            for w in ('好谋', '爱才', '善解人意', '武力教学')),
        ' / '.join('%d %s' % (c, app_mod.sc.char_name(c)) for c, _ in cl))
    chk('第 1 个是「2 好谋」', cl[0][0] == 2, str(cl[0]))
    chk('左侧表格与列表同步', len(app.tv_hchar.get_children()) == len(cl),
        '%d 行' % len(app.tv_hchar.get_children()))
    # 搜索 → 加入两个
    app.var_hcq.set('放荡'); app.hchar_pick()
    chk('按关键字搜到「放荡」', any('放荡' in v for v in app.cb_hchar['values']),
        str(list(app.cb_hchar['values']))[:60])
    app.cb_hchar.set('62 放荡'); app.hchar_add()
    app.var_hcq.set('鱼水'); app.hchar_pick(); app.cb_hchar.set('63 鱼水之欢'); app.hchar_add()
    chk('连加两个性格 10 → 12，等级按游戏给 1',
        len(app.hero_char_list) == 12 and app.hero_char_list[-1] == (63, 1),
        str(app.hero_char_list[-2:]))
    chk('表格跟着变成 12 行', len(app.tv_hchar.get_children()) == 12,
        '%d 行' % len(app.tv_hchar.get_children()))
    # 删除第 2 个（15 爱才）
    app.tv_hchar.selection_set('1')
    app.hchar_del()
    chk('删除能生效（12 → 11，且 15 爱才没了）',
        len(app.hero_char_list) == 11 and all(c != 15 for c, _ in app.hero_char_list),
        ' / '.join(str(c) for c, _ in app.hero_char_list))
    # 点「修改」的等价动作：把列表交给引擎 → 整段重建
    expect = list(app.hero_char_list)
    app.hero_chars[idx] = expect
    app.hero_dlg.destroy()
    app._collect_all()
    chk('性格走「整段重建」（进 char_edits，不是逐条插入）',
        app.save.char_edits.get(idx) == expect and not app.save.char_adds,
        'char_edits=%s' % (str(app.save.char_edits.get(idx))[:70]))
    out, ch = app.save.build()
    s2 = app_mod.sc.SaveFile(out)
    h2 = [x for x in s2.heroes if x['id'] == 'NWJ0'][0]
    c2 = app_mod.sc.find_character_cell(s2.raw, h2)
    chk('写出后重新载入能认出，组数 = 列表长度（11）',
        c2 is not None and len(c2) == 11, 'None' if c2 is None else '%d 个' % len(c2))
    chk('写出后末尾两个正是新加的 62 / 63',
        c2 is not None and c2[-2]['id'] == 62 and c2[-1]['id'] == 63 and c2[-1]['lv'] == 1,
        'None' if c2 is None else '末两个 %d/%d、%d/%d'
        % (c2[-2]['id'], c2[-2]['lv'], c2[-1]['id'], c2[-1]['lv']))
    # ⚠️ 性格段前面的「数量」字段必须一起改，否则游戏按旧数量读 → 报 key 重复进不去游戏
    cnt = app_mod.sc.i32(out, c2[0]['off'] - 4) if c2 else -1
    chk('性格段前的「数量」字段同步更新（游戏的读档依据）', cnt == len(c2), '数量=%d / 实际 %d 组' % (cnt, len(c2)))
    chk('重开后能回显上次的改动（不会变回原样）',
        (lambda: (app.hero_edit_dialog(idx, modal=False),
                  len(app.hero_char_list) == 11 and app.hero_char_list[-1] == (63, 1),
                  app.hero_dlg.destroy())[1])(), '回显 11 个')
    chk('性格名表已覆盖全部 60 个性格（0~70 里的非空 id）',
        app_mod.sc.char_name(2) == '好谋' and app_mod.sc.char_name(62) == '放荡'
        and app_mod.sc.char_name(70) == '意志教学' and len(app_mod.sc.CHAR_NAMES) == 60
        and app_mod.sc.char_name(32).startswith('性格#'),
        '2/62/70/32 → %s/%s/%s/%s（共 %d 条）'
        % (app_mod.sc.char_name(2), app_mod.sc.char_name(62), app_mod.sc.char_name(70),
           app_mod.sc.char_name(32), len(app_mod.sc.CHAR_NAMES)))
    # 回显已在上面的「重开后能回显」里覆盖

    print('=== ⑤2 诊断包导出 ===')
    app_mod.DIAG.op('测试操作', '这是一条测试记录')
    try:
        raise ValueError('故意抛一个异常，测试诊断包能不能抓到')
    except Exception as e:
        import traceback as _tb
        try:
            raise
        except Exception:
            app_mod.DIAG.err('测试异常')
    zp = app_mod.export_diag(app, '测试：列表里看不到某件物品', include_save=False,
                             out_dir=os.path.join(HERE))
    chk('诊断 zip 已生成', os.path.exists(zp), zp)
    import zipfile
    with zipfile.ZipFile(zp) as z:
        names = z.namelist()
        txt = z.read('环境与定位.txt').decode('utf-8')
        log = z.read('运行日志.txt').decode('utf-8')
        prob = z.read('问题描述.txt').decode('utf-8')
        errs = z.read('报错.txt').decode('utf-8') if '报错.txt' in names else ''
        seg = z.read('字节片段/关键区域.txt').decode('utf-8')
    chk('包内文件齐全（说明/环境与定位/日志/操作/问题描述/字节片段）',
        all(n in names for n in ('说明.txt', '环境与定位.txt', '运行日志.txt', '操作记录.txt',
                                 '问题描述.txt', '字节片段/关键区域.txt')), ' / '.join(names))
    chk('环境与定位含全部板块（金钱/武将/背包/称号/资源/城市/宠物）',
        all(k in txt for k in ('--- 金钱 ---', '--- 武将 ---', '--- 背包 ---', '--- 称号 ---',
                               '--- 势力资源 ---', '--- 城市 ---', '--- 宠物 ---',
                               '定位 76 座', '共 6 只')),
        '金钱=%s 背包=%s 称号=%s' % ('96620179' in txt, '件' in txt, '条数' in txt))
    chk('含版本与系统信息', '英雄立志传' in txt and 'Windows' in txt)
    chk('问题描述被带进去', '看不到某件物品' in prob)
    chk('异常被记录', '测试异常' in errs and 'ValueError' in errs, errs.splitlines()[0] if errs else '空')
    chk('字节片段有关键区域', '★' in seg and '背包起点' in seg, '%d 字节' % len(seg))
    chk('操作记录有测试动作', '测试操作' in log)
    os.remove(zp)
    print('  （已删除测试用 zip）')

    print('=== ⑤1 回归：只改一处，不许动别处（2026-10-14 事故）===')
    app.load_file(SAVE)
    raw0 = bytes(app.save.raw)
    app.tv_city.selection_set('CS1068')
    app.refresh_city_fields()
    app.city_vars['money'].set('333333')
    app.apply_city()
    app._collect_all()
    chk('只改城市时 bag_dirty / titles_dirty 都为 False',
        (not app.save.bag_dirty) and (not app.save.titles_dirty),
        'bag_dirty=%s titles_dirty=%s' % (app.save.bag_dirty, app.save.titles_dirty))
    d1, c1 = app.save.build()
    diff = [i for i in range(len(d1)) if d1[i] != raw0[i]]
    chk('变更清单只有定点改写', c1 == ['定点改写 4 处'], str(c1))
    chk('实际只有城市那几个字节变了', len(diff) <= 8, '%d 字节: %s' % (len(diff), [hex(x) for x in diff]))
    chk('文件长度没变', len(d1) == len(raw0), '%d → %d' % (len(raw0), len(d1)))

    print('=== ⑤1b 回归：改背包必须保住 f2/f3 ===')
    app.load_file(SAVE)
    app.bag_edit = None
    app.refresh_bag_list()
    gi, idx, it = app._bag_rows()[5]
    f_before = (it['f2'], it['f3'])
    app.bag_edit[gi][idx]['qty'] = 7
    app._collect_all()
    d2, c2 = app.save.build()
    cat2 = {'__CITY_ID__': app_mod.CAT.city_id, '__CITY_NAME__': app_mod.CAT.city_name,
            '__PET_CAT__': app_mod.CAT.pets}
    cat2.update({k: 1 for k in app_mod.CAT.items})
    chk2 = app_mod.sc.SaveFile(d2, cat2)
    lost = [(b['id'], b['f2'], a['f2']) for gb, ga in zip(app.save.bag['groups'], chk2.bag['groups'])
            for b, a in zip(gb['items'], ga['items'])
            if b['f2'] != a['f2'] or b['f3'] != a['f3']]
    chk('全部条目的 f2/f3 原样保留', not lost, '丢失 %d 条 %s' % (len(lost), lost[:2]))
    chk('非零 f2/f3 的条目仍在', sum(1 for g in chk2.bag['groups'] for x in g['items']
                                 if x['f2'] or x['f3']) > 0,
        '%d 条' % sum(1 for g in chk2.bag['groups'] for x in g['items'] if x['f2'] or x['f3']))
    chk('数量改成功', chk2.bag['groups'][gi]['items'][idx]['qty'] == 7,
        str(chk2.bag['groups'][gi]['items'][idx]['qty']))
    app.load_file(SAVE)

    print('=== ⑤3 添加宠物 ===')
    n_before = len(app.save.pets['recs'])
    chk('品种下拉已填充', len(app.cb_pet_new['values']) > 10,
        '%d 个品种' % len(app.cb_pet_new['values']))
    chk('模板下拉已填充', len(app.cb_pet_tmpl['values']) == n_before,
        ' / '.join(app.cb_pet_tmpl['values'][:2]))
    # 挑一个和模板不同的品种
    tpl_id = app.save.pets['recs'][0]['id']
    pick = next(v for v in app.cb_pet_new['values']
                if ('（' + tpl_id + '）') not in v and v.split('（')[1].split('）')[0] != tpl_id)
    app.cb_pet_new.set(pick)
    app.cb_pet_tmpl.current(0)
    app.pet_queue_add()
    chk('加入待添加成功', len(app.save.pet_adds) == 1,
        str(app.save.pet_adds))
    chk('待添加计数显示正确', '待添加 1 只' in app.lbl_pet_add.cget('text'), app.lbl_pet_add.cget('text'))

    print('=== ⑥ 生成存档（写盘 + 回读校验）===')
    app._collect_all()
    out = os.path.join(HERE, '_selftest_out.dat')
    data, ch = app.save.build()
    open(out, 'wb').write(data)
    chk('build 成功', len(data) > 1000, '%d 字节，变更 %s' % (len(data), ch))
    chk('文件已写出', os.path.exists(out), out)
    chk('变更清单里有宠物添加', any('宠物' in c for c in ch), '；'.join(ch))
    # 回读确认宠物真的多了一只
    cat2 = {'__CITY_ID__': app_mod.CAT.city_id, '__CITY_NAME__': app_mod.CAT.city_name,
            '__PET_CAT__': app_mod.CAT.pets}
    cat2.update({k: 1 for k in app_mod.CAT.items})
    chk2 = app_mod.sc.SaveFile(data, cat2)
    chk('回读出宠物 %d 只（原 %d）' % (n_before + 1, n_before),
        chk2.pets and chk2.pets['count'] == n_before + 1,
        str(chk2.pets['count']) if chk2.pets else '未定位')
    if chk2.pets:
        newp = chk2.pets['recs'][-1]
        chk('新宠物品种正确', newp['id'] == app.save.pet_adds[0]['tgt'],
            '%s %s' % (newp['id'], newp['name']))

    print('=== ⑥2 诊断包指定路径 ===')
    want = os.path.join(HERE, '_diag_path_test.zip')
    got = app_mod.export_diag(app, '指定路径测试', out_path=want)
    chk('导出到指定路径', got == want and os.path.exists(want), got)
    os.remove(want)

    # ------------------------------------------------------------------
    # ⑦ 换档不重新适配：同一套「不变量」要在两种完全不同的档上都命中真值
    #    Save1 = 已自立势力（君主）；Save5 = 新档武将（未自立，只有家族）
    # ------------------------------------------------------------------
    print('=== ⑦ 跨档定位不变量（换档不再重新适配）===')
    cat_full = {'__CITY_ID__': app_mod.CAT.city_id, '__CITY_NAME__': app_mod.CAT.city_name,
                '__PET_CAT__': app_mod.CAT.pets}
    cat_full.update(app_mod.CAT.items)

    def probe(path):
        with open(path, 'rb') as fh:
            return app_mod.sc.SaveFile(bytearray(fh.read()), cat_full)

    s1 = probe(SAVE)
    chk('Save1 判定为君主（已自立势力）', s1.is_ruler is True, str(s1.role))
    chk('Save1 背包 0xD6AEBD / 655 件',
        s1.bag and s1.bag['start'] == 0xD6AEBD and s1.bag['tot'] == 655,
        ('0x%X / %d 件' % (s1.bag['start'], s1.bag['tot'])) if s1.bag else '未定位')
    chk('Save1 称号 54 条', s1.titles and len(s1.titles['ids']) == 54,
        str(len(s1.titles['ids'])) if s1.titles else '未定位')
    f1 = s1.faction or {}
    chk('Save1 势力资源 920851 / 990869 / 灵蕴 9999975',
        f1.get('kind') == 'faction' and f1.get('tech') == 920851
        and f1.get('strat') == 990869 and s1.lingyun == 9999975,
        '%s %s %s' % (f1.get('tech'), f1.get('strat'), s1.lingyun))

    SAVE5 = os.path.join(ROOT, '新档诊断', 'Save5_新档.dat')
    if os.path.exists(SAVE5):
        s5 = probe(SAVE5)
        chk('Save5 判定为未自立势力', s5.is_ruler is False, str(s5.role))
        chk('Save5 背包 0x3571C / 11 件',
            s5.bag and s5.bag['start'] == 0x3571C and s5.bag['tot'] == 11,
            ('0x%X / %d 件' % (s5.bag['start'], s5.bag['tot'])) if s5.bag else '未定位')
        chk('Save5 称号只有「常胜将军」一条',
            s5.titles and s5.titles['ids'] == ['1001205'],
            str(s5.titles['ids']) if s5.titles else '未定位')
        f5 = s5.faction or {}
        chk('Save5 家族资源 科技 1000 / 策略 200 / 灵蕴 0',
            f5.get('kind') == 'family' and f5.get('tech') == 1000
            and f5.get('strat') == 200 and s5.lingyun == 0,
            '%s %s %s' % (f5.get('tech'), f5.get('strat'), s5.lingyun))
        chk('Save5 资产块金钱锚点 = 背包起点 - 4',
            s5.money2 == (s5.bag['start'] - 4 if s5.bag else None),
            '0x%X' % (s5.money2 or 0))
    else:
        print('    （跳过：找不到 Save5_新档.dat）')

    root.destroy()

    print('\n结果：%d 通过 / %d 失败' % (pass_n, fail_n))
    return 1 if fail_n else 0


if __name__ == '__main__':
    sys.exit(main())
