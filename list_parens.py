# 18.09: полный список дисбалансов скобок в trigger/ приёмника
import io, os, re

d = r'C:\AgentLetta\LOWSWARIORS\trigger'
results = []
for root, dirs, fs in os.walk(d):
    for f in fs:
        if not f.endswith('.j'):
            continue
        p = os.path.join(root, f)
        s = io.open(p, 'rb').read().decode('utf-8', errors='replace')
        depth = 0
        for l in s.splitlines():
            if l.strip().startswith('//'):
                continue
            i2 = l.find('//')
            if i2 >= 0:
                l = l[:i2]
            l2 = re.sub(r'"[^"]*"', '""', l)
            depth += l2.count('(') - l2.count(')')
        if depth != 0:
            results.append((os.path.relpath(p, d), depth))
for r, dep in sorted(results):
    print('%+d  %s' % (dep, r))
print('всего:', len(results))