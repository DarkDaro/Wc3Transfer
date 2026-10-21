# 17.09: stage_cleanup.py — чистка карты (скан/удаление)
# Подход: --scan -> cleanup_scan.json; --delete -> удаление
# по подтверждённому списку (cleanup_delete.json) + лог.
# НИКАКИХ молчаливых удалений: удаление только по файлу,
# который пишет GUI после подтверждения пользователем.
# Бэкап: backup/cleanup/<дата>/ перед удалением.
import io, os, re, sys, json, time, struct

TYPES = ['unit', 'ability', 'buff', 'item', 'upgrade', 'doodad', 'destructable']
PREFIX = {
    'unit': 'ehnou',
    'ability': 'A',
    'buff': 'BX',
    'item': 'I',
    'upgrade': 'R',
    'doodad': 'DOL',
    'destructable': 'BT',
}
MUSTUSE = {
    'ability': {'Avul', 'Adda', 'Amnz', 'Aalr', 'Aatk', 'ANbu', 'AHbu', 'AObu', 'AEbu', 'AUbu', 'AGbu',
                'Abdt', 'Argd', 'AHer', 'Arev', 'ARal', 'ACsp', 'Sloa', 'Aetl', 'Amov',
                'Afir', 'Afih', 'Afio', 'Afin', 'Afiu', 'ACac'},
    'buff': {'BPSE', 'BSTN', 'Btlf', 'Bdet', 'Bvul', 'Bspe', 'Bfro', 'Bsha', 'Btrv',
             'Xbdt', 'Xbli', 'Xdis', 'Xfhs', 'Xfhm', 'Xfhl', 'Xfos', 'Xfom', 'Xfol',
             'Xfns', 'Xfnm', 'Xfnl', 'Xfus', 'Xfum', 'Xful'},
}
REF_FIELDS = {'abilList', 'BuffId', 'upgradeList', 'UpgradeArt',
              'required1', 'required2', 'required3', 'required4', 'required5', 'required6',
              'itemAbility'}
DEFAULT_SUFFIX_PATTERNS = ['(убрано)', '(Убрано)', 'не используется']


def parse_bodies(path):
    out = {}
    if not os.path.exists(path):
        return out
    s = io.open(path, 'rb').read().decode('utf-8', errors='replace')
    cur = None
    in_block = False
    for l in s.splitlines():
        if not in_block:
            m = re.match(r'^\[([^\]]+)\]', l)
            if m:
                cur = m.group(1)
                out[cur] = []
                continue
            if cur:
                # 21.10 (аудит): строку открытия блока сохраняем в теле,
                # иначе терялось поле вида 'Description = [=['.
                out[cur].append(l)
                if l.rstrip().endswith('[=['):
                    in_block = ']=]' not in l
                elif ']=]' in l:
                    in_block = False
        else:
            if ']=]' in l:
                in_block = False
    return out


def load_tables(tgt):
    tabs = {}
    for t in TYPES:
        p = os.path.join(tgt, 'table', t + '.ini')
        if os.path.exists(p):
            tabs[t] = parse_bodies(p)
    return tabs


def field(lines, key):
    for l in lines:
        m = re.match(r'^' + key + r'\s*=\s*"?(.*?)"?\s*$', l)
        if m:
            return m.group(1)
    return ''


def collect_refs(tabs):
    """refs: {id: [(владелец_тип, владелец_id, поле), ...]}"""
    refs = {}

    def add(ref, owner_t, owner_id, key):
        if ref:
            refs.setdefault(ref, []).append((owner_t, owner_id, key))

    for t, bodies in tabs.items():
        for sid, lines in bodies.items():
            i = 0
            while i < len(lines):
                l = lines[i]
                m = re.match(r'^(\w+)\s*=\s*(.*)$', l)
                if not m:
                    i += 1
                    continue
                key, val = m.group(1), m.group(2)
                # 19.09: многострочное значение { ... } — токены
                # собираем и с последующих строк до }
                if val.rstrip().endswith('{'):
                    j = i + 1
                    while j < len(lines) and '}' not in lines[j]:
                        val += ' ' + lines[j]
                        j += 1
                    if j < len(lines):
                        val += ' ' + lines[j]
                    i = j
                # 19.09: номерные ключи (1 = "B023") — в lni так абилки
                # держат баффы (DataA/DataB = BuffID по уровням).
                # Токены-слова (self, air) не секции — refs их игнорирует.
                if key in REF_FIELDS or key.lower() == 'buffid' or key.isdigit():
                    for tok in re.findall(r'\b[A-Za-z][A-Za-z0-9]{3}\b', val):
                        if tok != sid:
                            add(tok, t, sid, key)
                if key == '_parent':
                    add(val.strip().strip('"'), t, sid, '_parent')
                i += 1
    return refs


def scan_code_literals(tgt):
    found = set()
    code_dir = os.path.join(tgt, 'trigger')
    if not os.path.isdir(code_dir):
        return found
    for root, dirs, fs in os.walk(code_dir):
        for f in fs:
            if not (f.endswith('.j') or f.endswith('.lml')):
                continue
            p = os.path.join(root, f)
            try:
                s = io.open(p, 'rb').read().decode('utf-8', errors='replace')
            except Exception:
                continue
            for m in re.finditer(r"'([A-Za-z0-9]{4})'", s):
                found.add(m.group(1))
    return found


def is_std(id4, t, std_ids):
    """Стандартный объект WC3: есть в prebuilt (MPQ) приёмника."""
    return id4 in std_ids


def scan_map_placement(tgt):
    """19.09: ID, реально стоящие на карте.
    war3map.doo — декорации/деревья/разрушаемые,
    war3mapUnits.doo — юниты/предметы. Эти ID
    всегда считаются используемыми: юнит или
    декорация, расставленная редактором, живёт
    только в расстановке, код её не упоминает.
    Формат (по парсеру w2l frontend_doo.lua):
    W3do, ver=8, unk=11, count, записи переменной
    длины (typeId + поля + дроп-сеты)."""
    found = {'doo': set(), 'units': set()}
    p = os.path.join(tgt, 'map', 'war3map.doo')
    if os.path.exists(p):
        d = io.open(p, 'rb').read()
        try:
            pos = 12
            def i32():
                nonlocal pos
                v = struct.unpack('<i', d[pos:pos+4])[0]
                pos += 4
                return v
            def c4():
                nonlocal pos
                v = d[pos:pos+4]
                pos += 4
                return v
            if d[:4] == b'W3do':
                count = i32()
                for _ in range(count):
                    found['doo'].add(c4().decode('latin1'))
                    pos += 4 + 12 + 4 + 12 + 2  # стиль, xyz, угол, масштаб, флаги
                    i32()  # dropList
                    drops = i32()
                    for _ in range(max(drops, 0)):
                        c4(); i32()
                    i32()  # номер
        except (struct.error, IndexError):
            pass  # битый файл — не валим скан
    p = os.path.join(tgt, 'map', 'war3mapUnits.doo')
    if os.path.exists(p):
        d = io.open(p, 'rb').read()
        # юнит-записи переменной длины без надёжной
        # спеки под рукой — эмпирический скан валидных
        # равкодов (4 ASCII [A-Za-z0-9]{4} с буквой
        # первой). Ложные срабатывания редки, а
        # ложный «используемый» безопасен (не удалит).
        for m in re.finditer(rb'[A-Za-z][A-Za-z0-9]{3}', d):
            found['units'].add(m.group(0).decode('latin1'))
        found['units'].discard('W3do')
        found['units'].discard('sloc')
    return found


def load_std_ids(tgt, cfgp=None):
    """Стандартные ID из prebuilt w3x2lni (рядом с source).
    20.10: конфиг передаётся снаружи (мультиконфиг), tgt оставлен
    для совместимости вызова."""
    std = set()
    here = os.path.dirname(os.path.abspath(__file__))
    if not cfgp:
        cfgp = os.path.join(here, 'transfer_config.json')
    pb = ''
    if os.path.exists(cfgp):
        cfg = json.load(io.open(cfgp, 'rb'))
        pb = cfg.get('mapping', {}).get('prebuilt_dir') or ''
        if not pb:
            src = cfg.get('source', '')
            sd = os.path.dirname(src)
            import glob
            cand = glob.glob(os.path.join(sd, '*', 'data', '*', 'prebuilt', 'Custom'))
            if not cand:
                cand = glob.glob(os.path.join(sd, 'data', '*', 'prebuilt', 'Custom'))
            pb = cand[0] if cand else ''
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


def scan(tgt, suffix_patterns, manual_ids, protect_ids=None, cfgp=None):
    # 19.09: protect_ids = {type: [id,...]} — защитный список
    # (cleanup_protect.json): живые дамми-абилки/баффы, которые
    # сканер не должен помечать неиспользуемыми ни при каких фильтрах
    protect_ids = protect_ids or {}
    tabs = load_tables(tgt)
    refs = collect_refs(tabs)
    code_ids = scan_code_literals(tgt)
    std_ids = load_std_ids(tgt, cfgp)
    # 19.09: расстановка карты — юниты/декорации,
    # стоящие на карте, всегда «используемые»
    place = scan_map_placement(tgt)
    place_all = place['doo'] | place['units']

    result = {'suffix': {}, 'badcode': {}, 'unused': {}, 'stats': {}}
    dead_owner = set()  # владельцы, которые сами пойдут в удаление

    # проход 1: классификация
    for t, bodies in tabs.items():
        result['stats'][t] = len(bodies)
        for sid, lines in bodies.items():
            if sid in MUSTUSE.get(t, set()):
                continue
            # 19.09: защитный список — никогда не unused
            if sid in protect_ids.get(t, set()):
                continue
            if is_std(sid, t, std_ids):
                continue
            my_refs = refs.get(sid, [])
            in_code = sid in code_ids
            if my_refs or in_code:
                continue  # используется
            # 19.09: стоит на карте (расстановка)?
            if sid in place_all:
                continue  # используется — расставлен редактором
            name = field(lines, 'Name')
            es = field(lines, 'EditorSuffix')
            es_l = es.lower()
            matched = next((p for p in suffix_patterns if p.lower() in es_l), None)
            if matched:
                result['suffix'].setdefault(t, {})[sid] = {'name': name, 'suffix': es, 'pattern': matched}
                continue
            if manual_ids.get(t) and sid in manual_ids[t]:
                result['suffix'].setdefault(t, {})[sid] = {'name': name, 'suffix': es, 'pattern': '(ручной)'}
                continue
            bad = False
            # 18.09: префиксный фильтр убран — в LoW/UFS кастомные
            # равкоды с любой первой буквой ВАЛИДНЫ (pUad, rUas...).
            # Реально битый = длина/символы.
            if len(sid) != 4 or not sid.isalnum():
                bad = True
            if bad:
                result['badcode'].setdefault(t, {})[sid] = {'name': name, 'id': sid}
                continue
            result['unused'].setdefault(t, {})[sid] = {'name': name}
            dead_owner.add(sid)

    # проход 2: каскадные волны — объекты, чьи владельцы все мертвы
    waves = []
    while True:
        wave = {}
        for t, bodies in tabs.items():
            for sid, lines in bodies.items():
                if sid in dead_owner or sid in MUSTUSE.get(t, set()) or sid in protect_ids.get(t, set()) or is_std(sid, t, std_ids):
                    continue
                my_refs = refs.get(sid, [])
                if not my_refs:
                    continue
                if all(owner_id in dead_owner for _, owner_id, _ in my_refs):
                    name = field(lines, 'Name')
                    wave[sid] = {'name': name, 'type': t,
                                 'owners': sorted({o for _, o, _ in my_refs})[:5]}
        if not wave:
            break
        waves.append(wave)
        dead_owner |= set(wave)
        if len(waves) > 10:
            break
    result['waves'] = waves
    return result


def delete(tgt, del_list, log_dir, backup_dir, dry=False):
    """del_list: {type: [id,...]}. Возвращает лог-строки.
    19.09 (вечер): dry=True — ДЕМО: показать что будет
    удалено, БЕЗ записи в таблицы и без бэкапа."""
    stamp = time.strftime('%Y-%m-%d_%H%M%S')
    bdir = os.path.join(backup_dir, stamp)
    if not dry:
        os.makedirs(bdir, exist_ok=True)
    os.makedirs(log_dir, exist_ok=True)
    tabs = {}
    for t in TYPES:
        p = os.path.join(tgt, 'table', t + '.ini')
        if os.path.exists(p):
            tabs[t] = p
    lines_out = ['# %s %s' % ('ДЕМО чистки (без записи):' if dry else 'Чистка',
                              time.strftime('%Y-%m-%d %H:%M:%S')), '']
    total = 0
    for t, ids in del_list.items():
        if not ids or t not in tabs:
            continue
        p = tabs[t]
        # 19.09 (вечер): ДЕМО — посчитать секции, не трогать файл
        if dry:
            s = io.open(p, 'rb').read().decode('utf-8', errors='replace')
            idset = set(ids)
            have = set()
            for l in s.splitlines():
                m = re.match(r'^\[([^\]]+)\]', l)
                if m and m.group(1) in idset:
                    have.add(m.group(1))
            lines_out.append('%s: БУДЕТ удалено %d секций (%s)'
                             % (t, len(have),
                                ', '.join(sorted(have)[:20]) + ('...' if len(have) > 20 else '')))
            total += len(have)
            continue
        # бэкап
        import shutil
        shutil.copy(p, os.path.join(bdir, t + '.ini'))
        s = io.open(p, 'rb').read().decode('utf-8', errors='replace')
        idset = set(ids)
        # удаление секций: от [id] до следующей [ или EOF, с учётом [=[ ]=]
        # 19.09 (fix): при пропуске тела удаляемой секции
        # ОБЯЗАТЕЛЬНО следить за блоками [=[ ]=] — иначе
        # Ubertip=[=[ пропускается без открытия блока,
        # строка текста '[...' внутри описания принимается
        # за новую секцию, и в файл пишется битая «секция»
        # (lni потом падает: ']' expected near '+').
        out = []
        cur = None
        in_block = False
        removed = 0
        for l in s.splitlines():
            if not in_block:
                m = re.match(r'^\[([^\]]+)\]', l)
                if m:
                    cur = m.group(1)
                    if cur in idset:
                        removed += 1
                        in_block = False
                        continue
                    out.append(l)
                    continue
                if cur and cur in idset:
                    # 19.09: тело удаляемой секции — но блоки трекаем!
                    if l.rstrip().endswith('[=['):
                        in_block = True
                    elif ']=]' in l:
                        in_block = False
                    continue
                if l.rstrip().endswith('[=['):
                    in_block = True
                elif ']=]' in l:
                    in_block = False
                out.append(l)
            else:
                if ']=]' in l:
                    in_block = False
                # тело удаляемой секции не пишем
                if cur and cur in idset:
                    continue
                out.append(l)
        io.open(p, 'wb').write(('\n'.join(out) + '\n').encode('utf-8'))
        lines_out.append('%s: удалено %d секций (%s)' % (t, removed, ', '.join(sorted(idset)[:20]) + ('...' if len(idset) > 20 else '')))
        total += removed
    lines_out.append('ИТОГО %s: %d' % ('будет удалено (ДЕМО)' if dry else 'удалено', total))
    if not dry:
        lines_out.append('Бэкап: %s' % bdir)
    logp = os.path.join(log_dir, 'cleanup-%s%s.md'
                        % (time.strftime('%Y-%m-%d'), '-demo' if dry else ''))
    io.open(logp, 'ab').write(('\n'.join(lines_out) + '\n\n').encode('utf-8'))
    # 19.09 (вечер): путь к логу отдельной строкой (GUI откроет его)
    lines_out.append('ЛОГ: %s' % logp)
    return lines_out


if __name__ == '__main__':
    ap = sys.argv
    if len(ap) < 2:
        print('usage: stage_cleanup.py <config.json> --scan | --delete <cleanup_delete.json>')
        sys.exit(1)
    cfg = json.load(io.open(ap[1], 'rb'))
    tgt = cfg['target']
    here = os.path.dirname(os.path.abspath(ap[1]))
    if '--scan' in ap:
        patterns = cfg.get('cleanup', {}).get('suffix_patterns', DEFAULT_SUFFIX_PATTERNS)
        manual = cfg.get('cleanup', {}).get('manual_ids', {})
        # 19.09: защитный список из внешнего файла рядом с конфигом
        protect = {}
        pp = os.path.join(here, 'cleanup_protect.json')
        if os.path.exists(pp):
            protect = json.load(io.open(pp, 'rb'))
            print('защитный список:', {k: len(v) for k, v in protect.items()})
        res = scan(tgt, patterns, manual, protect, cfgp=ap[1])
        out = os.path.join(here, 'cleanup_scan.json')
        io.open(out, 'wb').write(json.dumps(res, indent=2, ensure_ascii=False).encode('utf-8'))
        print('скан ->', out)
        for k in ['suffix', 'badcode']:
            n = sum(len(v) for v in res[k].values())
            print(k, n)
        print('unused:', sum(len(v) for v in res['unused'].values()), '+ волн:', len(res['waves']) - 1 if res['waves'] else 0)
    elif '--delete' in ap:
        dp = os.path.join(here, 'cleanup_delete.json')
        dl = json.load(io.open(dp, 'rb'))
        # 21.10: пути чистки настраиваемые и рядом с конфигом (консистентно
        # с пайплайном переноса): cleanup.log_dir / cleanup.backup_dir,
        # иначе logs/ и safety.backup_dir/cleanup у конфига.
        ccfg = cfg.get('cleanup', {})
        ldir = ccfg.get('log_dir') or cfg.get('log_dir') or os.path.join(here, 'logs')
        broot = ccfg.get('backup_dir') or os.path.join(here, cfg['safety']['backup_dir'], 'cleanup')
        lines = delete(tgt, dl, ldir, broot)
        for l in lines:
            print(l)