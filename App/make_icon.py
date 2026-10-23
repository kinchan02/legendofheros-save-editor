# -*- coding: utf-8 -*-
"""生成修改器图标：DeepSeek 鲸鱼娘（chibi 版）

2026-10-23 新增。纯 Pillow 绘制，先 4 倍超采样再缩回来，保证小尺寸下边缘不毛。
输出：
  assets/icon.ico   多尺寸 ico（16/24/32/48/64/128/256），给 Nuitka 与 tkinter 用
  assets/icon.png   256x256 png，方便预览
"""
import os
import math
from math import cos, sin
from PIL import Image, ImageDraw, ImageFilter

S = 4                      # 超采样倍数
BASE = 256
W = BASE * S               # 1024

BLUE_D = (52, 76, 214)
BLUE = (77, 107, 254)      # DeepSeek 蓝 #4D6BFE
BLUE_M = (98, 126, 255)
FIN = (150, 175, 255)
FIN_D = (120, 148, 246)
SKIN = (255, 253, 250)
SKIN_SH = (223, 232, 250)
INK = (26, 34, 74)
PINK = (255, 150, 175)
WHITE = (255, 255, 255)
SPOUT = (176, 224, 255)

# 主形体圆心与半径（略微左移，给右边尾巴腾地方）
CX = int(W * 0.455)
CY = int(W * 0.525)
R = int(W * 0.315)


def rounded_mask(size, radius):
    m = Image.new('L', (size, size), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size - 1, size - 1],
                                        radius=radius, fill=255)
    return m


def vgrad(size, top, bottom):
    img = Image.new('RGB', (1, size))
    d = ImageDraw.Draw(img)
    for y in range(size):
        t = y / max(1, size - 1)
        d.point((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    return img.resize((size, size), Image.BICUBIC)


def pt(fx, fy):
    """按 0..1 归一化坐标取点，方便整体缩放。"""
    return (int(W * fx), int(W * fy))


def draw_tail(img):
    """鲸鱼尾巴：从身体右腰伸出，末端劈成上下两叶。

    踩过的坑（别重复）：
    1. 位置不能落在两腮鳍的高度（CY+0.30R 起）—— 会被右腮鳍整个盖住。
    2. 位置也不能压到右下圆角 —— 圆角半径 0.225W，y 太靠下时右侧已被裁掉。
    3. 尾巴白色 SKIN 会和白身体融成一块，只看得见描边留下的细线。
    4. 深蓝 FIN_D 填充和背景蓝 (77,107,254) 太近，同样糊成一片。
    5. polygon 三点画叶片极易退化成细长条；pieslice 扇形又像鱼鳍。
       最终用「独立图层画椭圆叶片 → rotate 旋转 → 合成」，形状稳定且像鲸尾。
    """
    root = (CX + int(R * 0.52), CY + int(R * 0.16))
    mid = (CX + int(R * 0.86), CY + int(R * 0.06))
    stem = int(R * 0.28)
    lw = max(2, int(R * 0.046))

    # 尾柄：深蓝描边垫底，再填白色
    lay = Image.new('RGBA', img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    d.line([root, mid], fill=BLUE_D, width=stem + lw * 2)
    d.line([root, mid], fill=WHITE, width=stem)

    # 两片尾叶：各自在独立小图层里画一个椭圆，旋转后再贴回去
    # 深蓝当描边、白色当叶面 —— 白色对蓝背景醒目，深蓝边对白身体也能分开
    leaf_l = int(R * 0.58)      # 叶长
    leaf_w = int(R * 0.38)      # 叶宽
    for angle in (-30, 30):
        pad = leaf_l + leaf_w
        tile = Image.new('RGBA', (pad * 2, pad * 2), (0, 0, 0, 0))
        td = ImageDraw.Draw(tile)
        cx0, cy0 = pad, pad
        # 椭圆沿 +x 方向，从 mid 向外长
        td.ellipse([cx0, cy0 - leaf_w // 2,
                    cx0 + leaf_l, cy0 + leaf_w // 2],
                   fill=BLUE_D)
        td.ellipse([cx0 + lw * 1.4, cy0 - leaf_w // 2 + lw * 1.4,
                    cx0 + leaf_l - lw * 1.4, cy0 + leaf_w // 2 - lw * 1.4],
                   fill=WHITE)
        tile = tile.rotate(angle, resample=Image.BICUBIC, center=(cx0, cy0))
        lay.alpha_composite(tile, (mid[0] - cx0, mid[1] - cy0))
    return Image.alpha_composite(img, lay)


def draw_icon():
    img = Image.new('RGBA', (W, W), (0, 0, 0, 0))

    # ---------- 背景：圆角方块 + 竖直渐变 + 右上高光 ----------
    bg = vgrad(W, (132, 160, 255), BLUE_D).convert('RGBA')
    glow = Image.new('RGBA', (W, W), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse(
        [W * 0.44, -W * 0.30, W * 1.30, W * 0.62], fill=(255, 255, 255, 42))
    bg = Image.alpha_composite(bg, glow)
    img.paste(bg, (0, 0), rounded_mask(W, int(W * 0.225)))

    # ---------- 尾巴（在身体后面） ----------
    img = draw_tail(img)
    d = ImageDraw.Draw(img, 'RGBA')

    # ---------- 身体底阴影 ----------
    d.ellipse([CX - R, CY - R + int(R * 0.10), CX + R, CY + R + int(R * 0.08)],
              fill=SKIN_SH)

    # ---------- 身体 ----------
    d.ellipse([CX - R, CY - R, CX + R, CY + R], fill=SKIN)

    # ---------- 头顶蓝帽（鲸鱼背） ----------
    cap_r = int(R * 1.04)
    cap = [CX - cap_r, CY - int(R * 1.08), CX + cap_r, CY + int(R * 0.42)]
    d.ellipse(cap, fill=BLUE)
    # 用肤色盖掉下半，只留下上半圈帽子
    d.ellipse([cap[0] - 4 * S, CY - int(R * 0.62), cap[2] + 4 * S, cap[3] + int(R * 0.20)],
              fill=SKIN)
    # 帽沿深蓝描边
    d.arc([cap[0] + 3 * S, cap[1] + 3 * S, cap[2] - 3 * S, cap[3] - 3 * S],
          start=192, end=348, fill=BLUE_D, width=int(R * 0.055))
    # 帽子高光
    d.ellipse([CX - int(R * 0.52), CY - int(R * 0.96),
               CX - int(R * 0.02), CY - int(R * 0.70)],
              fill=(255, 255, 255, 58))

    # ---------- 头顶喷水（三滴） ----------
    for (fx, fy, r, a) in ((-0.115, 0.215, 0.030, 205),
                           (0.0, 0.140, 0.042, 255),
                           (0.115, 0.215, 0.030, 205)):
        xx = CX + int(W * fx)
        yy = int(W * fy)
        rr = int(W * r)
        d.ellipse([xx - rr, yy - rr, xx + rr, yy + rr], fill=SPOUT + (a,))

    # ---------- 两腮鳍（小手） ----------
    for sx in (-1, 1):
        fx = CX + sx * int(R * 1.02)
        d.ellipse([fx - int(R * 0.24), CY + int(R * 0.30),
                   fx + int(R * 0.24), CY + int(R * 0.72)], fill=FIN)

    # ---------- 眼睛 ----------
    for sx in (-1, 1):
        ex = CX + sx * int(R * 0.44)
        ey = CY + int(R * 0.02)
        ew = int(R * 0.27)
        eh = int(R * 0.35)
        d.ellipse([ex - ew, ey - eh, ex + ew, ey + eh], fill=INK)
        # 主高光
        d.ellipse([ex - int(ew * 0.62), ey - int(eh * 0.62),
                   ex + int(ew * 0.10), ey - int(eh * 0.06)], fill=WHITE)
        # 次高光（右下小点）
        d.ellipse([ex + int(ew * 0.28), ey + int(eh * 0.22),
                   ex + int(ew * 0.66), ey + int(eh * 0.66)], fill=(255, 255, 255, 160))

    # ---------- 腮红（模糊处理） ----------
    blush = Image.new('RGBA', (W, W), (0, 0, 0, 0))
    bd = ImageDraw.Draw(blush)
    for sx in (-1, 1):
        bx = CX + sx * int(R * 0.72)
        by = CY + int(R * 0.30)
        bd.ellipse([bx - int(R * 0.22), by - int(R * 0.12),
                    bx + int(R * 0.22), by + int(R * 0.12)], fill=PINK + (118,))
    blush = blush.filter(ImageFilter.GaussianBlur(int(R * 0.07)))
    img = Image.alpha_composite(img, blush)
    d = ImageDraw.Draw(img, 'RGBA')

    # ---------- 嘴 ----------
    mw = int(R * 0.17)
    my = CY + int(R * 0.30)
    d.arc([CX - mw, my - int(R * 0.10), CX + mw, my + int(R * 0.10)],
          start=18, end=162, fill=INK, width=int(R * 0.040))

    return img


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    out = os.path.join(here, 'assets')
    if not os.path.isdir(out):
        os.makedirs(out)
    big = draw_icon()
    png = big.resize((256, 256), Image.LANCZOS)
    png.save(os.path.join(out, 'icon.png'))
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    png.save(os.path.join(out, 'icon.ico'), format='ICO', sizes=sizes)
    print('写出：', os.path.join(out, 'icon.ico'))
    print('写出：', os.path.join(out, 'icon.png'))


if __name__ == '__main__':
    main()
