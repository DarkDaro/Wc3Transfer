# 18.09: существующие bat утилиты  # 20.10: путь от папки скрипта, не от машины
import os, glob

HERE = os.path.dirname(os.path.abspath(__file__))
for f in glob.glob(os.path.join(HERE, '*.bat')):
    print(f)
    print(open(f, encoding='utf-8', errors='replace').read())