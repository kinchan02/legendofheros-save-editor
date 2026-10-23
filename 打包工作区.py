# -*- coding: utf-8 -*-
"""把工作区打包成一份「换台电脑也能继续干活」的压缩包。

只带：源码 / 测试脚本 / 文档 / 记忆 / 当前测试真正依赖的存档 fixture / 编译好的 exe。
不带：几百 MB 的历史临时存档、PyInstaller 构建中间目录、旧版 exe。
所有脚本里的路径都是相对自身的（HERE/ROOT），解压到任意位置都能跑测试。
"""
import os
import time
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, '英雄立志传修改器_工作区_%s.zip' % time.strftime('%Y%m%d'))

# 当前测试套件真正依赖的存档（其它历史档不带，省 700MB）
FIXTURES = [
    '势力资源/Save1_1014_基准.dat',          # smoketest 主存档（君主档，76 城）
    '新档诊断/Save5_新档.dat',               # smoketest 新档用例（家族资源 / 背包锚点）
    '删除重复武将/Save2_最新_1008.dat',
    '删除重复武将/Save2_基准.dat',
    '城市属性/Save3_基准_1009.dat',
    '势力资源/Save0_最新_2219.dat',
    '势力资源/Save0_势力_1041.dat',
    '宠物/Save1_宠物_1011.dat',
    '主角六维/Save0_1012_2009.dat',
    '主角六维/Save1_1012_2009.dat',
    '主角六维/Save0_1013_0102.dat',
    '主角六维/Save1_1013_0103.dat',
    '主角六维/Save0_1013_2022.dat',
    '主角六维/Save0_1013_2126.dat',
    '主角六维/Save1_1013_2224.dat',
    '_逆向分析/_test_add.dat',
]

SKIP_DIR_PARTS = ('_build', '_build2', '__pycache__', '.git', '_旧版', '_tmp_dist')
SKIP_EXT = ('.pyc',)          # 注意别把 App/诊断包_示例.zip、MOD整合/*.zip 排除掉
# 整目录带走（脚本/文档/资源），但不含 *.dat
WHOLE_DIRS = ['App', '存档修改器', '_逆向分析', 'NewNPC编辑器', 'MOD整合',
              'backup_NewNPC_20261007', '.workbuddy', '快照', 'exe', 'exe原生']
EXES = []   # exe 已由 WHOLE_DIRS 的 'exe' / 'exe原生' 整目录带上了，这里不用重复加

README = """英雄立志传·三国志 存档修改器 —— 工作区（换机 debug 包）
=========================================================

解压后目录结构（脚本路径都是相对的，放任何位置都能跑）：

  App/                     源码 + 测试
    savecore.py            存档解析/写回引擎
    三国存档修改器.py       tkinter 界面
    smoketest_app.py       回归测试（92 项）
    selftest.py            引擎自测
    游戏路径.txt           游戏安装目录（换机后要改！）
  势力资源/ 新档诊断/ 等    smoketest 依赖的存档样本（保持原路径）
  物品库.js                在 exe原生/ 和 exe/ 各一份（selftest 读 exe原生/ 的）
  exe原生/                 编译好的 exe + spec + PyInstaller 配置
  打包说明.md              打包 / 重编译步骤
  快照/                    Save4/Save5 的定位基线

在新电脑上跑测试：
  python App/smoketest_app.py
  （需要 Python 3.8，PyInstaller 重编译见 打包说明.md）

注意：
  1. 游戏路径：本机是 E:/SteamLibrary/steamapps/common/LegendOfHeros，
     换机后改 App/游戏路径.txt 和 exe原生/游戏路径.txt。
  2. 真实存档目录：%USERPROFILE%/AppData/LocalLow/FreeWing/ThreeKingdom/SaveData/
     自建武将定义文件 NewNPC 也在这个目录里。
  3. 已知遗留：君主档的势力资源（科技点/策略点/国库金）定位不准，
     一般档的家族资源是准的。详见 .workbuddy/memory/ 里的记录。
"""


def add(z, path, arcname):
    try:
        z.write(path, arcname)
        return os.path.getsize(path)
    except Exception as e:
        print('  [跳过] %s (%s)' % (arcname, e))
        return 0


def main():
    total_raw = 0
    n = 0
    with zipfile.ZipFile(OUT, 'w', zipfile.ZIP_DEFLATED) as z:
        # README 放最前面
        z.writestr('README_换机说明.txt', README)
        n += 1
        for d in WHOLE_DIRS:
            base = os.path.join(ROOT, d)
            if not os.path.isdir(base):
                continue
            for dp, dn, fs in os.walk(base):
                if any(p in dp for p in SKIP_DIR_PARTS):
                    continue
                for f in fs:
                    if f.endswith(SKIP_EXT) or f.lower().endswith('.dat'):
                        continue
                    p = os.path.join(dp, f)
                    total_raw += add(z, p, os.path.relpath(p, ROOT).replace('\\', '/'))
                    n += 1
        for ex in EXES:
            if os.path.exists(os.path.join(ROOT, ex)):
                total_raw += add(z, os.path.join(ROOT, ex), ex)
                n += 1
        for rel in FIXTURES:
            p = os.path.join(ROOT, rel.replace('/', os.sep))
            if not os.path.exists(p):
                print('  [缺失] %s' % rel); continue
            # 保持原相对路径（脚本里就是按这个路径引用的，解压后直接能跑）
            total_raw += add(z, p, rel.replace('\\', '/'))
            n += 1
        for extra in ('打包说明.md', '打包工作区.py', '存档快照.py'):
            fp = os.path.join(ROOT, extra)
            if os.path.exists(fp):
                total_raw += add(z, fp, extra)
                n += 1
    print('打包完成：%s' % OUT)
    print('  文件 %d 个，原始 %.1f MB，压缩后 %.1f MB'
          % (n, total_raw / 1e6, os.path.getsize(OUT) / 1e6))


if __name__ == '__main__':
    main()
