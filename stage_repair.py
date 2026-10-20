# 17.09: repair_tables — починка table/*.ini карты
# Скан: --repair-scan -> отчёт в stdout (список проблем)
# Починка: --repair -> бэкап + правка + лог
# Проблемы: разбаланс [=[ ]=], дубли секций, оборванные
# секции (EOF внутри тела), битый _parent (нет в таблице
# и в prebuilt) -> замена на дефолтного родителя типа.
import io, os, re, sys, json, time, shutil

TYPES = ['unit', 'ability', 'buff', 'item', 'upgrade', 'doodad', 'destructable']
DEFAULT_PARENT = {
    'unit': 'hpea',        # пехотинец
    'ability': 'ANcl',     # Channel
    'buff': 'BPSE',        # Bloodlust
    'item': 'ratf',        # скелет-предмет (нейтральный)
    'upgrade': 'Rhlh',
    'doodad': 'OLra',
    'destructable': 'ATtr',
}


def load_std_ids(cfgp=None):
    # 20.10: читаем конфиг, с которым запущены (мультиконфиг), а не
    # всегда transfer_config.json рядом со скриптом.
    here = os.path.dirname(os.path.abspath(__file__))
    if not cfgp:
        cfgp = os.path.join(here, 'transfer_config.json')
    pb = ''
    if os.path.exists(cfgp):
        cfg = json.load(io.open(cfgp, 'rb'))
        pb = cfg.get('mapping', {}).get('prebuilt_dir') or ''
        if not pb:
            sd = os.path.dirname(cfg.get('source', ''))
            import glob
            cand = glob.glob(os.path.join(sd, '*', 'data', '*', 'prebuilt', 'Custom'))
            if not cand:
                cand = glob.glob(os.path.join(sd, 'data', '*', 'prebuilt', 'Custom'))
            pb = cand[0] if cand else ''
    std = set()
    if pb and os.path.isdir(pb):
        for f in os.listdir(pb):
            if not f.endswith('.ini'):
                continue
            s = io.open(os.path.join(pb, f), 'rb').read().decode('utf-8', errors='replace')
            in_block = False
            for l in s.splitlines():
                if not in_block:
                    m = re.match(r'^\[([^\]]+)\]', l)
                    if m:
                        std.add(m.group(1))
                    if l.rstrip().endswith('[=['):
                        in_block = True
                elif ']=]' in l:
                    in_block = False
    return std


def collect_ids(tgt):
    """20.10: все ID секций во всех таблицах приёмника. Нужен, чтобы
    не объявлять битым _parent, объявленный НИЖЕ по файлу или в
    соседней таблице (раньше проверялось только `seen` сверху)."""
    ids = set()
    for t in TYPES:
        p = os.path.join(tgt, 'table', t + '.ini')
        if not os.path.exists(p):
            continue
        s = io.open(p, 'rb').read().decode('utf-8', errors='replace')
        in_block = False
        for l in s.splitlines():
            if not in_block:
                m = re.match(r'^\[([^\]]+)\]', l)
                if m:
                    ids.add(m.group(1))
                if l.rstrip().endswith('[=['):
                    in_block = True
            elif ']=]' in l:
                in_block = False
    return ids


def repair(tgt, log_dir, backup_dir, do=True, cfgp=None):
    """Возвращает (строки_отчёта, число_правок)."""
    stamp = time.strftime('%Y-%m-%d_%H%M%S')
    report = ['# Починка таблиц %s' % time.strftime('%Y-%m-%d %H:%M:%S'), '']
    std = load_std_ids(cfgp)
    all_ids = collect_ids(tgt)
    total = 0
    if do:
        os.makedirs(backup_dir, exist_ok=True)
    for t in TYPES:
        p = os.path.join(tgt, 'table', t + '.ini')
        if not os.path.exists(p):
            continue
        s = io.open(p, 'rb').read().decode('utf-8', errors='replace')
        lines = s.splitlines()
        out = []
        fixed = []
        seen = set()
        in_block = False
        cur = None
        cur_dropped = False
        # 19.09 (правило 2): счётчик пропуска строк обрывка
        skip_count = 0
        i = 0
        while i < len(lines):
            l = lines[i]
            if not in_block:
                # 19.09: активен пропуск хвоста обрывка?
                if skip_count > 0:
                    skip_count -= 1
                    i += 1
                    continue
                m = re.match(r'^\[([^\]]+)\]', l)
                if m and re.match(r'^[A-Za-z][A-Za-z0-9]{3}$', m.group(1)):
                    sid = m.group(1)
                    if sid in seen:
                        # дубль: пропускаем целиком (тело тоже)
                        cur = sid
                        cur_dropped = True
                        fixed.append('дубль секции %s (строка %d) — удалён' % (sid, i + 1))
                        i += 1
                        continue
                    seen.add(sid)
                    cur = sid
                    cur_dropped = False
                    out.append(l)
                    i += 1
                    continue
                # 19.09 (правило 1+2): строка вне блока, начинающаяся
                # с '[' но НЕ валидная секция (имя не 4 символа
                # A-Za-z0-9) — это текст описания, lni падает.
                # Если в ближайших 15 строках есть ']=] — обрывок
                # многострочного описания (хвост без открытия):
                # удаляю хвост до ']=]' включительно.
                # Иначе — одиночная строка текста: экранирую
                # '[' -> '(' в начале строки.
                if l.startswith('[') and not l.startswith('[=['):
                    j = i + 1
                    found = False
                    while j < len(lines) and j <= i + 15:
                        if ']=]' in lines[j]:
                            found = True
                            break
                        if re.match(r'^\[[A-Za-z][A-Za-z0-9]{3}\]', lines[j]):
                            break
                        j += 1
                    if found:
                        fixed.append('обрывок описания (строки %d-%d) — удалён: %s' % (i + 1, j + 1, l[:60]))
                        skip_count = j - i  # пропустить строки i+1..j
                        i += 1
                        continue
                    else:
                        fixed.append('текст с [ вне блока (строка %d) -> ( экранирован: %s' % (i + 1, l[:60]))
                        l = '(' + l[1:]
                # _parent проверка
                mp = re.match(r'^(_parent)\s*=\s*"?([^"\n]*)', l)
                if mp and cur and not cur_dropped:
                    par = mp.group(2).strip().strip('"')
                    # 18.09: self-parent (секция = модификация
                    # стандарта, [X] _parent=X) — ВАЛИДНЫЙ
                    # lni-формат. НЕ чинить! Битый = указывает
                    # на ДРУГОЙ несуществующий ID.
                    if par and par != cur and par not in std and par not in all_ids:
                        # родитель не стандартный и не в этой таблице
                        # (проверю по остальным таблицам позже — пока
                        # только если вообще нет нигде: заменю)
                        fixed.append('битый _parent %s у %s (строка %d) -> %s' % (par, cur, i + 1, DEFAULT_PARENT.get(t, '')))
                        l = re.sub(r'^(_parent\s*=\s*).*(\s*)$', lambda mm: mm.group(1) + '"' + DEFAULT_PARENT.get(t, 'hpea') + '"', l)
                if l.rstrip().endswith('[=['):
                    in_block = True
                elif ']=]' in l:
                    in_block = False
                if cur_dropped:
                    i += 1
                    continue
                out.append(l)
            else:
                if ']=]' in l:
                    in_block = False
                if cur_dropped:
                    i += 1
                    continue
                out.append(l)
            i += 1
        if fixed:
            total += len(fixed)
            report.append('## %s' % t)
            report.extend('- ' + f for f in fixed)
            if do:
                # 20.10: папка бэкапа создаётся здесь же (GUI звал repair
                # без предварительного makedirs), прошлый бэкап не затираем
                dst = os.path.join(backup_dir, t + '.ini')
                if os.path.exists(dst):
                    dst = os.path.join(backup_dir, '%s-%s.ini' % (t, stamp))
                shutil.copy(p, dst)
                io.open(p, 'wb').write(('\n'.join(out) + '\n').encode('utf-8'))
    report.append('ИТОГО правок: %d%s' % (total, '' if do else ' (режим скана — ничего не писано)'))
    return report, total


if __name__ == '__main__':
    cfg = json.load(io.open(sys.argv[1], 'rb'))
    tgt = cfg['target']
    here = os.path.dirname(os.path.abspath(sys.argv[1]))
    do = '--repair' in sys.argv
    backup_dir = os.path.join(here, cfg['safety']['backup_dir'], 'repair')
    if do:
        os.makedirs(backup_dir, exist_ok=True)
    report, total = repair(tgt, None, backup_dir, do=do, cfgp=sys.argv[1])
    for l in report:
        print(l)
    if do:
        os.makedirs(os.path.join(here, 'logs'), exist_ok=True)
        lp = os.path.join(here, 'logs', 'repair-%s.md' % time.strftime('%Y-%m-%d'))
        io.open(lp, 'ab').write(('\n'.join(report) + '\n\n').encode('utf-8'))
        print('лог ->', lp)