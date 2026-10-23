# -*- coding: utf-8 -*-
"""引擎自测：拿真值核对 Python 移植版是否与 HTML 版结果一致。"""
import io
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import savecore as sc

CAT = os.path.join(ROOT, '存档修改器', '物品库.js')
SAVE = os.path.join(ROOT, '势力资源', 'Save1_1014_基准.dat')


def load_catalog():
    src = io.open(CAT, encoding='utf-8').read()
    out = {}
    for key in ('CITY_ID', 'CITY_NAME', 'ITEM_CAT'):
        i = src.find('window.%s=' % key)
        if i < 0: continue
        i += len('window.%s=' % key)
        j = src.find(';\n', i)
        out[key] = json.loads(src[i:j])
    return out


def main():
    cat = load_catalog()
    print('物品库：ITEM_CAT %d 条，城市 %d 座' % (len(cat['ITEM_CAT']), len(cat['CITY_ID'])))
    data = open(SAVE, 'rb').read()
    t0 = time.time()
    s = sc.SaveFile(data, {'__CITY_ID__': cat['CITY_ID'], '__CITY_NAME__': cat['CITY_NAME'],
                           **{k: 1 for k in cat['ITEM_CAT']}})
    t1 = time.time()
    print('解析耗时 %.2fs' % (t1 - t0))
    print('版本戳 %d  槽位 %d  当前地点 %s' % (s.ver, s.slot, s.place))
    print('金钱 %d（期望 96620179）  副本 %s' % (s.money, [hex(x) for x in s.money_copies]))
    f = s.faction or {}
    print('科技 %s（期望 920851）  策略 %s（期望 990869）  国库 %s（期望 8402291）'
          % (f.get('tech'), f.get('strat'), f.get('treasury')))
    print('  偏移 科技@%s 策略@%s 国库@%s'
          % (hex(f.get('tech_off', 0)), hex(f.get('strat_off', 0)), hex(f.get('treasury_off', 0))))
    print('武将 %d 条（首位 %s / %s）' % (len(s.heroes), s.heroes[0]['id'], s.heroes[0].get('preset')))
    if s.bag:
        g = s.bag['groups']
        print('背包 @%#x  共 %d 件  各组 %s' % (s.bag['start'], sum(len(x['items']) for x in g),
                                              ' '.join('%d:%d' % (i, len(x['items'])) for i, x in enumerate(g))))
        print('  组12（货物）前 3 件：%s' % ' '.join(x['id'] for x in g[12]['items'][:3]))
    else:
        print('背包：未定位 ✗')
    print('称号列表 %s' % (('@%#x %d 条：%s' % (s.titles['count_off'], len(s.titles['ids']),
                                            ' '.join(s.titles['ids'][:5]))) if s.titles else '未定位 ✗'))
    cs = s.cities.get('CS1068')
    print('百济 CS1068：%s' % ({'资金': 237285, '实际': cs and cs['money']} if not cs else
                              '资金 %d（期望 237285） 军粮 %d（期望 1962765） 人口 %d 治安 %.1f'
                              % (cs['money'], cs['food'], cs['pop'], cs['security'])))
    print('城市定位 %d / 76' % len(s.cities))
    # 试改一处：金钱 +1 并回读
    if s.money_off >= 0:
        s.edits[s.money_off] = ('i32', 96620179 + 1)
        out, ch = s.build()
        print('build 测试：%d → %d 字节，变更 %s' % (len(data), len(out), ch))
        chk = sc.SaveFile(out, {'__CITY_ID__': cat['CITY_ID'], '__CITY_NAME__': cat['CITY_NAME'],
                                **{k: 1 for k in cat['ITEM_CAT']}})
        print('  回读金钱 %d（期望 96620180）' % chk.money)


if __name__ == '__main__':
    main()
