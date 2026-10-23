# -*- coding: utf-8 -*-
"""savecore.py —— 三国存档修改器 · 存档读写引擎（纯 Python 重写版）

把原来 HTML 版里的逆向成果用 Python 重写一遍，供原生界面（Tkinter）调用，
不再依赖浏览器。包含：
  · 存档头部解析（版本戳 / 槽位 / 头部字符串 / 金钱）
  · 武将记录扫描（主表 + 玩家自建记录）、六维块定位、资质块
  · 背包：13 个分类容器的定位 / 读写 / 重建
  · 称号列表：定位 / 增删改 / 重建
  · 势力资源：金钱 / 科技点 / 策略点 / 国库金
  · 城市：76 座城的 资金 / 军粮 / 人口 / 治安
  · build()：把所有改动一次性写回并做回读校验

所有偏移都按「结构定位」，不写死固定地址；规则与 HTML 版一致（2026-10-14 版）。
"""
import bisect
import re
import struct

# ---------------------------------------------------------------- 基础读写
def i32(b, o):  return struct.unpack_from('<i', b, o)[0]
def u32(b, o):  return struct.unpack_from('<I', b, o)[0]
def i16(b, o):  return struct.unpack_from('<h', b, o)[0]
def f32(b, o):  return struct.unpack_from('<f', b, o)[0]
def put_i32(b, o, v): struct.pack_into('<i', b, o, int(v))
def put_u8(b, o, v):  b[o] = int(v) & 255
def put_f32(b, o, v): struct.pack_into('<f', b, o, float(v))


def dec(b, s, e):
    """严格 utf-8 解码，失败返回 None。"""
    try:
        return bytes(b[s:e]).decode('utf-8')
    except Exception:
        return None


# 背包 / 物品 ID 规则（2026-10-14 最终版：首字符字母 + 其余字母数字下划线 + 长度 3~40 + 至少含一个数字）
ID_RE = re.compile(r'^(?=[A-Za-z0-9_]*[0-9])[A-Za-z][A-Za-z0-9_]{2,39}$')
TID_RE = re.compile(r'^\d{7}$|^\d{4,}[a-z]{2,}[\da-z]*$')
NAME_RE = re.compile(r'^[\u3400-\u9fff]{2,8}$')
JZ_RE = re.compile(r'^JZ\d{4,6}(_\d+)?$')
CITY_ID_RE = re.compile(r'^[A-Za-z]{1,5}[0-9]{1,9}[0-9A-Za-z_]{0,7}$')

# 资质块内的偏移
O_MORAL, O_COMPAT, O_BIRTH, O_SHOW, O_DEATH = 0x44, 0x4C, 0x51, 0x55, 0x59
# 六维块内的偏移
O_SOULPT, O_SOULLV, O_MASTER, O_PROF = 24, 36, 48, 80

BAG_NGRP = 13
BAG_MAX_ITEMS = 3000

LAB_SIX = ['统率', '武力', '智略', '政略', '魅力', '意志']
LAB_TAL = ['统率资质', '武力资质', '智略资质', '政略资质', '魅力资质', '意志资质']

# ---------------------------------------------------------------- 性格
# 性格在存档里是武将记录内的一串「(i32 性格id, i32 等级)」对，8~12 组，等级 0~3。
# 下面这些是**已确认**的 id↔名称（名称按游戏界面现行文案；括号里是游戏事件对话里的旧写法）：
#   1 好武 / 2 好谋 / 3 好酒 / 4 厌酒 / 5 好色 / 6 享乐 / 7 好财宝（旧：好宝物） / 8 好书籍
#   9 好马匹 / 10 好武具（旧：武具） / 11 好奇 / 12 感恩 / 13 淡漠 / 14 记仇 / 15 爱才
#   16 傲慢 / 17 善妒 / 18 执见（旧：执着） / 19 无主见（旧：随性） / 20 浪漫
#   21 惠民（旧：爱民） / 22 制民（旧：残忍） / 23 包容 / 24 苛刻 / 25 好攻
#   43 善交 / 47 善解人意 / 63 鱼水之欢 / 66 武力教学
#   + 用马隆（WJ1032715）的性格面板逐项对照确认的：0 好兵 / 27 公正 / 30 好战主义 /
#     31 重正邪 / 33 重声望 / 38 热忱 / 44 励志 / 57 好防具 / 65 统率教学
#   + 用小乔（WJ10024）的性格面板确认的：36 重貌 / 39 广交 / 41 真挚 / 45 好游 /
#     49 温柔体贴 / 58 好衣物
# 依据：游戏「解锁你的XX」事件对话的 character 字段、MOD「大虎鞭→鱼水之欢」事件、
#       以及用小K 提供的角色性格面板（马隆 / 陈平安）与存档 id 顺序逐项对照
#       （面板顺序 == 存档顺序，已多次验证）。
# 其余 id（26 / 28 / 29 / 32 / 34 / 36 / 37 / 39~42 / 45 / 46 / 48~62 / 67~69 / 79 / 80）
# **尚未确认，一律显示「性格#id」，不猜名字**。
CHAR_NAMES = {
    0: '好兵', 1: '好武', 2: '好谋', 3: '好酒', 4: '厌酒', 5: '好色', 6: '享乐',
    7: '好财宝', 8: '好书籍', 9: '好马匹', 10: '好武具', 11: '好奇', 12: '感恩',
    13: '淡漠', 14: '记仇', 15: '爱才', 16: '傲慢', 17: '善妒', 18: '执见',
    19: '无主见', 20: '浪漫', 21: '惠民', 22: '制民', 23: '包容', 24: '苛刻',
    25: '好攻', 26: '好守', 27: '公正', 28: '贪婪', 29: '和平主义', 30: '好战主义',
    31: '重正邪', 33: '重声望', 36: '重貌', 37: '内敛', 38: '热忱', 39: '广交',
    40: '慎交', 41: '真挚', 42: '好政', 43: '善交', 44: '励志', 45: '好游',
    46: '爱财', 47: '善解人意', 48: '动若脱兔', 49: '温柔体贴', 57: '好防具',
    58: '好衣物', 59: '无欲', 60: '静若处子', 61: '巾帼英姿', 62: '放荡',
    63: '鱼水之欢', 65: '统率教学', 66: '武力教学', 67: '智略教学', 68: '政略教学',
    69: '魅力教学', 70: '意志教学',
}
CHAR_MAX_LV = 3


def char_name(cid):
    """性格 id -> 名称（没对上的返回 性格#id）。"""
    try:
        cid = int(cid)
    except Exception:
        return str(cid)
    return CHAR_NAMES.get(cid) or ('性格#%d' % cid)


def ser_char_list(pairs):
    """[(性格id, 等级), ...] -> 字节（和称号列表一样整段重建）。"""
    return b''.join(struct.pack('<ii', int(a), int(b)) for a, b in pairs)


def find_character_cell(b, h):
    """武将记录内的性格列表。

    【不变量】从记录起点按 4 字节对齐扫，**第一段**满足下面三条的就是性格列表：
      ① 连续 >=4 组 `(i32 性格id, i32 等级)`，id ∈ 0..90、等级 ∈ 0..3；
      ② **id 互不重复**（一个人不会有两种一样的性格）；
      ③ 至少有 1 组等级 > 0。
    实测：单经只有 6 个性格（59/1 1/1 0/1 26/1 39/1 33/1，@anc+153），
    若按「>=8 组」筛选会跳过真段、命中后面 id 重复的假段（教训）。曹操 12 组与
    Hero.json 完全一致；孙谦 9 组与面板 9 个一一对应。
    返回 [{'off': 偏移, 'id': 性格id, 'lv': 等级}, ...] 或 None。
    """
    if 'char_cell' in h:
        return h['char_cell']
    lo = h['anc']
    # 玩家记录的 end 只到下一个武将开头（太窄），所以至少往下搜 0x400 字节；
    # 性格段实测在 anc+153~156 处，0x4000 上限足够且能避免扫进别的武将。
    hi = min(max(h.get('end') or 0, lo + 0x400), lo + 0x4000, len(b))
    p = lo
    while p + 8 <= hi:
        q, run = p, []
        while q + 8 <= hi:
            cid, lv = struct.unpack_from('<ii', b, q)
            if 0 <= cid <= 90 and 0 <= lv <= CHAR_MAX_LV:
                run.append({'off': q, 'id': cid, 'lv': lv})
                q += 8
            else:
                break
        ids = [r['id'] for r in run]
        if len(run) >= 4 and len(set(ids)) == len(ids) and any(r['lv'] for r in run):
            h['char_cell'] = run          # 缓存进 hero，界面/写回都复用它
            return run
        p = q if len(run) >= 4 else p + 1
    h['char_cell'] = None                 # 找过了但没找到，也记下来
    return None


# ---------------------------------------------------------------- 头部
def header_strings(b, limit=0x200):
    """头部按 字符串 / i32 / f32 启发式前进，收集字符串序列。"""
    out, p = [], 8
    while p < limit and p + 1 < len(b):
        L = b[p]
        if 2 < L < 60 and p + 1 + L <= len(b):
            s = dec(b, p + 1, p + 1 + L)
            if s and s.isprintable():
                out.append((p, s))
                p += 1 + L
                continue
        v = i32(b, p)
        p += 4 if (-100000 <= v <= 200000000) else 4
    return out


def loc_money(b):
    """头部金钱偏移：跳两个 [len]str + 两个 i32 之后。"""
    p = 8
    if p >= len(b): return -1
    l1 = b[p]
    if not (1 <= l1 <= 60): return -1
    p += 1 + l1 + 4
    if p >= len(b): return -1
    l2 = b[p]
    if not (1 <= l2 <= 60): return -1
    p += 1 + l2 + 4
    return p if p + 4 <= len(b) else -1


def money_copies(b):
    off = loc_money(b)
    if off < 0: return off, 0, []
    v = i32(b, off)
    copies = [off]
    if 0 < v <= 2000000000:
        pat = struct.pack('<i', v)
        i = off + 4
        while len(copies) < 8:
            i = bytes(b).find(pat, i)
            if i < 0: break
            copies.append(i)
            i += 1
    return off, v, copies


# 身份字段：头部前若干串里出现「君主」= 已自立势力；否则是武将/在野（只有家族）
ROLE_RULER = '君主'


def player_role(b):
    """返回头部里的身份串（'君主' / '一般' / None）。

    规律：存档头部是一串 [len]字符串，其中第 5 个就是玩家身份。
      君主档：…'陈平安','邪马台','陈平安','君主',…
      新档  ：…'赵云','江陵','刘备','一般',…
    只有身份为「君主」时存档里才有势力科技/策略点与国库金；否则只有家族资源。
    """
    try:
        hs = header_strings(b, limit=0x300)
    except Exception:
        return None
    for _, s in hs[:12]:
        if s in ('君主', '一般', '在野', '武将', '太守', '军师', '都督', '州牧'):
            return s
    return None


def player_is_ruler(b):
    return player_role(b) == ROLE_RULER


# ---------------------------------------------------------------- 武将
def _tal_ok(b, tal_off):
    """资质块的强约束（和 HTML 版一致）。"""
    if tal_off + 0x60 > len(b) or tal_off < 2: return None
    tal = [i32(b, tal_off + j * 4) for j in range(6)]
    if not all(0 <= v <= 100 for v in tal): return None
    if b[tal_off - 1] != 0 or b[tal_off - 2] != 0: return None
    birth, show, death = i32(b, tal_off + O_BIRTH), i32(b, tal_off + O_SHOW), i32(b, tal_off + O_DEATH)
    moral, compat = i32(b, tal_off + O_MORAL), i32(b, tal_off + O_COMPAT)
    if not (100 <= birth <= 300 and 100 <= show <= 300 and 130 <= death <= 320 and death > birth): return None
    if not (-100 <= moral <= 100 and 0 <= compat <= 200): return None
    return tal


def find_all_npc_records(b):
    """一个档里可能有多个自建武将（NWJ0/NWJ1/NWJ2…），全扫出来。"""
    out, st = [], 0
    while True:
        r = find_player_record(b, st)
        if not r:
            break
        out.append(r)
        st = r['anc']
    return out


def parse_new_npc(path):
    """读 SaveData/NewNPC（自建武将定义）→ {NWJx: 显示名}。

    每条记录的形状（实测 Save7 的三条）：
        [len]姓 [len]名 [len]字(可为 00) [00] [len]NWJx ...
    例：03 陈 06 平安 06 子玉 00 04 NWJ0 / 03 陆 03 一 00 00 04 NWJ1
    注意：自建武将的定义在这个**全局文件**里，存档里只有"用到的实例"，
    所以存档里查不到名字时要来这里补。
    """
    out = {}
    try:
        b = open(path, 'rb').read()
    except Exception:
        return out
    STR = re.compile(rb'([\x01-\x0c])((?:[\xe0-\xef][\x80-\xbf]{2}|[\x20-\x7e])+)')
    for m in re.finditer(rb'([\x03-\x08])(NWJ\d+)', b):
        pid = m.group(2).decode('ascii')
        head = b[max(0, m.start() - 48):m.start() - 1]
        parts = [x.group(2).decode('utf-8', 'ignore') for x in STR.finditer(head)]
        if len(parts) >= 3:
            out[pid] = parts[-3] + parts[-2]        # 姓 + 名（丢掉"字"）
        elif len(parts) == 2:
            out[pid] = parts[-2] + parts[-1]
    return out


def find_player_record(b, start=0):
    r"""自建武将记录： [len]NWJ\d+[len]模型预设[7字节口令][资质×6]

    2026-10-22 提速：原来逐字节 for i in range(start, len(b)-12) 试，
    23MB 存档要 ~1 秒（cProfile 实测 find_player_record 0.97s，是读档第二大项）。
    现在用 bytes.find（C 层）先跳到 'NWJ' 出现处，再回退一个字节看长度 ——
    与被扫条件「b[i] 是 3..16 的长度 且 b[i+1:i+4]=='NWJ'」完全等价。
    """
    n = len(b)
    j = start + 1                    # NWJ 的 'N' 位置 = i+1，故 j 从 start+1 起
    while j <= n - 12:
        j = b.find(b'NWJ', j)
        if j < 0 or j > n - 12:
            return None
        i = j - 1
        L = b[i]
        if (3 <= L <= 16) and j + 1 + L <= n:
            pid = dec(b, j, j + L)
            if pid and re.match(r'^NWJ\d+$', pid):
                ps = i + 1 + L
                pl = b[ps] if ps < n else 255
                if not (pl > 40 or ps + 1 + pl + 7 + 24 > n):
                    preset = dec(b, ps + 1, ps + 1 + pl)
                    if preset and not any(ord(c) < 32 for c in preset):
                        t = ps + 1 + pl + 7
                        if (b[t - 7] == 0 and b[t - 6] == 1 and b[t - 5] == 1):
                            tal = [i32(b, t + k * 4) for k in range(6)]
                            if all(0 <= v <= 100 for v in tal):
                                return {'id': pid, 'preset': preset, 'anc': j,
                                        'tal_off': t, 'id_len': L,
                                        'kind': 'player', 'six_off': None}
        j += 1
    return None


def mark_player_hero(heroes, save_name):
    """在武将表里标出**玩家自己**那条记录：记录内 Name == 存档头部第 1 串。

    ⚠️ 自建档的关键：自建武将的记录名不是玩家起的真名，而是**立绘预设名**
       （Save1 头部 = ['随机男025', '陈平安', '邪马台', '陈平安']，
        NWJ0 记录里的 Name 字段正是「随机男025」）。
       旧代码拿头部第 1 串去比「主表武将名」，自建档永远 0 命中 —— 这就是
       自建武将/自建君主一直定位不到玩家的真正原因。
    改成比「记录内 Name」之后，六档（Save5/6/7/8/9 + 诊断档，含自建档）全部唯一命中。
    返回玩家记录（已置 is_player=True）或 None。
    """
    if not save_name:
        return None
    hit = [h for h in heroes if h.get('rec_name') == save_name]
    if len(hit) == 1:
        hit[0]['is_player'] = True
        return hit[0]
    # 兜底：顺序解析没拿到 rec_name（个别变体记录会解析失败）时，退回
    # 「主表武将名 == save_name」。普通档这两种写法结果一致。
    hit = [h for h in heroes if h.get('name') == save_name and h.get('rec_name')]
    if len(hit) != 1:
        hit = [h for h in heroes if h.get('name') == save_name]
    if len(hit) != 1:
        return None
    hit[0]['is_player'] = True
    return hit[0]


def parse_heroes(b, npc_names=None):
    """主表武将 + 玩家自建记录。返回 (heroes, base_count)。"""
    cand, seen = [], set()
    raw = bytes(b)
    st = 0
    while True:
        j = raw.find(b'WJ', st)
        if j < 0 or j < 1: break
        st = j + 1
        i = j - 1                      # 长度字节位置
        L = b[i]
        if not (7 <= L <= 16): continue
        if i + 1 + L + 2 > len(b): continue
        hid = dec(b, i + 1, i + 1 + L)
        if not hid or not re.match(r'^WJ\d{5,}$', hid): continue
        np = i + 1 + L
        nl = b[np]
        if not (6 <= nl <= 24) or np + 1 + nl > len(b): continue
        nm = dec(b, np + 1, np + 1 + nl)
        if not nm or not NAME_RE.match(nm): continue
        anc = i + 1
        tal_off = anc + L + nl + 8
        if _tal_ok(b, tal_off) is None: continue
        if hid in seen: continue
        seen.add(hid)
        cand.append({'id': hid, 'name': nm, 'anc': anc, 'id_len': L, 'name_len': nl,
                     'tal_off': tal_off, 'kind': 'main', 'six_off': None})
    cand.sort(key=lambda h: h['anc'])
    base = len(cand)
    for k, h in enumerate(cand):
        h['end'] = cand[k + 1]['anc'] if k + 1 < len(cand) else len(b)
    # 自建武将（可能有多个）：名字不在存档里，从 SaveData/NewNPC 取
    for k, pl in enumerate(find_all_npc_records(b)):
        pl['name'] = (npc_names or {}).get(pl['id']) or pl['id']
        pl['end'] = cand[0]['anc'] if cand else len(b)
        cand.insert(k, pl)
    # 顺序解析一遍：拿记录内的真名 + 六维块偏移（见 parse_hero_seq 说明）
    for h in cand:
        sq = parse_hero_seq(b, h['anc'])
        if not sq:
            continue
        h['rec_name'] = sq['name']        # 记录内 Name（自建武将是立绘预设名）
        h['seq_six'] = sq['six_off']      # 顺序解析得到的六维块偏移（首选）
        h['seq_attrs'] = sq['attrs']
        h['seq_city'] = sq['city']
    return cand, base


def after_hero_anchor(b, pos):
    """pos 之前 700 字节内是否已越过玩家记录、进入主表某条武将记录（严格判据）。"""
    for q in range(pos - 1, max(1, pos - 700) - 1, -1):
        L = b[q]
        if not (7 <= L <= 16): continue
        if q + 1 + L > len(b): continue
        if b[q + 1] != 0x57 or b[q + 2] != 0x4A: continue
        s = dec(b, q + 1, q + 1 + L)
        if not s or not re.match(r'^WJ\d{5,}$', s): continue
        np = q + 1 + L
        nl = b[np]
        if not (6 <= nl <= 24) or np + 1 + nl > len(b): continue
        nm = dec(b, np + 1, np + 1 + nl)
        if not nm or not NAME_RE.match(nm): continue
        return True
    return False


# ---------------------------------------------------------------- 武将记录顺序解析
# 2026-10-21：改用「顺序解析」（逆向第三方编辑器 HeroesVowEditor 的
# CharacterScanner.Parse 字段顺序，源码见 hve_ref/src/decompiled_zh-cn/）。
#
# 为什么换：旧办法是「在记录区间内搜 [06]CS1xxx + 6 个小整数」再靠签名/城市挑，
# 属启发式，自建武将、变体记录都会选错。顺序解析是照字段定义一路读下去，
# 读到 City 串之后紧跟着就是 6 个基础能力（六维），位置确定、不需要猜。
# 六档（Save5/6/7/8/9 + 诊断档）实测：1269~1271 条记录 100% 解析成功，0 失败。
#
# 字段顺序（CharacterScanner.cs:38-127 的 Parse）：
#   id Str, name Str, source Str, byte<=1, byte<=1, int(0/1),
#   6×资质(0..1000), 11×float(0..100), int×3, byte<=1,
#   生年 int, int, 卒年 int, int, 死因 int(0..2), int, int, byte<=1, int×4,
#   byte, byte, count(500)×(int,int), 2×(Str, int), 3×Pairs,
#   Power Str, other Str, int, byte<=1, 身份 int(0..3), int, int,
#   **City Str（CS1xxx）→ 6×基础能力(0..10000)**
#
# ⚠️ 起点差异：h['anc'] 指向 **id 字符串内容**（长度字节之后 +1），
#    HVE 的 Parse(start) 起点是 **LEB128 长度字节本身**，所以这里要 anc-1。

class _SeqBad(Exception):
    pass


class _SeqR:
    """按 HVE SaveReader 的规则顺序读，越界/取值非法就抛 _SeqBad。"""
    __slots__ = ('b', 'p', 'n')

    def __init__(self, b, p):
        self.b, self.p, self.n = b, p, len(b)

    def i32(self):
        p = self.p
        if p + 4 > self.n:
            raise _SeqBad('eof')
        self.p = p + 4
        return struct.unpack_from('<i', self.b, p)[0]

    def u8(self):
        p = self.p
        if p >= self.n:
            raise _SeqBad('eof')
        self.p = p + 1
        return self.b[p]

    def f32(self):
        p = self.p
        if p + 4 > self.n:
            raise _SeqBad('eof')
        self.p = p + 4
        return struct.unpack_from('<f', self.b, p)[0]

    def s(self, mx):
        """LEB128 长度前缀的 UTF-8 串。"""
        n, ok = 0, False
        for i in range(0, 35, 7):
            c = self.u8()
            if i == 28 and c > 7:
                raise _SeqBad('len')
            n |= (c & 0x7F) << i
            if c < 128:
                ok = True
                break
        if not ok or n > mx or self.p + n > self.n:
            raise _SeqBad('len')
        raw = self.b[self.p:self.p + n]
        self.p += n
        try:
            return bytes(raw).decode('utf-8')
        except Exception:
            raise _SeqBad('utf8')

    def cnt(self, mx):
        v = self.i32()
        if v < 0 or v > mx:
            raise _SeqBad('count')
        return v

    def pairs(self):
        for _ in range(self.cnt(5000)):
            t = self.s(100)
            if t and not all(c.isalnum() or c in '_-' for c in t):
                raise _SeqBad('pairs')
            self.i32()


def parse_hero_seq(b, anc):
    """顺序解析一条武将记录，返回 dict；解析不通过返回 None。

    返回：id / name（记录内的名字，自建武将是立绘预设名如「随机男025」）/
          source / city / six_off（六维块偏移）/ attrs（6 个基础能力）/
          prefix_end（8 项武器熟练度之后的偏移）。
    """
    try:
        r = _SeqR(b, anc - 1)
        hid = r.s(100)
        if not (hid.startswith('WJ') or hid.startswith('NWJ')):
            return None
        nm = r.s(240)
        if not nm or any(ord(c) < 32 for c in nm):
            return None
        src = r.s(240)
        if r.u8() > 1 or r.u8() > 1 or r.i32() not in (0, 1):
            return None
        for _ in range(6):                       # 6 项成长资质 0..1000
            if not (0 <= r.i32() <= 1000):
                return None
        for _ in range(11):                      # 11 个 0..100 的浮点
            f = r.f32()
            if not (0.0 <= f <= 100.0):
                return None
        for _ in range(3):
            r.i32()
        if r.u8() > 1:
            return None
        birth = r.i32()
        r.i32()
        death = r.i32()
        if not (0 <= birth <= 1500 and 0 <= death <= 1500):
            return None
        r.i32()
        if not (0 <= r.i32() <= 2):               # 死因 0..2
            return None
        r.i32()
        r.i32()
        if r.u8() > 1:
            return None
        for _ in range(4):
            r.i32()
        if r.u8() > 1 or r.u8() > 1:
            return None
        for _ in range(r.cnt(500)):
            r.i32()
            r.i32()
        for _ in range(2):
            r.s(100)
            r.i32()
        for _ in range(3):
            r.pairs()
        r.s(100)                                  # Power 串
        r.s(100)                                  # other 串
        r.i32()
        if r.u8() > 1:
            return None
        if not (0 <= r.i32() <= 3):               # 身份 0..3
            return None
        r.i32()
        r.i32()
        city = r.s(100)
        if city and not city.startswith('CS'):
            return None
        six_off = r.p
        attrs = [r.i32() for _ in range(6)]
        if not all(0 <= v <= 10000 for v in attrs):
            return None
        return {'id': hid, 'name': nm, 'source': src, 'city': city,
                'six_off': six_off, 'attrs': attrs}
    except _SeqBad:
        return None
    except (struct.error, IndexError):
        return None


def head_hve(b):
    """HVE CharacterScanner.Detect 的头部读法：从 offset 8 起
    saveName Str / i32 / playerName Str / i32 / i32。

    返回 {'save': …, 'player': …}；读不通返回 None。
    ⚠️ 自建档：saveName 是**立绘预设名**（如「随机男025」，等于 NWJ 记录里的 Name），
        playerName 才是玩家自己起的真名（如「陈平安」）。旧代码只取了启发式扫的第一个
        串（= 立绘预设名）当玩家名，拿去对势力称号归属当然对不上。
    """
    try:
        r = _SeqR(b, 8)
        save = r.s(1024)
        r.i32()
        player = r.s(1024)
        r.i32()
        r.i32()
        return {'save': save, 'player': player}
    except (_SeqBad, struct.error, IndexError):
        return None


def six_cands(b, h, raw=None):
    """武将记录内的 [06]CS1xxx + 6 个 1..300 整数 + 字段签名（用字节比较 + 批量解包，别逐字节 Python 循环）。"""
    frm = h['tal_off']
    if h['kind'] == 'player':
        to = min(len(b), h['tal_off'] + 0x8000)
    else:
        to = min(len(b), h.get('end') or len(b))
    if frm >= to: return []
    if raw is None: raw = bytes(b)
    out = []
    is_player = (h['kind'] == 'player')
    p = raw.find(b'\x06CS1', frm, to)      # 命中位置是 0x06 那个长度字节，字符串从 p+1 开始
    while p >= 0:
        if p + 97 > to: break
        d1, d2, d3 = b[p + 4], b[p + 5], b[p + 6]
        if 48 <= d1 <= 57 and 48 <= d2 <= 57 and 48 <= d3 <= 57:
            q = p + 7
            v = struct.unpack_from('<6i', b, q)
            if v[0] >= 1 and v[1] >= 1 and v[2] >= 1 and v[3] >= 1 and v[4] >= 1 and v[5] >= 1 \
                    and max(v) <= 300:
                sp = struct.unpack_from('<3i', b, q + O_SOULPT)
                sl = struct.unpack_from('<3i', b, q + O_SOULLV)
                ms = struct.unpack_from('<8i', b, q + O_MASTER)
                pf = struct.unpack_from('<4i', b, q + O_PROF)
                # 特性真实上限是 6（全档实测最大 6）；签名放宽到 9 是故意的——
                # 容忍旧版本修改器把 9 写进存档的档，别把六维块定位弄丢
                sig = (min(sp) >= 0 and max(sp) <= 999999 and min(sl) >= 0 and max(sl) <= 99
                       and min(ms) >= 0 and max(ms) <= 300 and min(pf) >= 0 and max(pf) <= 9)
                # 强签名：魂等级(soullv)与专精(prof)都至少有一项非 0。
                # 实测（2026-10-20，诊断档 Save1）：「[06]CS1xxx + 6 个小整数」这种形状
                # 在同一武将记录里会出现好几份，但只有真六维块的 soullv/prof 有内容，
                # 假块两者全 0。用这个区分，别拿城市串去猜——CS1xxx 代表的是记录里
                # 引用的城市，不是武将当前坐标，按它匹配会选到假块。
                strong = sig and max(sl) > 0 and max(pf) > 0
                if is_player and after_hero_anchor(b, p + 1):
                    break
                cs = bytes(b[p + 1:p + 7]).decode('ascii', 'ignore')
                out.append({'off': q, 'cs': cs, 'vals': list(v), 'sig': sig, 'strong': strong})
        p = raw.find(b'\x06CS1', p + 1, to)
    return out


def locate_six(b, h, cur_place=None, city_id=None, raw=None, rec_ancs=None):
    """给一条武将记录定位六维块。

    取值顺序：
      ⓪ 记录区间归属（首选）：一条武将记录之后、**下一条**武将记录之前的六维块才
         属于它。2026-10-20 修：Save8 孙权档里两个自建武将（NWJ1 陆一 / NWJ2 梁二）
         的真块就在各自记录后约 0xf0 处，但同一搜索区间里还躺着别人的强块，城市串
         恰好等于玩家当前城市「建业」（CS1053），旧的城市匹配把两人都指到同一块假
         块 [8,4,34,38,52,38] 上。1270 条武将 × 6 档实测：改用区间归属只有这 2 条
         变化，其余全部不变。
         区间内取第一个强块（soullv/prof 有内容），没有强块再退弱签名块。
      ① 没有记录边界可用时（老调用方）退回旧逻辑：强签名块恰好一个 → 直接用它；
      ② 否则玩家记录按「城市 == 当前地点」在强块里挑，挑不到就用强块第一个；
      ③ 一个强块都没有（新武将魂等级专精本来就是 0）才退回弱签名池。
    ⚠️ 2026-10-20 修：旧的「城市 == 当前地点」判据不可靠——[06]CS1xxx 串代表的是
       记录里引用的城市，不是武将当前坐标。诊断档 Save1 的师宁(NWJ0) 因此读成
       [6,3,11,18,21,3]，真值是 [79,43,97,83,70,84] @0xd9a0cd。
    ⚠️ 2026-10-21：parse_heroes 已经顺手做了顺序解析，h['seq_six'] 存在时**直接采信**
       （照字段定义读出来的，不用猜）。下面的启发式只在顺序解析失败时兜底。
    """
    if h.get('seq_six') is not None:
        return {'off': h['seq_six'], 'cs': h.get('seq_city') or '',
                'vals': list(h.get('seq_attrs') or []), 'sig': True, 'strong': True,
                'how': 'seq'}
    allc = six_cands(b, h, raw)
    if not allc: return None
    if rec_ancs:
        i = bisect.bisect_left(rec_ancs, h['anc'])
        nxt = rec_ancs[i + 1] if i + 1 < len(rec_ancs) else len(b)
        mine = [c for c in allc if h['anc'] <= c['off'] < nxt]
        if mine:
            ms = [c for c in mine if c.get('strong')]
            return (ms or [c for c in mine if c['sig']] or mine)[0]
    good = [c for c in allc if c['sig']]
    strong = [c for c in good if c.get('strong')]
    if len(strong) == 1:
        return strong[0]                     # 强块唯一：城市串不可信，直接采信
    pool = strong or good or allc
    if h['kind'] == 'player' and cur_place and city_id:
        cid = city_id.get(cur_place)
        if cid:
            for c in pool:
                if c['cs'] == cid:
                    return c
    # 主表武将有 1~2 块时按签名取第一个；玩家挑不到城市也取第一个
    return pool[0]


# ---------------------------------------------------------------- 背包
def bag_entry(b, p):
    if p < 0 or p >= len(b): return None
    L = b[p]
    if not (4 <= L <= 45) or p + 1 + L + 10 > len(b): return None
    iid = dec(b, p + 1, p + 1 + L)
    if not iid or not ID_RE.match(iid): return None
    e = p + 1 + L
    qty = i32(b, e)
    if not (0 <= qty <= 1000000): return None
    return {'id': iid, 'qty': qty, 'f2': i32(b, e + 4), 'f3': i16(b, e + 8), 'next': e + 10, 'off': p}


def bag_walk(b, p0, ngrp=BAG_NGRP):
    p, groups = p0, []
    for _ in range(ngrp):
        if p + 4 > len(b): return None
        n = i32(b, p)
        if not (0 <= n <= BAG_MAX_ITEMS): return None
        items, q = [], p + 4
        for _ in range(n):
            e = bag_entry(b, q)
            if not e: return None
            items.append(e)
            q = e['next']
        groups.append({'off': p, 'n': n, 'items': items, 'end': q})
        p = q
    return {'start': p0, 'end': p, 'groups': groups}


def _bag_score(groups):
    tot = sum(len(g['items']) for g in groups)
    ne = sum(1 for g in groups if g['items'])
    return tot, ne


def find_bag(b, money=None, player=None):
    """定位玩家真正的 13 组背包。

    【不变量】玩家的资产块里，「金钱 i32」后面**紧跟着** 13 个分类容器链
    （[i32 n][n × ([len]id + i32 数量 + i32 f2 + i16 f3)] × 13）。
    所以只要找一个位置 p，满足 i32(b, p-4) == 头部金钱 且 bag_walk(b, p) 走通，
    那就是背包起点，而 p-4 就是金钱在资产块里的副本（后面称号列表也要用它当锚点）。

    这条规则与「玩家是不是君主、背包第一组是不是空的、背包里有多少东西」都无关：
      · Save1（君主档，655 件）→ 0xD6AEBD
      · Save5（新档·武将，11 件，武器组为空）→ 0x3571C
    两档同一条规则都唯一命中，不用再按档适配。
    """
    if money is None:
        _, money, _ = money_copies(b)
    best = None
    if money and 0 < money <= 2000000000:
        pat = struct.pack('<i', money)
        raw = bytes(b)
        i, cands = 0, []
        while True:
            i = raw.find(pat, i)
            if i < 0: break
            p = i + 4
            r = bag_walk(b, p)
            if r:
                tot, ne = _bag_score(r['groups'])
                cands.append((tot, ne, -p, p, r))     # 件数多 > 非空组多 > 靠前
            i += 1
        if cands:
            cands.sort(reverse=True)
            tot, ne, _, p, r = cands[0]
            best = {'start': p, 'end': r['end'], 'groups': r['groups'],
                    'tot': tot, 'ne': ne, 'money2': p - 4}
    if best and (best['tot'] >= 1 or best['ne'] >= 1):
        return best
    # ---------------------------------------------------------------- 兜底
    # 上面按值找金钱副本失败（比如金钱为 0）时，退回旧的全局扫描：
    # 先按 NWJ 玩家锚点找，再全文件兜底，取件数最多的那个。
    best = None
    raw = bytes(b)
    anchors, st = [], 0
    while True:
        j = raw.find(b'NWJ', st)
        if j < 0 or j < 1: break
        st = j + 1
        L = b[j - 1]
        if not (3 <= L <= 16): continue
        nid = dec(b, j, j + L)
        if nid and re.match(r'^NWJ\d+$', nid):
            anchors.append(j)
            if len(anchors) > 60: break
    for anc in anchors:
        lim = min(len(b) - BAG_NGRP * 6, anc + 40000)
        for p in range(anc, max(anc, lim)):
            v = i32(b, p)
            if not (0 < v <= 3000): continue
            r = bag_walk(b, p)
            if not r: continue
            tot, ne = _bag_score(r['groups'])
            if tot < 20 or ne < 3: continue
            if not best or tot > best['tot']:
                best = {'start': p, 'end': r['end'], 'groups': r['groups'],
                        'tot': tot, 'ne': ne, 'money2': p - 4}
        if best and best['tot'] >= 250 and best['ne'] >= 10:
            break
    if not (best and best['tot'] >= 250 and best['ne'] >= 10):
        p = 4
        while p + 8 < len(b):
            v = i32(b, p)
            if 0 < v <= 3000:
                r = bag_walk(b, p)
                if r:
                    tot, ne = _bag_score(r['groups'])
                    if tot >= 20 and ne >= 3 and (not best or tot > best['tot']):
                        best = {'start': p, 'end': r['end'], 'groups': r['groups'],
                                'tot': tot, 'ne': ne, 'money2': p - 4}
            p += 1
    return best


def ser_bag(groups):
    """把 13 组重新序列化成字节（用于写回）。"""
    out = bytearray()
    for g in groups:
        items = g['items']
        out += struct.pack('<i', len(items))
        for it in items:
            iid = it['id']
            out += bytes([len(iid)]) + iid.encode('ascii')
            out += struct.pack('<i', int(it.get('qty', 0)))
            out += struct.pack('<i', int(it.get('f2', 0)))
            out += struct.pack('<h', int(it.get('f3', 0)))
    return bytes(out)


# ---------------------------------------------------------------- 称号列表
def find_title_lists(b, money2, title_ids, win=0x8000):
    """装配称号列表：[i32 N][len][称号id]×N，位于玩家资产块金钱**之前**。

    【不变量】
      ① 锚点用「资产块金钱」= 背包起点 - 4（见 find_bag），
         而不是「金钱值的第二处出现」—— 金钱是小数值时（比如新档 4000），
         文件里会有成百上千个同值字节，第二处根本不是资产块，旧规则就是这么跑偏的。
      ② 玩家自己的称号表整条都是称号（ratio = 1）；同一个窗口里长得一模一样的
         军魂 / 军技 / 武魂 / 阵法表 ratio 很低，靠 ratio 先筛掉。
      ③ ratio = 1 的可能有好几条（别的武将也有称号表），
         玩家那条一定离资产块金钱最近 —— 因为在自己的数据块最末尾。
    实测：Save1（君主档）→ 0xD68F98，N=54；Save5（新档）→ 0x330D4，N=1（常胜将军）。
    """
    if money2 is None or money2 <= 8 or not title_ids:
        return []
    out, lo = [], max(0, money2 - win)
    for o in range(lo, money2 - 8):
        N = i32(b, o)
        if not (1 <= N <= 300): continue
        p, ids, ok = o + 4, [], True
        for _ in range(N):
            L = b[p] if p < len(b) else 0
            if not (5 <= L <= 16): ok = False; break
            s = dec(b, p + 1, p + 1 + L)
            if not s or not TID_RE.match(s): ok = False; break
            ids.append(s); p += 1 + L
        if not ok: continue
        nt = sum(1 for i in ids if i in title_ids)
        if not nt: continue
        out.append({'count_off': o, 'start': o + 4, 'end': p, 'ids': ids,
                    'nt': nt, 'ratio': nt / len(ids)})
    if not out:
        return out
    # 玩家称号表就在资产块前面不远（实测 Save1 -8199 / Save6 -9979 / Save7 -6878），
    # 更远的那种（Save7 的 -26126「奇佐之才」）是别的武将的，要排除掉。
    near = [x for x in out if 0 < (money2 - x['count_off']) <= 15000]
    pure = [x for x in near if x['ratio'] >= 1.0]
    if pure:
        # 玩家的称号表永远排在**靠前**的位置（相邻常有别的武将/势力的同类表紧跟在后面）。
        # 实测：Save6 袁绍 0xD915C(N=5) 才是他的，0xD9188(N=4) 是下一个人的；
        #       Save1 0xDA2343(N=56)、Save7 钟会 0x1FE18A(N=1) 也都是靠前那条。
        # （旧规则用「离金钱最近」，Save6/Save7 会选错成后面那条）
        pure.sort(key=lambda x: (x['count_off'], -x['nt']))
        return pure + sorted((x for x in out if x['ratio'] < 1.0),
                             key=lambda x: (-x['ratio'], -x['nt'], x['count_off']))
    out.sort(key=lambda x: (-x['ratio'], -x['nt'], x['count_off']))
    return out


def scan_hero_titles(b, hero, title_ids):
    """任意武将记录内的称号表（`[i32 N][len]title_id × N`）。

    实测 Save6 颜良（0xE4D1B~0xE87E0）记录里有两条：
        @0xE4EFB N=1 → 勇冠三军
        @0xE4F07 N=3 → 西凉铁骑统领 / 奇策百出 / 贲育之胆
    返回 [{'count_off','start','end','ids'}, ...]（按位置升序）。
    """
    lo, hi = hero.get('anc'), hero.get('end')
    if not lo or not hi or hi <= lo:
        return []
    out = []
    p = lo
    while p < hi - 4:
        N = i32(b, p)
        if 1 <= N <= 60:
            q, ids, ok = p + 4, [], True
            for _ in range(N):
                if q >= hi:
                    ok = False
                    break
                L = b[q]
                if not (5 <= L <= 16):
                    ok = False
                    break
                t = dec(b, q + 1, q + 1 + L)
                if not t or not re.match(r'^1\d{6}$', t):
                    ok = False
                    break
                ids.append(t)
                q += 1 + L
            if ok and len(ids) == N and any(x in title_ids for x in ids):
                out.append({'count_off': p, 'start': p + 4, 'end': q, 'ids': ids})
                p = q
                continue
        p += 1
    return out


def ser_title_list(ids):
    out = bytearray(struct.pack('<i', len(ids)))
    for i in ids:
        out += bytes([len(i)]) + i.encode('ascii')
    return bytes(out)


# ---------------------------------------------------------------- 势力资源
def skill_run_before(b, p):
    """返回紧邻 p 之前的 [len 3..5][纯数字][i32 0..999999] 连续记录条数。"""
    for pad in range(4, 17):
        q, cnt = p - pad, 0
        while q > 8:
            found = -1
            for L in range(3, 6):
                o = q - 1 - L - 4
                if o < 0: continue
                if b[o] != L: continue
                s = dec(b, o + 1, o + 1 + L)
                if not s or not s.isdigit() or not (2 <= len(s) <= 6): continue
                v = i32(b, o + 1 + L)
                if not (0 <= v <= 999999): continue
                found = o; break
            if found < 0: break
            q = found; cnt += 1
            if cnt > 80: break
        if cnt >= 3: return cnt
    return 0


def find_treasury_near(b, lo, hi):
    """在 [lo,hi) 找「国库金 + 势力仓库物品列表」。"""
    for t in range(lo, min(hi, len(b) - 24)):
        v = i32(b, t)
        if not (10000 <= v <= 99999999): continue
        for c_off in (t + 4, t + 8):
            if c_off == t + 8 and i32(b, t + 4) != 0: continue
            n = i32(b, c_off)
            if not (1 <= n <= 500): continue
            p, ok = c_off + 4, True
            for _ in range(n):
                e = bag_entry(b, p)
                if not e or len(e['id']) < 4 or not (0 <= e['qty'] <= 1000000):
                    ok = False; break
                p = e['next']
            if ok: return {'off': t, 'val': v, 'n': n}
    return None


def find_lingyun(b):
    """灵蕴 = 玩家个人资源。

    锚点（2026-10-19 三档实测，全档唯一）：
        [i32 -251658240][i32 33554392][i32 0]  [i32 灵蕴值]
        字节：f1 d8 ff ff  01 80 00 00  00 00 00 00  <灵蕴>
    Save5=12345、Save6=99999、Save7=45678，三档全档搜索都只有 1 处命中。
    返回 (灵蕴偏移, 灵蕴值) 或 (None, None)。
    """
    pat = struct.pack('<3i', -251658240, 33554392, 0)
    i = bytes(b).find(pat)
    if i < 0:
        return None, None
    off = i + 12
    if off + 4 > len(b):
        return None, None
    return off, i32(b, off)


# ---------------------------------------------------------------- 势力块（2026-10-19 重写）
# 存档后半段每个势力都有一份「势力块」。已确认的两种形态：
#   形态A（Save6/Save8，带建筑列表）：
#     [i32 n1][len]JZ建筑id × n1
#     [i32 n2]([len]据点编号 [i32]) × n2
#     [i32 0][科技 i32][策略 i32]
#   形态B（Save1_1014_基准，无建筑列表）：
#     [i32 n2]([len]据点编号 [i32]) × n2
#     [i32 某值][科技 i32][策略 i32]        ← 中间可能夹一个非零 i32（实测是 float 0.2）
# 共同点（扫描锚点）：
#   · 「据点编号」= 纯数字串，长度 2~6，每条 = [len][编号][i32 等级/数量]
#   · 据点列表**结束后**不远处就是 [科技 i32][策略 i32]（相邻，允许夹 0~2 个 i32）
# 之后：
#   [i32 0][i32 0][7位君主策略id]        ← 只有「有专属策略的君主势力」才有
#   [i32 仓库物品数]([len]id[i32 数量])×n [i32 国库金]
#   …其后是武将列表（WJ id）
# 【每个势力有两份记录】
#   · 当前状态块：tech 是真实值、有君主策略 id、国库金为真实值、仓库数字段 == 0
#   · 孪生模板块：tech=1000 / strat=0、据点列表与当前块相同、无策略 id、
#                 仓库数字段 == -1（Save6/Save8 实测国库金偏移 +0x277/+0x279，当前块 +0x127）
# ⚠️ 国库金的绝对偏移不固定（+0x127 / +0x310 都见过），必须动态找。
FACTION_STRAT_RE = re.compile(r'^\d{7}$')
ANCHOR_RE = re.compile(r'^\d{2,6}$')


def _faction_anchor_ok(s):
    """据点编号：2~6 位纯数字（102 / 10502 / 11302 都见过）。"""
    return bool(s) and ANCHOR_RE.match(s)


def faction_treasury_at(b, tech_off, span=0x400, n1=0):
    """找势力块的国库金。

    【2026-10-21 破案】国库金是**形态A 块内的固定字段**，位置恒为 `tech_off + 0x127`：
        形态A（n1>=1，块头是 JZ 建筑列表）——
          Save6 袁绍 12304 @ tech_off+0x127 ✅（真值，小K 游戏内改出后全档搜索确认）
          Save8 孙权 12357 @ tech_off+0x127 ✅（同上）
          Save9 刘备 10000 @ tech_off+0x127
          诊断档 刘备 10000 @ tech_off+0x127
        四档同偏移，且 Save6 全 32 块里只有玩家块(=12304)和曹操块(=10000)非零、
        其余 30 块恰好全 0 → 这是结构字段，不是撞出来的。
    ⚠️ 为什么是奇数偏移：块头 JZ/据点串长度不定，`tech_off` 本身不对齐
       （Save6 tech_off=0x15c2e6a，%4=2），所以 0x127 也是奇数位。
       **必须按字节偏移读，不能对齐到 4 字节**，否则会读到 `0x30`(=48) 那种错位值。
    ⚠️ 旧的「逐字节找 100~0xFFFF 且后跟 4 个 0」启发式会**抢先撞上假值**：
       Save9 / 诊断档 会读到 15948 @ +0x89（真值 10000 @ +0x127）。故形态A 直接
       取固定偏移，不再扫描。

    形态B（n1==0，无建筑列表，如自建档 Save1 系列 / 家族档）块布局不同，
    该偏移读到的是垃圾（Save1=808519424、S1_1012=50），仍退回旧启发式并标注不可靠。

    返回 {'wh_off','wh','val_off','val'} 或 None。
    """
    # ---- 形态A：固定字段 ----
    if n1 >= 1:
        p = tech_off + 0x127
        if p + 4 <= len(b):
            val = i32(b, p)
            if 0 <= val <= 1000000000:
                return {'wh_off': p - 4, 'wh': i32(b, p - 4),
                        'val_off': p, 'val': val, 'form': 'A'}
    # ---- 形态B / 兜底：旧启发式（不可靠，仅供诊断）----
    lo = tech_off + 0x80        # 跳过「策略 id + 305 + 中间字段」等头部，从 0x80 之后找
    hi = min(len(b) - 8, tech_off + span)
    p = lo
    while p < hi:
        val = i32(b, p)
        if (100 <= val < 0x10000 and not (val & 0xFF000000)
                and i32(b, p + 4) == 0):
            return {'wh_off': p - 4, 'wh': i32(b, p - 4), 'val_off': p, 'val': val,
                    'form': 'B'}
        p += 1
    return None


# 势力块起点预筛：小端 i32 落在 1..40（两个入口的首字段都要求 1 <= n <= 40）。
# 后三字节必须为 0 —— 这是 i32 落在 1..40 的充要条件（值 < 256 且非 0）。
_FACTION_CAND_RE = re.compile(rb'[\x01-\x28]\x00\x00\x00')
# 家族块候选：score_faction_at 第一关是 1<=n1<=60，同上面道理（2026-10-22）
_FAMILY_CAND_RE = re.compile(rb'[\x01-\x3c]\x00\x00\x00')


def scan_faction_blocks(b, lo=None):
    """全档扫势力块。两种入口都收，最后都归结到「据点列表结束后紧跟 [科技][策略]」：

      入口A `[i32 n2][([len]据点编号[i32 值])×n2]`   ← 老形态（Save6/Save8 常见）
      入口B `[i32 n1][([len]JZ建筑)×n1][i32 n2]…`    ← 2026-10-20 新增：诊断档 Save1 里
            刘备势力是 n1=8 的 JZ 列表 + n2=0（没有据点），旧扫描要求 n2≥1 直接把这块
            跳过了，于是 pick_player_faction 只能在别人（曹操 1013801 / 孙权 1014201）
            的块里挑，读出科技 740、策略 353 —— 真值是 1081 / 263。

    返回按位置排序的列表，每项：
      {'start','n1','n2','lst2','tech_off','tech','strat',
       'strat_id','treasury','wh'}
    只扫文件后半段（势力块都在那里），lo 可覆盖。

    性能（2026-10-22）：原来 for p in range(lo, n) 逐字节试，23MB 存档光这一步
    就要 ~8 秒、单核跑满（cProfile：3317 万次 i32 + 3355 万次 unpack_from）。
    现在先用正则把「i32(b,p) 落在 1..40 且后三字节为 0」的位置一次性挑出来
    （约 30 万个，占 2.5%），只对它们做完整判定 —— 结果完全等价（两个入口的
    第一关都是 1 <= i32(p) <= 40，不满足的起点本来就会被当场否掉）。
    """
    n = len(b)
    if lo is None:
        lo = n // 2
    out = {}
    limit = n - 16
    # 预筛剩余 → 候选起点（C 层正则，比 Python 循环快约 6 倍）
    # 2026-10-22 二次提速：直接迭代 finditer 生成器，不再先构建 30 万元素的
    # list（原来那次 listcomp 单独占 0.11s / 3MB 内存，纯属浪费）。
    p_floor = lo            # 命中一块后从 tech_off+4 接着扫，等价于原来的 p 跳转
    for _m in _FACTION_CAND_RE.finditer(b, lo, limit):
        p = _m.start()
        if p < p_floor:
            continue
        q = None
        n1 = n2 = 0
        lst2 = []
        # ---- 入口B：JZ 建筑列表（n1≥1）在前 ----
        n1c = i32(b, p)
        if 1 <= n1c <= 40:
            r, ok = p + 4, True
            for _ in range(n1c):
                if r + 2 > n: ok = False; break
                L = b[r]
                if not (5 <= L <= 14) or r + 1 + L > n: ok = False; break
                s = dec(b, r + 1, r + 1 + L)
                if not s or not JZ_RE.match(s): ok = False; break
                r += 1 + L
            if ok:
                n2c = i32(b, r) if r + 4 <= n else -1
                if n2c == 0:
                    q, n1, n2 = r + 4, n1c, 0
                elif 1 <= n2c <= 40:
                    rr, ok2 = r + 4, True
                    lst = []
                    for _ in range(n2c):
                        if rr + 6 > n: ok2 = False; break
                        L = b[rr]
                        if not (2 <= L <= 6) or rr + 1 + L + 4 > n: ok2 = False; break
                        s = dec(b, rr + 1, rr + 1 + L)
                        if not s or not _faction_anchor_ok(s): ok2 = False; break
                        v = i32(b, rr + 1 + L)
                        if not (0 <= v <= 999999): ok2 = False; break
                        lst.append(s); rr += 1 + L + 4
                    if ok2:
                        q, n1, n2, lst2 = rr, n1c, n2c, lst
        # ---- 入口A：据点列表（n2≥1）在前（入口B 没命中时才试）----
        if q is None:
            n2c = i32(b, p)
            if 1 <= n2c <= 40:
                rr, ok = p + 4, True
                lst = []
                for _ in range(n2c):
                    if rr + 6 > n: ok = False; break
                    L = b[rr]
                    if not (2 <= L <= 6) or rr + 1 + L + 4 > n: ok = False; break
                    s = dec(b, rr + 1, rr + 1 + L)
                    if not s or not _faction_anchor_ok(s): ok = False; break
                    v = i32(b, rr + 1 + L)
                    if not (0 <= v <= 999999): ok = False; break
                    lst.append(s); rr += 1 + L + 4
                if ok:
                    q, n2, lst2 = rr, n2c, lst
                    # 回头看一眼入口B 的 JZ 列表，纯粹为了报告里的 n1 好看
                    e = p - 4
                else:
                    q = None
        if q is None:
            continue
        # ---- 据点列表结束后 0~2 个 i32 之内必须是 [科技][策略] ----
        # 已见两种形态：
        #   Save6/Save8：[i32 0][科技][策略]        ← 固定一个 0 前缀
        #   Save1 基准 ：[i32 0.2(float)][科技][策略] ← 夹一个非零值
        # 所以：第一格是 0 就跳过（那是前缀，不是科技）。
        tech_off = None
        for pad in range(0, 3):
            o = q + pad * 4
            if o + 8 > n: break
            a0, c0 = i32(b, o), i32(b, o + 4)
            if a0 == 0:
                continue
            if 0 < a0 <= 30000000 and 0 <= c0 <= 30000000:
                tech_off = o; break
        if tech_off is None:
            continue
        tech, strat = i32(b, tech_off), i32(b, tech_off + 4)
        # 君主专属策略 id（tech 之后 0x340 内第一个 7 位纯数字串）
        strat_id = None
        sp, slim = tech_off + 8, min(n, tech_off + 0x340)
        while sp < slim - 1:
            L = b[sp]
            if 2 <= L <= 12 and sp + 1 + L <= slim:
                s = dec(b, sp + 1, sp + 1 + L)
                if s and FACTION_STRAT_RE.match(s) and all(32 <= ord(c) < 127 for c in s):
                    strat_id = s; break
                sp += 1; continue
            sp += 1
        tr = faction_treasury_at(b, tech_off, n1=n1)
        out.setdefault(tech_off, {'start': p, 'n1': n1, 'n2': n2, 'lst2': lst2,
                                  'tech_off': tech_off, 'tech': tech, 'strat': strat,
                                  'strat_id': strat_id,
                                  'treasury': (tr['val'] if tr else None),
                                  'treasury_off': (tr['val_off'] if tr else None),
                                  'treasury_form': (tr.get('form') if tr else None),
                                  'wh': (tr['wh'] if tr else None),
                                  'wh_off': (tr['wh_off'] if tr else None)})
        p_floor = tech_off + 4
    return sorted(out.values(), key=lambda x: x['start'])


# 君主称号 → 归属武将名。键是势力块里存的 strat_id（Strategy.json 的 id），
# 值是 HeroTitle.json 里该称号 remark 字段登记的主人。
# 2026-10-20 从游戏 StreamingAssets/Json/{Strategy,HeroTitle}.json 抓取：
#   Strategy.json 的「特殊称呼」+「专人策略」共 52 条，按称号名关联到 HeroTitle.json 的 remark。
# 用途：势力块的 strat_id 就是「这块势力的君主称号」，于是能反查这块属于谁。
# 覆盖验证：Save8 孙权→1014201、Save6 袁绍→1014501、诊断档 刘备→1013901，三档全中。
FACTION_TITLE_OWNER = {
    '1013801': ('曹操',),          # 超世之杰（专人策略）
    '1013901': ('刘备',),          # 大汉皇叔
    '1014001': ('孙坚',),          # 江东猛虎
    '1014101': ('孙策',),          # 江东小霸王
    '1014201': ('孙权',),          # 碧眼儿
    '1003005': ('周瑜',),          # 江东周郎
    '1003905': ('二乔',),          # 国色
    '1014301': ('董卓',),          # 暴虐豺王
    '1014401': (),                 # 八俊（科技型君主，非具体人物）
    '1014501': ('袁绍',),          # 名门孤嗣
    '1014601': ('张鲁',),          # 五米天师令
    '1014701': ('公孙瓒',),        # 白马将军
    '1003605': ('赵云',),          # 常胜将军
    '1014801': (),                 # 发政施仁
    '1014901': (),                 # 广交内安
    '1015001': ('孔融',),          # 建安七子
    '1003405': ('阮籍', '山涛'),   # 竹林七贤
    '1004205': ('张昭', '张纮'),   # 江东二张
    '1004305': ('费祎', '董允', '蒋琬'),   # 蜀汉四相
    '1004405': ('司马八兄弟',),    # 司马八达
    '1015101': (),                 # 治世安民
    '1015201': ('张燕',),          # 飞燕
    '1015301': ('王朗',),          # 政通人和
    '1015401': ('吕布',),          # 飞将
    '1015501': (),                 # 仁政（农业型君主）
    '1015601': ('马超',),          # 西凉之锦
    '1004005': ('马腾', '韩遂'),   # 西凉枭雄
    '1015701': (),                 # 以德服人（外交型君主）
    '1016001': (),                 # 军阀（军事型君主）
    '1016101': (),                 # 豪强（经济型君主）
}


def pick_player_faction(blocks, player_name=None):
    """从势力块里挑出「玩家自己的那块」。

    判据（2026-10-21 修订，七档实测）：
      ⓪ 排除孪生模板块：tech==1000 and strat==0
      ① **官方君主判据**：块的 strat_id 是「该势力君主的称号」，查 FACTION_TITLE_OWNER
         反查归属武将，命中玩家名的那块就是他自己的势力。
         Save8 孙权→碧眼儿、Save6 袁绍→名门孤嗣、诊断档 刘备→大汉皇叔，全中。
      ② **自建君主判据**：strat_id 存在且 **strat > 0** 的块里，据点列表最长、科技最高的。
         2026-10-21 新增「strat > 0」这半条：自建档（玩家自建武将、自定义称号）的
         sid 会借用某个官方称号（Save1 陈平安借了 1014701 白马将军），① 永远落空；
         而干扰块（如 Save1_1010 的 92589/0）特征是 strat 恒为 0。
         实测：Save1=921212/988606、Save1_1010=89042/59564、Save1_1014=920851/990869 全中。
      ③ 兜底：有 strat_id 的块按据点列表最长、科技最高；再兜底据点列表最长。
    ⚠️ 为什么 ② 不能去掉 strat>0：诊断档里「超世之杰(曹操)」那块有 4 个据点，
       「大汉皇叔(刘备)」那块 0 个据点，若没有 strat>0 过滤 + ① 未命中，
       按长度排序会选中曹操那块，读出 740/353（真值 1081/263）。
    ⚠️ 国库金的精确定位未解决（已知真值 Save6=12304、Save8=12357，但偏移不固定、
       候选不唯一），所以**不把国库金当判据**。`treasury` 字段仅供诊断展示。
    player_name 传存档头部第 1 串（玩家真名）；为 None 时跳过 ①。
    返回 (块, 依据) ；挑不出来返回 (None, 原因)。
    块里额外带 `confident`（True=唯一命中、确定；False=多候选里挑的、不确定）。
    2026-10-23：参照「英雄立志傳存檔編輯器」v1.03 的做法 —— 它一旦不能唯一确认
    玩家身份就明确拒绝（背包置灰），而不是猜一个。我们这里不能直接置灰
    （势力资源是核心功能），但必须把「这是猜的」如实告诉界面，让用户自己判断。
    """
    def _tag(blk, why, conf):
        if blk is None:
            return None, why
        out = dict(blk)
        out['confident'] = conf
        return out, why

    if not blocks:
        return None, '没有扫到势力块'
    live = [x for x in blocks
            if not (x['tech'] == 1000 and x['strat'] == 0)]
    if not live:
        live = list(blocks)
    # ① 称号归属 == 玩家名
    if player_name:
        named = [x for x in live
                 if x['strat_id'] and player_name in FACTION_TITLE_OWNER.get(x['strat_id'], ())]
        if len(named) == 1:
            return _tag(named[0],
                        '称号归属「%s」唯一命中（sid=%s）' % (player_name, named[0]['strat_id']),
                        True)
        if named:
            named.sort(key=lambda x: (-len(x['lst2']), -x['tech']))
            return _tag(named[0], ('称号归属「%s」有 %d 个候选，取据点列表最长、科技最高的'
                                   % (player_name, len(named))), False)
    # ② 自建君主：strat_id 存在 且 strat > 0（排除 strat=0 的干扰块）
    weak = [x for x in live if x['strat_id'] and x['strat'] > 0]
    if len(weak) == 1:
        return _tag(weak[0], '有君主专属策略且策略>0（唯一）', True)
    if weak:
        weak.sort(key=lambda x: (-len(x['lst2']), -x['tech']))
        return _tag(weak[0], '有君主专属策略且策略>0（%d 个候选，取据点列表最长、科技最高的）'
                    % len(weak), False)
    # ③ 兜底：放松 strat>0 限制，再退到据点列表最长
    weak2 = [x for x in live if x['strat_id']]
    if len(weak2) == 1:
        return _tag(weak2[0], '有君主专属策略（唯一）', True)
    if weak2:
        weak2.sort(key=lambda x: (-len(x['lst2']), -x['tech']))
        return _tag(weak2[0], '有君主专属策略（%d 个候选，取据点列表最长、科技最高的）'
                    % len(weak2), False)
    live.sort(key=lambda x: -len(x['lst2']))
    return _tag(live[0], '兜底：据点列表最长的块', False)



def find_faction_res(b, is_ruler='auto', player_name=None):
    """势力 / 家族资源，按玩家身份分两条支路。

    is_ruler: True=君主档（只走势力分支） / False=武将档（只走家族分支） /
              'auto' 或 None=头部没认出身份串，两条都试（先势力后家族）。
    player_name: 玩家**真名**（头部第 2 串）。传进来优先用它做称号归属反查；
              不传则退回 header_strings 第 1 串（普通档两者相同，自建档第 1 串是
              立绘预设名，会失配 —— 2026-10-21 修）。

    【不变量】存档头部第 5 个串就是玩家身份：
      · '君主' → 已自立势力：有 势力科技点 + 势力策略点 + 国库金（含势力仓库物品列表）
      · 其它（'一般' / 在野 / 武将）→ 没有国库金，只有家族资源
    旧代码不看身份，一律先跑「科技+策略都 ≥ 10000 且后面有国库」的势力分支，
    于是不自立势力的档会被一段长得像的字节骗到，给出天文数字的假值（比如科技 1723 万）。
    """
    if is_ruler == 'auto' or is_ruler is None:
        role = player_role(b)
        is_ruler = None if role is None else (role == ROLE_RULER)
    if is_ruler is not False:                    # True=君主；None=身份没认出来，也先试一遍
        # 2026-10-19 重写：旧做法是「扫全后半年找 [科技][策略] 都 ≥10000 的 i32 对」，
        # 可新开的君主档科技才几百（袁绍 598 / 孙权 600），直接被跳过，
        # 于是串到毫不相干的数据上读出天文数字（Save6 曾读出科技 15859712）。
        # 现在改成：先按结构签名扫出全部势力块，再用 pick_player_faction 挑玩家的那块。
        blocks = scan_faction_blocks(b)
        if blocks:
            _pn = player_name
            if not _pn:
                # 兜底：HVE 头部读法不行时退回启发式扫描
                try:
                    _hd = head_hve(b) or {}
                    _pn = _hd.get('player')
                    if not _pn:
                        _hs = header_strings(b)
                        _pn = _hs[0][1] if _hs else None
                except Exception:
                    _pn = None
            sel, why = pick_player_faction(blocks, _pn)
            if sel:
                # 国库金：只有形态A（n1>=1，位置固定 tech_off+0x127）才可信。
                # 形态B（自建档/家族档）读到的是垃圾，宁可显示“定位不到”也不能让用户
                # 往垃圾偏移上写值。2026-10-21。
                _ok = (sel.get('treasury_form') == 'A')
                return {'kind': 'faction', 'list_off': sel['start'], 'tech_off': sel['tech_off'],
                        'tech': sel['tech'], 'strat_off': sel['tech_off'] + 4, 'strat': sel['strat'],
                        'treasury_off': (sel.get('treasury_off') if _ok else None),
                        'treasury': (sel['treasury'] if _ok else None),
                        'strat_id': sel['strat_id'],
                        # 2026-10-23：唯一命中才算确定；多候选挑出来的要在界面提示「仅供参考」
                        'confident': bool(sel.get('confident')),
                        'why': why, 'blocks': len(blocks)}
        # 一个势力块都没扫到（极少见）：退回旧逻辑碰碰运气
        lo_v, hi_v = 10000, 30000000
        half = len(b) // 2
        cand_pos = []
        for shift in range(4):                   # 科技/策略不保证 4 字节对齐，四种相位都要扫
            base = half + shift
            cnt = (len(b) - base - 8) // 4
            if cnt <= 0: continue
            allv = struct.unpack_from('<%di' % cnt, b, base)
            for k in range(len(allv) - 1):
                a0, c0 = allv[k], allv[k + 1]
                if lo_v <= a0 <= hi_v and lo_v <= c0 <= hi_v:
                    cand_pos.append(base + k * 4)
        for p in cand_pos:
            if p + 24 > len(b): continue
            a, c = i32(b, p), i32(b, p + 4)
            if skill_run_before(b, p) < 3: continue
            t = find_treasury_near(b, p + 8, min(len(b) - 24, p + 0x600))
            if not t: continue
            return {'kind': 'faction', 'list_off': p, 'tech_off': p, 'tech': a,
                    'strat_off': p + 4, 'strat': c,
                    'treasury_off': t['off'], 'treasury': t['val'], 'why': '旧逻辑兜底'}
    # ------------------------------------------------------------------ 家族
    # 没有自立势力：不存在国库金。家族的科技/策略点只有玩家真正经营过家族之后
    # 才会写进存档，新档里是游戏默认值，存档里根本没有这份数据 —— 这时返回
    # kind='family' 且各项为 None，界面上明确提示，而不是拿假数字糊弄。
    cands = []
    from_ = max(0, len(b) // 2)
    # 2026-10-22 提速：原来 for p in range(from_, len(b)-32) 逐字节试 1150 万次
    # （Save5/Save7 这类家族档因此比君主档慢 0.5s）。score_faction_at 的
    # 第一关就是 1 <= i32(b,p) <= 60，小端下等价于「p 处 4 字节 = 01..3c 00 00 00」
    # —— 直接用正则挑出来，只对它们做完整判定，结果完全等价。
    for _m in _FAMILY_CAND_RE.finditer(b, from_, len(b) - 32):
        p = _m.start()
        c = score_faction_at(b, p)
        if c: cands.append(c)
    if not cands:
        return {'kind': 'family', 'treasury': None, 'treasury_off': None,
                'tech': None, 'tech_off': None, 'strat': None, 'strat_off': None,
                'confident': False,
                'note': '未自立势力，无国库金；家族资源在存档中未定位'}
    cands.sort(key=lambda x: x['list_off'])
    # 玩家的家族块紧跟在城市块之后、NPC 家族表（第一个 [08]GI1+中文名）之前 ——
    # 取这条分界线之前的最后一块，就是玩家自己的家族块。
    g = find_family_head(b)
    if g > 0:
        mine = [c for c in cands if c['list_off'] < g]
        sel = mine[-1] if mine else cands[-1]
    else:
        sel = cands[-1]
    idx = cands.index(sel)
    nxt = cands[idx + 1]['list_off'] if idx + 1 < len(cands) else (g if g > 0 else len(b))
    hi = min(nxt, sel['tech_off'] + 0x4000)
    s = find_family_strategy(b, sel['tech_off'], hi)
    sel['strat_off'] = s['off'] if s else None
    sel['strat'] = s['val'] if s else 0
    sel['fam'] = bool(s)
    # 2026-10-23：「分界线之前的最后一块」是启发式。只有界之前恰好一块候选时才确定。
    _conf = False
    if g > 0:
        _conf = (len([c for c in cands if c['list_off'] < g]) == 1 and bool(s))
    sel.update({'kind': 'family', 'treasury': None, 'treasury_off': None,
                'confident': _conf,
                'note': '未自立势力，无国库金'})
    return sel


def score_faction_at(b, p):
    n = len(b)
    n1 = i32(b, p)
    if not (1 <= n1 <= 60): return None
    q = p + 4
    for _ in range(n1):
        if q + 2 > n: return None
        L = b[q]
        if not (5 <= L <= 14): return None
        s = dec(b, q + 1, q + 1 + L)
        if not s or not JZ_RE.match(s): return None
        q += 1 + L
    e1 = q
    if e1 + 4 > n: return None
    n2 = i32(b, e1)
    if not (0 <= n2 <= 60): return None
    if n2 == 0:
        e2 = e1 + 4
    else:
        r = e1 + 4
        for _ in range(n2):
            if r + 5 > n: return None
            L = b[r]
            if not (3 <= L <= 16): return None
            s = dec(b, r + 1, r + 1 + L)
            if not s: return None
            r += 1 + L + 4
        e2 = r
    tech_off = None
    for k in range(0, 12):
        o = e2 + k * 4
        if o + 8 > n: return None
        if i32(b, o) == 0 and 0 <= i32(b, o + 4) <= 90000000 and 0 <= i32(b, o + 8) <= 90000000:
            tech_off = o + 4; break
    if tech_off is None:
        tech_off = e2 + 8
    score = (5 if n2 > 0 else 0)
    tech = i32(b, tech_off)
    if tech > 10000: score += 3
    return {'kind': 'legacy', 'list_off': p, 'tech_off': tech_off, 'tech': tech,
            'strat_off': tech_off + 4, 'strat': i32(b, tech_off + 4),
            'n1': n1, 'n2': n2, 'score': score}


def find_family_head(b):
    """第一个「[08]GI1xxxxx + 中文名」家族表头（NPC 家族表的起点）。"""
    raw = bytes(b)
    i = 0
    while True:
        i = raw.find(b'\x08GI1', i)
        if i < 0 or i + 14 >= len(b): break
        ok = True
        for k in range(4, 9):
            if not (48 <= b[i + k] <= 57): ok = False; break
        if ok:
            p = i + 9
            L = b[p]
            if 4 <= L <= 30 and p + 1 + L <= len(b):
                nm = dec(b, p + 1, p + 1 + L)
                if nm and re.match(r'^[\u4e00-\u9fff·]{2,}$', nm):
                    return i
        i += 1
    return -1


def find_family_strategy(b, tech_off, hi=None):
    """家族策略点：家族块里「前后都被一大片 0 包夹」的那个孤立 i32。

    实测（Save5 新档）：科技点在 0x15BE94D，策略点 200 在 0x15BF0CD ——
    中间隔着 0x180 字节的 0，前后也都是 0。旧逻辑只要求「前面是 0」，
    还额外要求「附近要有 WJ 成员列表」，结果被同块里一串城市数据（50000）抢走了。
    改成前后都要 0，玩家自己的策略点就是唯一命中。
    """
    end = min(len(b) - 8, hi if hi is not None else tech_off + 0x2000)
    best = None
    for o in range(max(8, tech_off + 8), end):
        v = i32(b, o)
        if not (1 <= v <= 9999999): continue
        if i32(b, o - 4) != 0: continue
        if any(b[k] for k in range(max(0, o - 0x20), o)): continue
        if any(b[k] for k in range(o + 4, min(len(b), o + 0x20))): continue
        best = {'off': o, 'val': v}                  # 取块内最后一个（离块尾最近的）
    return best


# ---------------------------------------------------------------- 城市
# 城市记录的 sec 候选预筛：i32(sec+4) 即「武将列表长度 N」落在 1..60。
# 小端下 N<256 且非 0 等价于后三字节为 0，所以直接匹配 N 字段本身
# `[\x01-\x3c]\x00\x00\x00`（4 字节，长度固定），命中位置 - 4 就是 sec。
# 因为匹配跨度的后 3 字节恒为 0，任意两个命中不会重叠，也不需要前瞻。
_CITY_SEC_CAND_RE = re.compile(rb'[\x01-\x3c]\x00\x00\x00')


def parse_city_list(b, p0, N, extra=4):
    p, items = p0, []
    for _ in range(N):
        if p + 5 >= len(b): return None
        L = b[p]
        if not (3 <= L <= 16): return None
        s = dec(b, p + 1, p + 1 + L)
        if not s or not CITY_ID_RE.match(s): return None
        items.append({'id': s, 'val_off': p + 1 + L, 'val': i32(b, p + 1 + L)})
        p += 1 + L + extra
    return {'end': p, 'items': items}


def scan_cities(b):
    """扫描 76 座城的运行时记录：[资金][军粮][人口][治安f][N][武将列表]…[06]CSxxxx"""
    out = {}
    n = len(b)
    raw = bytes(b)
    # 2026-10-22 提速：原来每个 CS 锚点都从 i-8 往回逐字节扫 0x300=768 次，
    # 1.1 万个锚点 ≈ 860 万次循环 + 每次 2 次 struct.unpack（cProfile:
    # scan_cities 3.85s，是读档第一大项）。
    # 现在每个锚点只在自己窗口 [i-0x300, i-8] 内跑一遍正则，挑出「N 字段落在
    # 1..60」的位置（N 是 i32(sec+4)，小端下 N<256 且非 0 ⇔ 后三字节为 0，
    # 所以直接匹配 4 字节 `[\x01-\x3c]\x00\x00\x00`，命中位置 -4 就是 sec）。
    # 窗口只有 800 字节，比原倒扫还少；顺序仍是倒序，第一个通过全部检查的
    # 就是原来那个 sec —— 结果完全等价（13 档逐档对比验证过）。
    st = 0
    while True:
        i = raw.find(b'\x06CS', st)
        st = i + 1
        if i < 0 or i + 7 > n: break
        try:
            cid = 'CS' + bytes(b[i + 3:i + 7]).decode('ascii')
        except Exception:
            continue
        if not re.match(r'^CS\d{4}$', cid): continue
        # 原来只往前扫 0x148，Save6 的邺资金在 CS1013 前 0x1B6 处，刚好落在窗口外，
        # 于是整座城被漏掉（57/76）。实测 0x1B6 属正常范围，放宽到 0x300。
        lo = i - 0x300
        if lo < 12: continue
        endp = min(i - 8, n - 4) + 4
        secs = [m.start() - 4 for m in _CITY_SEC_CAND_RE.finditer(b, lo + 4, endp)]
        for sec in reversed(secs):
            if sec < lo: continue
            N = i32(b, sec + 4)
            f = f32(b, sec)
            if not (0 < f <= 1000): continue
            money, food, pop = i32(b, sec - 12), i32(b, sec - 8), i32(b, sec - 4)
            # 军粮上限原来卡在 3,000,000，把军粮多的城（如邪马台 3,158,498）整条排除了，
            # 导致城市列表里缺城（CS1066 邪马台就是这样被漏掉的）。放宽到 2000 万。
            if not (0 <= money <= 90000000 and 0 <= food <= 20000000 and 0 <= pop <= 9000000): continue
            pl = None
            for off in range(4, 21):
                # 预筛（2026-10-22）：parse_city_list 第一关就是「首字节是 3..16 的
                # 长度」，不符当场 return None。原来 17 个 off × 每城若干 sec 会白白
                # 调 135 万次函数（cProfile 实测），这里先看字节挡掉，语义不变。
                L0 = b[sec + off]
                if not (3 <= L0 <= 16): continue
                t = parse_city_list(b, sec + off, N)
                if not t: continue
                # 2026-10-22 提速：原来 for kk in range(...) 逐字节找 'CS'，
                # 每城 320 次纯 Python 循环 × 1 万多次调用。改成 C 层 find，
                # 语义等价（从 t['end'] 起、只认第一个命中，且必须等于 cid）。
                kk = raw.find(b'\x06CS', t['end'], min(t['end'] + 0x140, n - 7))
                hit = False
                if kk >= 0:
                    got = 'CS' + bytes(b[kk + 3:kk + 7]).decode('ascii', 'ignore')
                    hit = (got == cid)
                if hit:
                    pl = t; break
            if not pl: continue
            score = N * 10000000 + pop
            prev = out.get(cid)
            if (not prev) or score > prev['score']:
                out[cid] = {'cid': cid, 'sec': sec, 'money': money, 'food': food, 'pop': pop,
                            'security': f, 'N': N, 'score': score}
            break
    return out


# ---------------------------------------------------------------- 宠物
PET_LEAD = 6


def pet_str(b, p):
    if p >= len(b): return None
    L = b[p]
    if L > 0x80: return None
    s = dec(b, p + 1, p + 1 + L)
    return None if s is None else {'s': s, 'next': p + 1 + L}


PET_ID_RE = re.compile(r'^P[0-9A-Za-z_]{2,15}$')


def parse_pet_rec(b, p):
    """一条宠物记录：[len]Pxxxxx + 4 段串(编号/名字/空/族) + 8 个 i32。"""
    if p + 4 > len(b): return None
    L0 = b[p]
    if not (3 <= L0 <= 16): return None
    if b[p + 1] != 80: return None                       # 'P'
    pid = dec(b, p + 1, p + 1 + L0)
    if not pid or not PET_ID_RE.match(pid): return None
    q = p + 1 + L0
    a = pet_str(b, q)
    if not a or not a['s'].isdigit() or not (1 <= len(a['s']) <= 6): return None
    q = a['next']
    nm = pet_str(b, q)
    if not nm: return None
    q = nm['next']
    e0 = pet_str(b, q)
    if not e0: return None
    q = e0['next']
    fa = pet_str(b, q)
    if not fa: return None
    q = fa['next']
    if q + 32 > len(b): return None
    v = list(struct.unpack_from('<8i', b, q))
    if not (1 <= v[0] <= 100): return None
    if not (0 <= v[1] <= 100000): return None
    if not (0 <= v[2] <= 10000000): return None
    if not (0 <= v[4] <= 3000 and 0 <= v[5] <= 3000 and 0 <= v[6] <= 3000): return None
    if not (0 <= v[7] <= 5000000): return None
    return {'id': pid, 'num': a['s'], 'name': nm['s'], 'fam': fa['s'], 'off': p,
            'field_off': q, 'lv_limit': v[0], 'month_cost': v[1], 'value': v[2],
            'atk': v[4], 'dfn': v[5], 'spd': v[6], 'hp': v[7]}


def pet_next_off(b, q):
    lim = min(len(b) - 9, q + 0x400)
    for d in range(8, max(8, lim - q)):
        p = q + d
        if p + 1 >= len(b) or b[p + 1] != 80: continue
        L = b[p]
        if not (3 <= L <= 16): continue
        if any(b[p - k] != 0 for k in range(1, PET_LEAD + 1)): continue
        if not parse_pet_rec(b, p): continue
        return p
    return -1


def find_pet_list(b):
    """定位玩家宠物列表：找 [count][n×宠物记录]，取只数最多的那个。"""
    best = None
    raw = bytes(b)
    st = 0
    while True:
        j = raw.find(b'P', st)
        if j < 0: break
        st = j + 1
        p = j - 1
        if p < 0 or not parse_pet_rec(b, p): continue
        count, co = i32(b, p - 4), p - 4
        if not (1 <= count <= 30):
            count, co = i32(b, p - 5), p - 5
        if not (1 <= count <= 30): continue
        recs, q, ok = [], p, True
        for k in range(count):
            rr = parse_pet_rec(b, q)
            if not rr: ok = False; break
            recs.append(rr)
            if k == count - 1: break
            nxt = pet_next_off(b, q)
            if nxt < 0: ok = False; break
            q = nxt
        if not ok or len(recs) != count: continue
        if not best or count > best['count']:
            best = {'count': count, 'count_off': co, 'list_start': p, 'recs': recs, 'list_end': q}
    return best


def pet_rec_end(b, off):
    """一条宠物记录的结束位置（尾部连续 0 填充的起点）。"""
    lim = min(len(b) - 8, off + 0x600)
    i = off + 8
    while i < lim:
        if b[i] == 0:
            j = i
            while j < lim and b[j] == 0:
                j += 1
            if j - i >= PET_LEAD:
                ok = False
                if j + 1 < len(b) and b[j + 1] == 80 and parse_pet_rec(b, j):
                    ok = True
                if not ok and j + 7 <= len(b) and b[j + 4] == 6 and b[j + 5] == 67 and b[j + 6] == 83:
                    n = i32(b, j)
                    if 10 <= n <= 2000:
                        ok = True
                if ok:
                    return i
            i = j
        else:
            i += 1
    return -1


_HAN = re.compile(r'[\u3400-\u9fff]')
_ASCII = re.compile(r'^[\x20-\x7e]+$')


def pet_lang_start(b, frm, end):
    """尾部「多语言名块」的起点：[简中][英文][繁中][韩文] 四段，正好抵到 end。"""
    for p in range(end - 1, frm, -1):
        q, ss, ok = p, [], True
        while q < end and len(ss) < 4:
            L = b[q]
            if L > 0x60 or q + 1 + L > end:
                ok = False; break
            t = dec(b, q + 1, q + 1 + L)
            if t is None:
                ok = False; break
            ss.append(t); q += 1 + L
        if ok and q == end and len(ss) == 4 and _HAN.search(ss[0]) and _ASCII.match(ss[1]) and _HAN.search(ss[2]):
            return p
    return -1


def _put_str(arr, s):
    e = str('' if s is None else s).encode('utf-8')
    arr.append(len(e))
    arr.extend(e)


def copy_pet_unit(b, t, new_num):
    """原样复制一条宠物记录，只把「编号」换成 new_num（长度必须一致）。"""
    end = pet_rec_end(b, t['off'])
    if end < 0: raise RuntimeError('模板宠物记录边界未找到')
    unit = bytearray(b[t['off']:end])
    L0 = unit[0]
    q = 1 + L0
    old = pet_str(unit, q)
    if not old: raise RuntimeError('模板编号串定位失败')
    nb = new_num.encode('utf-8')
    if len(nb) != len(old['s'].encode('utf-8')):
        raise RuntimeError('宠物编号位数会变化，暂不支持')
    unit[q] = len(nb)
    unit[q + 1:q + 1 + len(old['s'].encode('utf-8'))] = nb
    return bytes(unit)


def make_pet_unit(b, t, tgt_id, new_num, pet_cat):
    """以 t 为模板造一条新品种的宠物记录（品种来自物品库 PET_CAT）。"""
    ue = pet_rec_end(b, t['off'])
    if ue < 0: raise RuntimeError('模板宠物记录边界未找到')
    ls = pet_lang_start(b, t['field_off'], ue)
    if ls < 0: raise RuntimeError('没能定位模板宠物的多语言名块')
    info = pet_cat.get(tgt_id)
    if not info: raise RuntimeError('物品库里没有品种 %s，请先跑一次「更新物品库」' % tgt_id)
    def gi(idx, dflt=0):
        try:
            return int(info[idx])
        except Exception:
            return dflt
    head = bytearray()
    _put_str(head, tgt_id)
    _put_str(head, new_num)
    _put_str(head, info[0] or t['name'])
    _put_str(head, '')
    _put_str(head, (info[4] if len(info) > 4 and info[4] else t['fam']))
    mid = bytearray(b[t['field_off']:ls])
    def set_i(off, val):
        if off + 4 <= len(mid):
            struct.pack_into('<i', mid, off, max(0, int(round(val)) or 0))
    set_i(0x00, gi(6, t['lv_limit']))
    set_i(0x04, gi(7, t['month_cost']))
    set_i(0x08, gi(8, t['value']))
    set_i(0x10, gi(9)); set_i(0x14, gi(10)); set_i(0x18, gi(11)); set_i(0x1c, gi(12))
    lang = bytearray()
    _put_str(lang, info[0] or t['name'])
    _put_str(lang, (info[1] if len(info) > 1 and info[1] else (info[0] or t['name'])))
    _put_str(lang, (info[2] if len(info) > 2 and info[2] else (info[0] or t['name'])))
    _put_str(lang, (info[3] if len(info) > 3 and info[3] else (info[0] or t['name'])))
    body = bytes(head) + bytes(mid) + bytes(lang)
    return bytes(PET_LEAD) + body


# ---------------------------------------------------------------- 存档对象
class SaveFile:
    def __init__(self, data, catalog=None, npc_names=None):
        self.raw = bytearray(data)
        b = self.raw
        self.ver = u32(b, 0)
        self.slot = u32(b, 4)
        self.strings = header_strings(b)
        self.money_off, self.money, self.money_copies = money_copies(b)
        # 灵蕴 = 玩家个人资源（独立于势力/家族块）
        # 2026-10-19 三档实测锚点 [i32 -251658240][i32 33554392][i32 0][灵蕴]，全档唯一。
        self.lingyun_off, self.lingyun = find_lingyun(b)
        self.role = player_role(b)
        self.is_ruler = (self.role == ROLE_RULER)
        # 头部两串（HVE CharacterScanner.Detect 的读法，2026-10-21）：
        #   save_name   = 第 1 串 = **立绘/存档名**：普通档是武将名（Save7='钟会'），
        #                 自建档是立绘预设名（Save1='随机男025'）→ 用来匹配「记录内 Name」
        #   player_name = 第 2 串 = **玩家真名**：自建档才是「陈平安」这种
        # 旧代码把第 1 串当玩家真名，自建君主拿它去查称号归属表当然查不到。
        _hd = head_hve(b) or {}
        self.save_name = _hd.get('save') or (self.strings[0][1] if self.strings else None)
        self.player_name = _hd.get('player') or (
            self.strings[1][1] if len(self.strings) > 1 else self.save_name)
        self.heroes, self.base_hero_n = parse_heroes(b, npc_names)
        # 玩家自己那条武将记录：记录内 Name == save_name，必须唯一命中才算数
        self.player = mark_player_hero(self.heroes, self.save_name)
        self.cities = scan_cities(b)
        self.title_ids = set()
        for k in (catalog or {}):
            if k.startswith('HTC'):
                self.title_ids.add(k[3:])
        # 背包先行：资产块金钱 = 背包起点 - 4，称号列表要用它当锚点
        self.bag = find_bag(b, self.money, self.heroes[0] if self.heroes else None)
        self.money2 = self.bag.get('money2') if self.bag else None
        self.title_lists = find_title_lists(b, self.money2, self.title_ids)
        self.titles = self.title_lists[0] if self.title_lists else None
        # 每个武将自己的称号：取记录内的**第一条**（实测就是游戏面板显示的那条）
        self.hero_titles = {}       # hero_id -> {'count_off','start','end','ids'}
        self.hero_title_edits = {}  # hero_id -> [tid, ...]
        if self.title_ids:
            for h in self.heroes:
                tl = scan_hero_titles(b, h, self.title_ids)
                if tl:
                    self.hero_titles[h['id']] = tl[0]
        # 身份串没认出来时传 None，让引擎两条支路都试一遍
        self.faction = find_faction_res(b, self.is_ruler if self.role else None,
                                        self.player_name)
        self.pets = find_pet_list(b)
        self.pet_cat = (catalog or {}).get('__PET_CAT__') or {}
        # 当前地点 / 城市映射
        self.place = None
        self.city_id = (catalog or {}).get('__CITY_ID__') or {}
        self.city_name = (catalog or {}).get('__CITY_NAME__') or {}
        for _, s in self.strings:
            if s in self.city_id:
                self.place = s; break
        # 给所有武将定位六维（按「记录区间归属」定块，见 locate_six）
        _raw = bytes(b)                      # 只拷一次，别在循环里反复拷 24MB
        _ancs = sorted(h['anc'] for h in self.heroes)
        for h in self.heroes:
            if h.get('six_off') is not None:
                continue
            loc = locate_six(b, h, self.place if h['kind'] == 'player' else None,
                             self.city_id, _raw, _ancs)
            if loc:
                h['six_off'] = loc['off']
                h['six_cs'] = loc['cs']
        # 待写改动
        self.edits = {}                 # 偏移 -> ('i32'|'f32'|'u8', 值)
        self.bag_dirty = False
        self.titles_dirty = False
        self.bag_sig = ser_bag(self.bag['groups']) if self.bag else None
        self.titles_sig = ser_title_list(self.titles['ids']) if self.titles else None
        self.pet_adds = []              # [{'tgt': 品种id, 'tmpl': 模板宠物下标}]
        self.char_adds = {}             # 武将下标 -> [性格id, ...]（旧的“末尾追加”写法，保留兼容）
        self.char_edits = {}            # 武将下标 -> [(性格id, 等级), ...]：整段重建（和称号同一套路）

    # ---- 便捷读取
    @property
    def money_value(self):
        return self.money

    def summary(self):
        bag_n = sum(len(g['items']) for g in self.bag['groups']) if self.bag else 0
        f = self.faction or {}
        return {
            'ver': self.ver, 'slot': self.slot, 'place': self.place,
            'money': self.money, 'heroes': len(self.heroes), 'bag': bag_n,
            'tech': f.get('tech'), 'strat': f.get('strat'), 'treasury': f.get('treasury'),
            'titles': len(self.titles['ids']) if self.titles else 0,
            'cities': len(self.cities),
        }

    # ---- 写回
    def build(self):
        """应用全部改动，返回 (新字节, 变更清单)。"""
        work = bytearray(self.raw)
        ch = []
        for off, (typ, val) in self.edits.items():
            if typ == 'i32': put_i32(work, off, val)
            elif typ == 'f32': put_f32(work, off, val)
            elif typ == 'u8': put_u8(work, off, val)
        if self.edits:
            ch.append('定点改写 %d 处' % len(self.edits))

        # 结构变更：从后往前替换，避免偏移漂移
        splices = []
        if self.bag_dirty and self.bag:
            splices.append((self.bag['start'], self.bag['end'], ser_bag(self.bag['groups']),
                            '背包重建（%d 组 / %d 件）' % (len(self.bag['groups']),
                                                       sum(len(g['items']) for g in self.bag['groups']))))
        # 武将称号：整段重建（含数量前缀）
        for hid, ids in sorted(self.hero_title_edits.items()):
            info = self.hero_titles.get(hid)
            if not info or not ids:
                continue
            st, en = info['start'] - 4, info['end']
            blob = struct.pack('<i', len(ids)) + b''.join(
                bytes([len(x)]) + x.encode('ascii') for x in ids)
            if bytes(self.raw[st:en]) == blob:
                continue
            splices.append((st, en, blob,
                            '重建 %s 的武将称号（%d 个）' % (hid, len(ids))))
        if self.titles_dirty and self.titles:
            splices.append((self.titles['start'], self.titles['end'], ser_title_list(self.titles['ids']),
                            '称号列表重建（%d 条）' % len(self.titles['ids'])))
        # 人物性格：整段重建（和称号列表同一套思路 —— 读出来 → 改 → 整段换回去）
        # ⚠️ 性格段**前面 4 字节是「性格数量」**，必须一起改！否则游戏按旧数量读、
        #    多读/少读几组，直接报 "An item with the same key has already been added"
        #    （小K 2026-10-17 加鱼水之欢后进不去游戏，就是踩的这个）。
        #    实测 391/395 名武将的「段前 4 字节 == 组数」，所以只在确认时才连它一起换。
        for idx, pairs in sorted(self.char_edits.items()):
            if not pairs:
                continue
            if not (0 <= idx < len(self.heroes)):
                continue
            h = self.heroes[idx]
            cell = find_character_cell(self.raw, h)
            if not cell:
                continue
            st, en = cell[0]['off'], cell[-1]['off'] + 8
            cnt_off = st - 4
            old_n = struct.unpack_from('<i', self.raw, cnt_off)[0] if cnt_off >= 0 else -1
            if old_n == len(cell):
                blob = struct.pack('<i', len(pairs)) + ser_char_list(pairs)
                st = cnt_off                     # 连「性格数量」一起写
            else:
                blob = ser_char_list(pairs)      # 认不出数量字段就只换数据段（保守）
            if bytes(self.raw[st:en]) == blob:
                continue                         # 内容没变就不动这段
            splices.append((st, en, blob,
                            '重建 %s 的性格（%d 个）' % (h.get('name') or h['id'], len(pairs))))
        splices.sort(key=lambda s: -s[0])
        for st, en, blob, desc in splices:
            work[st:en] = blob
            ch.append(desc)
        # 自检：拿「原始字节 + 定点改写 + 同样的替换」重算一遍，必须和输出逐字节一致。
        # 只有被替换的区段允许变化，其余任何字节动过都会在这里被抓出来（写坏存档的最后一道闸）。
        expect = bytearray(self.raw)
        for off, (typ, val) in self.edits.items():
            if typ == 'i32': put_i32(expect, off, val)
            elif typ == 'f32': put_f32(expect, off, val)
            elif typ == 'u8': put_u8(expect, off, val)
        for st, en, blob, desc in splices:
            expect[st:en] = blob
        if len(expect) != len(work):
            raise RuntimeError('自检失败：输出长度不符（%d ≠ %d），已中止' % (len(work), len(expect)))
        if bytes(expect) != bytes(work):          # 快速比对（C 速度）；只有不一致时才去找偏移
            for i in range(len(expect)):
                if expect[i] != work[i]:
                    raise RuntimeError('自检失败：第 %#x 字节与预期不一致，已中止（不会写出）' % i)
            raise RuntimeError('自检失败：内容与预期不一致，已中止')
        out = bytes(work)
        # ---- 宠物添加：放在最后，基于新缓冲重新定位宠物列表（会改变文件长度）----
        if self.pet_adds and self.pets:
            pl = find_pet_list(out)
            if not pl:
                raise RuntimeError('宠物列表重定位失败，无法添加宠物')
            if len(pl['recs']) != len(self.pets['recs']):
                raise RuntimeError('宠物列表与载入时不一致，请重新载入存档再操作')
            end = pet_rec_end(out, pl['recs'][-1]['off'])
            if end < 0:
                raise RuntimeError('宠物列表结束位置未找到，拒绝添加')
            max_num = 0
            for r in pl['recs']:
                try:
                    n = int(r['num'])
                    if n > max_num: max_num = n
                except Exception:
                    pass
            pieces, names = [], []
            for a in self.pet_adds:
                ti = a.get('tmpl', 0)
                if not (0 <= ti < len(pl['recs'])):
                    raise RuntimeError('待添加的模板宠物不存在')
                t = pl['recs'][ti]
                max_num += 1
                nn = str(max_num)
                if len(nn) != len(t['num']):
                    raise RuntimeError('宠物编号会从 %s 变成 %s（位数变了），先少加几只'
                                       % (t['num'], nn))
                tid = a.get('tgt') or t['id']
                if tid == t['id']:
                    pieces.append(copy_pet_unit(out, t, nn))
                else:
                    pieces.append(make_pet_unit(out, t, tid, nn, self.pet_cat))
                names.append((self.pet_cat.get(tid) or [tid])[0])
            blob = b''.join(pieces)
            nb = bytearray(out[:end]) + bytearray(blob) + bytearray(out[end:])
            put_i32(nb, pl['count_off'], pl['count'] + len(self.pet_adds))
            out = bytes(nb)
            ch.append('宠物：添加 %d 只（%s）；%d → %d 只，文件 +%d 字节'
                      % (len(self.pet_adds), '、'.join(names), len(pl['recs']),
                         len(pl['recs']) + len(self.pet_adds), len(blob)))
        # 回读校验
        chk = SaveFile(out, {'__CITY_ID__': self.city_id, '__CITY_NAME__': self.city_name,
                             **{('HTC' + t): 1 for t in self.title_ids}})
        if self.bag_dirty:
            if not chk.bag or sum(len(g['items']) for g in chk.bag['groups']) !=\
                    sum(len(g['items']) for g in self.bag['groups']):
                raise RuntimeError('回读校验失败：背包条数不符')
        if self.titles_dirty:
            if not chk.titles or len(chk.titles['ids']) != len(self.titles['ids']):
                raise RuntimeError('回读校验失败：称号条数不符')
        if self.pet_adds:
            if not chk.pets or chk.pets['count'] != len(self.pets['recs']) + len(self.pet_adds):
                raise RuntimeError('回读校验失败：宠物条数不符')
        return out, ch

    def save_as(self, path):
        data, ch = self.build()
        with open(path, 'wb') as f:
            f.write(data)
        return len(data), ch
