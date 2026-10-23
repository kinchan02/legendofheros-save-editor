# -*- coding: utf-8 -*-
"""更新物品库.js —— 三国存档修改器的物品/称号数据库再生成工具

用法:
    python update_item_catalog.py [游戏根目录] [输出.js]

    游戏根目录 = 包含 ThreeKingdom_Data 的那层目录
    （默认: F:\\BaiduNetdiskDownload\\LegendOfHeros\\LegendOfHeros）
    输出.js   = 物品库.js 的写出路径
    （默认: F:\\WB\\2026-10-07-16-23-32\\存档修改器\\物品库.js）

做什么:
    1. 读主游戏 Json 目录的 Equipment/Drug/Book/Ci_Building/Ci_City 与魂技称号七张表，
       生成 id -> [名称,分类,推荐组,等级,价格,简述(,魂占用)]；
    2. **宠物单独一张清单**：读 Animal.json（主表 + MODs + MODProjects），
       生成 id -> [名称,英/繁/韩名,图标(族),type,等级上限,月饲养费,价值,攻/防/速/血,是否MOD]。
       宠物不是背包物品，所以不进 ITEM_CAT，单独放 window.PET_CAT。
    3. 遍历 MODs\\ 下所有 MOD 子目录，把「同名表」里主库没有的 id 合并进来
       （分类标注 MOD；称号自动加 HTC 前缀，其余按表内原 id）；
    4. 再遍历 MODProjects\\（TKEditor 的 MOD 工程目录，未导出的源），只补前两者没有的 id；
    5. 按背包条目 ID 规则过滤不合格 ID，写 _被剔除的ID.txt；
    6. 生成 物品库.js（window.CITY_ID / CITY_NAME / GRP_LABEL / ITEM_CAT / PET_CAT）。

什么时候跑:
    装了新 MOD、游戏更新了数据表、或修改器里搜不到某个物品/称号/宠物时。
    跑完用 node --check 校验一下产物语法即可。
"""
import json, os, re, sys, collections

DEFAULT_GAME = r'E:\SteamLibrary\steamapps\common\LegendOfHeros'
DEFAULT_OUT  = r'F:\WB\2026-10-07-16-23-32\存档修改器\物品库.js'
DROP_NAME    = '_被剔除的ID.txt'

GAME_ROOT = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_GAME
OUT       = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_OUT
JSON_DIR  = os.path.join(GAME_ROOT, 'ThreeKingdom_Data', 'StreamingAssets', 'Json')
MOD_DIR   = os.path.join(GAME_ROOT, 'MODs')
PROJ_DIR  = os.path.join(GAME_ROOT, 'MODProjects')   # TKEditor 的 MOD 工程目录（未导出的源）
DROP_PATH = os.path.join(os.path.dirname(OUT), DROP_NAME)

def load_json(path):
    try:
        return json.loads(open(path, encoding='utf-8').read(), strict=False)
    except Exception as e:
        print('  [warn] 读取失败:', path, e)
        return []

# equipType -> 背包组（2026-10-10 用 21 个存档实测校正）
#   0武器 1防具 2佩饰 3坐骑 4头盔 7盾牌 6礼物珍玩 —— 全部实测确认
#   5 = 任务/剧情道具（霸者之符、太平神符、春秋、兵法、战国策、县令的遗物…），
#       实测出现在组 9（与丹药符箓同页）；组 6 实测为空、不是它该去的地方。
EQ_GROUP = {'0': 0, '1': 1, '2': 2, '3': 3, '4': 4, '5': 9, '6': 7, '7': 5}
EQ_KIND  = {'0':'武器', '1':'防具', '2':'佩饰', '3':'坐骑', '4':'头盔',
            '5':'任务道具', '6':'礼物珍玩', '7':'盾牌'}
EQ_LABEL = {0:'武器',1:'防具',2:'佩饰',3:'坐骑',4:'头盔',5:'盾牌',6:'特殊/书籍',7:'礼物珍玩'}

def drug_group(t):
    """Drug.json 的 type -> 背包组（2026-10-10 实测校正）
       0酒 / 1药 / 2食物 / 3精要启示录 / 15录术手抄        -> 组 9（丹药符箓）
       4地图碎片 / 5地图 / 6藏宝图                          -> 组 6（地图，待游戏内复核）
       19~32 铁/布/玉石/茶/肉/盐/药草/香/瓷/漆/纸笔/粮食   -> 组 12（材料）"""
    t = str(t)
    if t in ('0','1','2','3','15'): return 9
    if t in ('4','5','6'): return 6
    return 12

# ---- 各表的处理函数: (records, is_mod, items) ----
def h_equipment(xs, mod, items):
    for x in xs:
        i = str(x.get('id',''))
        if not i or (mod and i in items): continue
        et = str(x.get('equipType',''))
        g = EQ_GROUP.get(et, 6)
        kind = EQ_KIND.get(et, '装备')
        items[i] = [x.get('name',''), ('MOD'+kind) if mod else kind, g,
                    str(x.get('level','')), str(x.get('price','')),
                    ('MOD'+kind) if mod else kind]
        # ---- 制造书：装备表里 forgeUnlockType=1 的「需要制造书解锁」装备 ----
        # 存档里的 ID 是代码生成的 `FORGEWP` + 装备编号去掉前缀（WP1012005 → FORGEWP1012005）。
        # 2026-10-13 在玩家存档里实测确认（山纹银狮甲 制造书）。
        # 制造书价格 = 装备价 ÷ 4（实测 18000→4500；128 条 ft=1 的价格全部能被 4 整除），
        # 等级沿用装备等级（3=传奇）。
        # MOD 装备的编号可能带字母（WP10001ouia1 → FORGEWP10001ouia1），同样按「去掉 WP 前缀」处理，
        # 这样 MOD 里把某件装备改成 forgeUnlockType=1 后，跑一次本脚本就能自动带上它的制造书。
        if str(x.get('forgeUnlockType','')) == '1' and i[:2] == 'WP' and len(i) > 2:
            num = i[2:]
            try: pr = int(x.get('price') or 0) // 4
            except Exception: pr = 0
            key = 'FORGEWP' + num
            if key not in items:
                lab = 'MOD制造书' if mod else '制造书'
                items[key] = [x.get('name',''), lab, 9,
                              str(x.get('level','')), str(pr),
                              lab + '（打造「' + x.get('name','') + '」的配方）']

def h_drug(xs, mod, items):
    for x in xs:
        i = str(x.get('id',''))
        if not i or (mod and i in items): continue
        t = str(x.get('type',''))
        g = drug_group(t)
        lab = {9:'丹药符箓', 6:'地图藏宝图', 12:'材料'}.get(g,'材料')
        items[i] = [x.get('name',''), ('MOD'+lab) if mod else lab, g,
                    str(x.get('level','')), str(x.get('price','')),
                    ('MOD'+lab) if mod else lab]

def h_topic(xs, mod, items):
    """话题（交谈时用的谈资，Topic.json，HT 前缀）——实测在背包组 10"""
    for x in xs:
        i = str(x.get('id',''))
        if not i or (mod and i in items): continue
        items[i] = [x.get('name',''), 'MOD话题' if mod else '话题', 10,
                    str(x.get('level','')), str(x.get('value','')),
                    'MOD话题' if mod else '话题']

def h_book(xs, mod, items):
    for x in xs:
        i = str(x.get('id',''))
        if not i or (mod and i in items): continue
        items[i] = [x.get('name',''), '书籍', 8, str(x.get('level','')),
                    str(x.get('price','')), 'MOD书籍' if mod else '书籍']

def _pair(v):
    """Animal.json 的数值字段形如 '27/30'（低/高）—— 返回 (lo, hi)"""
    s = str(v if v is not None else '')
    if '/' in s:
        a, b = s.split('/', 1)
        try: return int(float(a)), int(float(b))
        except Exception: return 0, 0
    try:
        n = int(float(s)); return n, n
    except Exception:
        return 0, 0

def h_animal(xs, mod, pets):
    """宠物（Animal.json，P 前缀）—— **不是背包物品**，单独出 PET_CAT。
       条目：[名称, 英文名, 繁中名, 韩文名, 图标(族), type,
              等级上限, 月饲养费, 价值, 攻击, 防御, 速度, 生命, 是否MOD]
       其中「图标(族)」对应存档记录里的那一段字符串（白狼王=白狼、熊王=熊…）。"""
    for x in xs:
        i = str(x.get('id',''))
        if not i or (mod and i in pets): continue
        alo, ahi = _pair(x.get('attackVal'))
        dlo, dhi = _pair(x.get('defenceVal'))
        slo, shi = _pair(x.get('speed'))
        hlo, hhi = _pair(x.get('hp'))
        pets[i] = [x.get('name',''), x.get('nameEn',''), x.get('nameTc',''),
                   x.get('nameKr',''), str(x.get('icon','')), str(x.get('type','')),
                   str(x.get('levelLimit','')), str(x.get('monthCost','')),
                   str(x.get('value','')), ahi, dhi, shi, hhi, 1 if mod else 0]

def h_building(xs, mod, items):
    for x in xs:
        i = str(x.get('id',''))
        if not i or (mod and i in items): continue
        items[i] = [x.get('name',''), '建筑', 12, '', '', 'MOD建筑' if mod else '建筑']

def _tagged(tag, label, g):
    def h(xs, mod, items):
        for x in xs:
            i = str(x.get('id',''))
            if not i or (mod and (tag + i) in items): continue
            sp = x.get('soulPoint', -1)
            try: sp = int(sp)
            except Exception: sp = -1
            val = x.get('value', '')
            if val is None: val = ''
            items.setdefault(tag + i, [x.get('name',''),
                                       'MOD' + label if mod else label, g,
                                       str(x.get('level','')), str(val),
                                       'MOD' + label if mod else label, sp])
    return h

def h_title(xs, mod, items):
    """称号 → 游戏里叫「称号证书」（背包里那群可叠加的凭证，使用后获得同名称号）。
       条目追加 [7]=效果描述(简体), [8]=专属人物(remark)，供修改器悬停提示用。
       价格：HeroTitle.json 里没有 value 字段，游戏是按等级定价的
             （2026-10-13 小K 游戏内实测：4 级「天下极策」价值 10000），
             这里按 等级 × 2500 推算（1 级 2500 … 4 级 10000）。"""
    for x in xs:
        i = str(x.get('id',''))
        if not i or (mod and ('HTC' + i) in items): continue
        sp = x.get('soulPoint', -1)
        try: sp = int(sp)
        except Exception: sp = -1
        try: lv = int(x.get('level', 0) or 0)
        except Exception: lv = 0
        val = str(lv * 2500) if lv else ''
        desc = (x.get('description') or '').strip()
        remark = (x.get('remark') or '').strip()
        lab = 'MOD称号证书' if mod else '称号证书'
        items.setdefault('HTC' + i, [x.get('name',''), lab, 9,
                                     str(x.get('level','')), val,
                                     lab + '（使用后获得同名称号）', sp,
                                     desc, remark])

# 文件名 -> 处理函数（MOD 合并按同名文件匹配；新 MOD 若带新表名，在这里补一行即可）
TABLES = {
    'Equipment.json':      h_equipment,
    'Drug.json':           h_drug,
    'Book.json':           h_book,
    'Animal.json':         h_animal,
    'Ci_Building.json':    h_building,
    # 2026-10-10 小K 指正 + 数据核对：War* = 军团战（军），F* = 武斗（武）。
    #   依据：HeroWarSoul.json 内首条名字就是「***军魂数据规则***」。
    'HeroBattleSoul.json': _tagged('FSoul',    '武魂', 11),   # 武斗·魂
    'HeroBattleCard.json': _tagged('FCard',    '武技', 11),   # 武斗·技
    'HeroWarSoul.json':    _tagged('WarSoul',  '军魂', 11),   # 军团战·魂
    'HeroWarSkill.json':   _tagged('WarSkill', '军技', 11),   # 军团战·技
    'HeroDebateSoul.json': _tagged('DSoul',    '智魂', 11),
    'HeroDebateCard.json': _tagged('DCard',    '智技', 11),
    'HeroTitle.json':      h_title,
    'Topic.json':          h_topic,
}

def main():
    items = {}
    pets  = {}
    tgt = lambda fn: (pets if fn == 'Animal.json' else items)
    print('== 主游戏数据 ==', JSON_DIR)
    for fn, h in TABLES.items():
        p = os.path.join(JSON_DIR, fn)
        if not os.path.exists(p):
            print('  [skip] 无', fn); continue
        xs = load_json(p)
        h(xs, False, tgt(fn))
        print('  %-22s %4d 条' % (fn, len(xs)))

    n_base = len(items)
    print('== MOD 合并 ==', MOD_DIR)
    if os.path.isdir(MOD_DIR):
        for root, dirs, files in os.walk(MOD_DIR):
            for fn in sorted(files):
                if fn not in TABLES: continue
                xs = load_json(os.path.join(root, fn))
                before = len(tgt(fn))
                TABLES[fn](xs, True, tgt(fn))
                add = len(tgt(fn)) - before
                if xs: print('  %s\\%s: %d 条，新增 %d' % (os.path.basename(root), fn, len(xs), add))

    # TKEditor 的 MOD 工程目录：里面放的是「全量表」（主表 + 该 MOD 的新增），
    # 所以只补前面主库 / MODs 都没有的 id，不会把已有条目覆盖成 MOD 版。
    n_mod = len(items)
    print('== MOD 工程目录合并 ==', PROJ_DIR)
    if os.path.isdir(PROJ_DIR):
        for root, dirs, files in os.walk(PROJ_DIR):
            for fn in sorted(files):
                if fn not in TABLES: continue
                xs = load_json(os.path.join(root, fn))
                before = len(tgt(fn))
                TABLES[fn](xs, True, tgt(fn))
                add = len(tgt(fn)) - before
                if add: print('  %s\\%s: %d 条，新增 %d' % (os.path.basename(root), fn, len(xs), add))
    print('主库 %d 条 -> MODs 后 %d 条 -> 工程目录后 %d 条' % (n_base, n_mod, len(items)))
    print('宠物 %d 条（含 MOD %d 条）' % (len(pets), sum(1 for v in pets.values() if len(v) > 13 and v[13])))

    # ---- 过滤：只保留符合背包条目读取规则的 ID ----
    BAGID = re.compile(r'^[A-Za-z]{1,9}[0-9]{2,9}[A-Za-z0-9_]{0,7}$')
    bad = []
    for k in list(items.keys()):
        if not (4 <= len(k) <= 40) or not BAGID.match(k):
            bad.append((k, items[k][0], items[k][1]))
            del items[k]
    if bad:
        with open(DROP_PATH, 'w', encoding='utf-8') as f:
            f.write('以下 ID 不符合背包条目规则（长度/格式），不能作为背包物品写入，已从物品库剔除：\n')
            for k, n, c in bad: f.write('%s\t%s\t%s\n' % (k, n, c))
        print('剔除不合格 ID %d 条（清单见 %s）' % (len(bad), DROP_PATH))
        for k, n, c in bad[:20]: print('   ', k, n, c)
    print('过滤后物品库条目:', len(items))
    c = collections.Counter(v[2] for v in items.values())
    print('按分类分布:', dict(sorted(c.items())))

    GRP_LABEL = {0:'武器',1:'防具',2:'佩饰',3:'坐骑',4:'头盔',5:'盾牌',6:'任务道具/特殊',
                 7:'礼物珍玩',8:'书籍',9:'称号/丹药符箓/制造书',10:'话题',
                 11:'魂与技（军/武/智）',12:'材料物资'}

    CITY_ID = {}
    for x in load_json(os.path.join(JSON_DIR, 'Ci_City.json')):
        nm, i = x.get('name',''), str(x.get('id',''))
        if nm and i: CITY_ID[nm] = i

    js  = 'window.CITY_ID='   + json.dumps(CITY_ID, ensure_ascii=False, separators=(',',':')) + ';\n'
    js += 'window.CITY_NAME=' + json.dumps({v:k for k,v in CITY_ID.items()}, ensure_ascii=False, separators=(',',':')) + ';\n'
    js += 'window.GRP_LABEL=' + json.dumps(GRP_LABEL, ensure_ascii=False) + ';\n'
    js += 'window.ITEM_CAT='  + json.dumps(items, ensure_ascii=False, separators=(',',':')) + ';\n'
    js += '/* PET_CAT：宠物品种清单（来自 Animal.json + MODs/MODProjects）。\n'
    js += '   条目 = [名称, 英文名, 繁中名, 韩文名, 图标(族), type, 等级上限, 月饲养费,\n'
    js += '           价值, 攻击, 防御, 速度, 生命, 是否MOD] —— 宠物不是背包物品，不进 ITEM_CAT。 */\n'
    js += 'window.PET_CAT='   + json.dumps(pets, ensure_ascii=False, separators=(',',':')) + ';\n'
    open(OUT, 'w', encoding='utf-8').write(js)
    print('已写出', OUT, os.path.getsize(OUT), '字节')
    htc = [k for k in items if k.startswith('HTC')]
    print('其中称号 %d 条 / 宠物品种 %d 条' % (len(htc), len(pets)))

if __name__ == '__main__':
    main()
