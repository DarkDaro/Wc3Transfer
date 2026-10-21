# 19.09: stage_triggers.py — чистка триггеров карты
# 4 операции (скан/удаление, удаление только по
# подтверждённому JSON):
#   1. Пустые папки (+ пустые .txt-заметки, опция)
#   2. Отключённые (Disab) / закрытые (Closed)
#      триггеры — с проверкой использования их
#      функций из живого кода
#   3. Неиспользуемые глобалки (variable.lml)
#   4. Мёртвые функции (trigger/*.j + корневые .j,
#      каскад, code.j — отдельной опцией)
# НЕ трогается: map/war3map.j (скомпилированный —
# редактор перезапишет), code.txt.
# CLI: stage_triggers.py <config.json> --scan <opts.json>
#      | --delete <delete.json>
import io, os, re, sys, json, time, shutil, struct

TRIGGER_FLAGS = {'Disab', 'Disable', 'Closed', 'Close',
                 'Comment', 'Run', 'Отключён', 'Отключен',
                 'Закрыт', 'Комментарий'}
FLAG_DISABLE = {'Disab', 'Disable', 'Отключён', 'Отключен'}
FLAG_CLOSE = {'Closed', 'Close', 'Закрыт'}
FLAG_COMMENT = {'Comment', 'Комментарий'}


def rp(path):
    return io.open(path, 'rb').read().decode('utf-8', errors='replace')


def wp(path, s):
    io.open(path, 'wb').write(s.encode('utf-8'))


# ---------- catalog.lml ----------

def parse_catalog(tgt):
    """Разбор catalog.lml. Возвращает (строки файла,
    список категорий, список триггеров).
    Категория: {name, disk, line, triggers:[...]}
    Триггер: {name, disk, flags:set, cat, line}
    Имя строки: 'name: display' (name в кавычках
    при спецсимволах). Флаги — строки без ':' с
    отступом под триггером."""
    p = os.path.join(tgt, 'trigger', 'catalog.lml')
    if not os.path.exists(p):
        return [], [], []
    s = rp(p)
    lines = s.split('\n')
    cats = []
    trigs = []
    cur_cat = None
    cur_trig = None
    for i, raw in enumerate(lines):
        t = raw.strip()
        if not t:
            continue
        indent = len(raw) - len(raw.lstrip())
        if ':' in t:
            # 19.09 (fix): в catalog.lml ДВА формата:
            #   'name: display'      — кавычки вокруг всей строки
            #   'name': 'display'     — кавычки у каждой части
            # Старый регекс ломался на втором. Универсальный парс:
            if t.startswith("'") and t.endswith("'") and len(t) >= 2:
                u = t[1:-1]
            else:
                u = t
            if "': '" in u and u.endswith("'"):
                # формат 2: name': 'display' — display в кавычках
                name, disp = u.split("': '", 1)
                disp = disp[:-1]
            elif "': '" in u:
                name, disp = u.split("': '", 1)
            elif ': ' in u:
                name, disp = u.split(': ', 1)
            else:
                name, disp = u.split(':', 1)
            disp_name = disp.strip()
            if disp_name.startswith("'") and disp_name.endswith("'") and len(disp_name) >= 2:
                disp_name = disp_name[1:-1]
            if indent == 0 and i > 0:
                # категория (первая строка файла — заголовок)
                disk = name
                cat = {'name': disp_name or name, 'disk': disk,
                       'line': i, 'triggers': []}
                cats.append(cat)
                cur_cat = cat
                cur_trig = None
            else:
                disk = name
                trig = {'name': disp_name or name, 'disk': disk,
                        'flags': set(), 'cat': cur_cat,
                        'line': i, 'flag_lines': []}
                trigs.append(trig)
                if cur_cat:
                    cur_cat['triggers'].append(trig)
                cur_trig = trig
        else:
            # флаг
            if t in TRIGGER_FLAGS:
                if cur_trig is not None:
                    cur_trig['flags'].add(t)
                    cur_trig['flag_lines'].append(i)
    return lines, cats, trigs


def trig_files(tgt, cat_disk, trig_disk):
    """Пути файлов триггера (.j/.lml/.txt), какие есть."""
    base = os.path.join(tgt, 'trigger', cat_disk, trig_disk)
    out = {}
    for ext in ('.j', '.lml', '.txt'):
        p = base + ext
        if os.path.exists(p):
            out[ext] = p
    return out


# ---------- код ----------

def code_files(tgt, include_codej):
    """Все .j файлы кода: trigger/**.j + корневые .j
    карты (trigger/code.j — по опции). НЕ map/war3map.j."""
    root = os.path.join(tgt, 'trigger')
    files = []
    if os.path.isdir(root):
        for dirpath, dirs, fs in os.walk(root):
            for f in fs:
                if not f.endswith('.j'):
                    continue
                p = os.path.join(dirpath, f)
                if include_codej or os.path.basename(p).lower() != 'code.j':
                    files.append(p)
    # корневые .j карты (вне trigger/ и map/)
    for f in os.listdir(tgt):
        if f.endswith('.j'):
            files.append(os.path.join(tgt, f))
    return files


def collect_functions(files):
    """{имя: [пути]} — все объявления function."""
    funcs = {}
    for p in files:
        try:
            s = rp(p)
        except OSError:
            continue
        for m in re.finditer(r'^\s*function\s+([A-Za-z_][A-Za-z0-9_]*)\s', s, re.M):
            funcs.setdefault(m.group(1), set()).add(p)
    return funcs


def collect_calls(files, own_names):
    """Множество имён, встречающихся как вызов/ссылка.
    Ловит: Имя( , ExecuteFunc("Имя"), 'Имя' в строках
    (коллбеки), Condition(Имя) и любые другие ссылки
    по слову целиком."""
    called = set()
    for p in files:
        try:
            s = rp(p)
        except OSError:
            continue
        # строковые литералы: ExecuteFunc('Имя') и прочие
        for m in re.finditer(r"'([A-Za-z_][A-Za-z0-9_]*)'", s):
            called.add(m.group(1))
        for m in re.finditer(r'"([A-Za-z_][A-Za-z0-9_]*)"', s):
            called.add(m.group(1))
        # прямые вызовы: имя( — слово целиком
        for m in re.finditer(r'\b([A-Za-z_][A-Za-z0-9_]*)\s*\(', s):
            called.add(m.group(1))
        # ссылки без скобок: Condition(Имя) уже покрыт,
        # но переменные-функции: = Имя (редко) — пропускаю,
        # ложный «мёртвый» опаснее ложного «живого»
    return called


# ---------- операции: скан ----------

def scan_empty_dirs(tgt, del_empty_txt, exclude=None):
    """Пустые папки (рекурсивно снизу вверх) +
    пустые .txt (0 байт / только пробелы) по опции.
    19.09 (вечер): exclude — имена папок, которые
    НЕ трогать (и их подпапки)."""
    root = os.path.join(tgt, 'trigger')
    empty_dirs = []
    empty_txt = []
    excl = set(x.lower() for x in (exclude or []))
    if not os.path.isdir(root):
        return empty_dirs, empty_txt
    for dirpath, dirs, fs in os.walk(root, topdown=False):
        rel = os.path.relpath(dirpath, root)
        if rel == '.':
            continue
        # 19.09: сама папка или родитель в исключении?
        parts = rel.split(os.sep)
        if any(pt.lower() in excl for pt in parts):
            continue
        # пустые .txt
        if del_empty_txt:
            for f in fs:
                if f.endswith('.txt'):
                    p = os.path.join(dirpath, f)
                    try:
                        if os.path.getsize(p) == 0 or not rp(p).strip():
                            empty_txt.append(p)
                    except OSError:
                        pass
        # папка пуста: нет файлов (кроме удаляемых .txt) и нет подпапок
        remaining = [f for f in fs if not (f.endswith('.txt') and any(p.endswith(f) and os.path.join(dirpath, f) == p for p in empty_txt))]
        if not dirs and not remaining:
            empty_dirs.append(dirpath)
    return empty_dirs, empty_txt


def scan_disabled(tgt, closed_too, del_notes, files_code, funcs, called, comments=False, exclude=None):
    """Отключённые/закрытые триггеры.
    19.09 (вечер): comments=True — включать Comment-заглушки
    (триггеры с флагом Comment без .j-кода: разделители,
    заметки). exclude — имена папок-категорий, НЕ трогать.
    Возвращает список {cat, name, disk, flags, size,
    used_by_live: [имена функций]}."""
    _, cats, trigs = parse_catalog(tgt)
    out = []
    excl = set(x.lower() for x in (exclude or []))
    for tr in trigs:
        if not tr['cat']:
            continue
        # 19.09: категория в исключении?
        parts = tr['cat']['disk'].split(os.sep)
        if any(pt.lower() in excl for pt in parts):
            continue
        want = ('Disab' in tr['flags'] or any(f in FLAG_DISABLE for f in tr['flags']))
        if closed_too and any(f in FLAG_CLOSE for f in tr['flags']):
            want = True
        # 19.09 (fix, КРИТИЧНО): было
        #   if comments and 'Comment' in flags or any(...)
        # — из-за приоритета AND/OR вторая ветка работала
        # БЕЗ галочки comments и БЕЗ проверки .j: сносились
        # живые триггеры с флагом Comment (MoveRight и др.).
        # Теперь: галочка включена И флаг Comment И нет .j.
        is_comment_stub = False
        if comments and any(f in FLAG_COMMENT for f in tr['flags']):
            base_c = os.path.join(tgt, 'trigger',
                                  tr['cat']['disk'] if tr['cat'] else '', tr['disk'])
            if not os.path.exists(base_c + '.j'):
                is_comment_stub = True
                want = True
        if not want:
            continue
        if not tr['cat']:
            continue
        # файлы
        base = os.path.join(tgt, 'trigger', tr['cat']['disk'], tr['disk'])
        size = 0
        for ext in ('.j', '.lml', '.txt'):
            p = base + ext
            if os.path.exists(p):
                size += os.path.getsize(p)
        # функции из этого триггера, вызываемые из ЖИВОГО кода
        jp = base + '.j'
        my_funcs = set()
        if os.path.exists(jp):
            try:
                s = rp(jp)
                for m in re.finditer(r'^\s*function\s+([A-Za-z_][A-Za-z0-9_]*)\s', s, re.M):
                    my_funcs.add(m.group(1))
            except OSError:
                pass
        used_by = sorted(my_funcs & called) if my_funcs else []
        note = ''
        if not del_notes and os.path.exists(base + '.txt'):
            note = 'есть заметка (.txt) — останется'
        if is_comment_stub:
            note = 'Comment-заглушка'
        out.append({'cat': tr['cat']['name'], 'cat_disk': tr['cat']['disk'],
                    'name': tr['name'], 'disk': tr['disk'],
                    'flags': sorted(tr['flags']), 'size': size,
                    'used_by': used_by, 'note': note})
    return out


def scan_globals(tgt, files_code):
    """Неиспользуемые глобалки из variable.lml.
    19.09 (fix, КРИТИЧНО): глобалка считается ИСПОЛЬЗУЕМОЙ,
    если udg_Имя упомянута ГДЕ-УГОДНО в карте:
    - .j триггеров (files_code)
    - trigger/code.j (кастом-код — раньше не сканировался,
      udg_MRR_* и др. сносились как unused!)
    - map/war3map.j (скомпилированный код)
    - .lml/.txt (текст триггеров в GUI-формате)
    Удаление идёт ТОЛЬКО по variable.lml — эти файлы
    не трогаются, только читаются как источники."""
    p = os.path.join(tgt, 'trigger', 'variable.lml')
    if not os.path.exists(p):
        return [], []
    s = rp(p)
    lines = s.split('\n')
    names = []
    for l in lines:
        t = l.strip()
        if t and ':' in t and (l.startswith(t[0]) if t else False):
            m = re.match(r'^([A-Za-z_][A-Za-z0-9_]*):\s*(\w+)$', t)
            if m:
                names.append(m.group(1))
    # 19.09: собираем ВЕСЬ текст карты как источник упоминаний
    all_code = ''
    for p in files_code:
        try:
            all_code += rp(p)
        except OSError:
            pass
    extra = [os.path.join(tgt, 'trigger', 'code.j'),
             os.path.join(tgt, 'map', 'war3map.j')]
    for p in extra:
        if os.path.exists(p):
            try:
                all_code += rp(p)
            except OSError:
                pass
    # .lml/.txt в trigger/ (текст триггеров GUI-формата)
    root = os.path.join(tgt, 'trigger')
    for dirpath, dirs, fs in os.walk(root):
        for f in fs:
            if f.endswith('.lml') or f.endswith('.txt'):
                fp = os.path.join(dirpath, f)
                try:
                    all_code += rp(fp)
                except OSError:
                    pass
    used = []
    unused = []
    for n in names:
        if re.search(r'\budg_%s\b' % re.escape(n), all_code):
            used.append(n)
        else:
            unused.append(n)
    return unused, used


def scan_dead_funcs(tgt, cascade, include_codej, exclude=None):
    """Мёртвые функции: определены, но не вызываются.
    Каскад: функция, вызываемая только из мёртвых,
    тоже мёртвая (итеративно).
    19.09 (вечер): exclude — имена папок, файлы в которых
    не предлагаются к удалению (но как источники вызовов
    учитываются)."""
    excl = set(x.lower() for x in (exclude or []))
    files = [p for p in code_files(tgt, include_codej)
             if not any(pt.lower() in excl
                        for pt in os.path.relpath(p, tgt).split(os.sep))]
    funcs = collect_functions(files)
    # исключения: никогда не удалять
    NEVER = {'main', 'InitCustomTriggers', 'InitGlobals',
             'InitCustomPlayerSlots', 'InitTeams', 'InitAllyPriorities',
             'config', 'InitMap', 'InitTrig_', 'trig_'}
    dead = {}
    alive_files = list(files)
    while True:
        called = collect_calls(alive_files, set(funcs))
        new_dead = {}
        for name, fps in funcs.items():
            if name in dead:
                continue
            if any(name.startswith(x) for x in NEVER):
                continue
            if name not in called:
                new_dead[name] = sorted(fps)
        if not new_dead or not cascade:
            for name, fps in new_dead.items():
                dead[name] = fps
            break
        for name, fps in new_dead.items():
            dead[name] = fps
        # убираем мёртвые из «живого» кода для следующей итерации:
        # т.к. их вызовы больше не считаются
        # (упрощение: пересчитываем called без учёта
        # мёртвых — достигается повторным проходом,
        # т.к. collect_calls сканирует весь текст;
        # для каскада достаточно повторить: мёртвая
        # функция F1 вызывала F2 — F2 попадёт в мёртвые,
        # только если F1 больше не «живая». Формально
        # надо исключить текст мёртвых из сканирования.)
        alive_files = []
        dead_set = set(dead)
        for p in files:
            try:
                s = rp(p)
            except OSError:
                continue
            # грубая проверка: файл содержит живые функции?
            file_funcs = set(m.group(1) for m in re.finditer(r'^\s*function\s+([A-Za-z_][A-Za-z0-9_]*)\s', s, re.M))
            if file_funcs and all(f in dead_set for f in file_funcs):
                continue  # весь файл мёртвый — не сканируем
            alive_files.append(p)
        if len(alive_files) == len(files):
            break
        files = alive_files
    return dead


# ---------- CLI ----------

def main():
    if len(sys.argv) < 3:
        print('usage: stage_triggers.py <config.json> --scan <opts.json> | --delete <delete.json>')
        sys.exit(1)
    cfg = json.load(io.open(sys.argv[1], 'rb'))
    tgt = cfg['target']
    # 20.10: окно «Чистка триггеров» умеет работать с другой картой,
    # но этап читал только cfg['target'] — скан шёл по приёмнику.
    if '--dir' in sys.argv:
        di = sys.argv.index('--dir')
        if di + 1 >= len(sys.argv):
            print('ОШИБКА: --dir без пути')
            sys.exit(2)
        tgt = os.path.abspath(sys.argv[di + 1])
    here = os.path.dirname(os.path.abspath(sys.argv[1]))
    if '--scan' in sys.argv:
        opts = json.load(io.open(sys.argv[sys.argv.index('--scan') + 1], 'rb'))
        # 19.09 (вечер): исключения — имена папок из конфига/opts
        exclude = opts.get('exclude_dirs') or cfg.get('cleanup', {}).get('exclude_dirs', [])
        files = code_files(tgt, opts.get('include_codej', False))
        funcs = collect_functions(files)
        called = collect_calls(files, funcs)
        res = {}
        if opts.get('empty_dirs', True):
            ed, et = scan_empty_dirs(tgt, opts.get('del_empty_txt', True), exclude=exclude)
            res['empty_dirs'] = [os.path.relpath(p, tgt) for p in ed]
            res['empty_txt'] = [os.path.relpath(p, tgt) for p in et]
        if opts.get('disabled', True) or opts.get('closed', False) or opts.get('comments', False):
            res['disabled'] = scan_disabled(tgt, opts.get('closed', False),
                                            opts.get('del_notes', False),
                                            files, funcs, called,
                                            comments=opts.get('comments', False),
                                            exclude=exclude)
        if opts.get('globals', False):
            un, us = scan_globals(tgt, files)
            res['globals_unused'] = un
            res['globals_used'] = us
        if opts.get('dead_funcs', False):
            res['dead_funcs'] = {n: [os.path.relpath(f, tgt) for f in fps]
                                 for n, fps in scan_dead_funcs(
                                     tgt, opts.get('cascade', True),
                                     opts.get('include_codej', False),
                                     exclude=exclude).items()}
        outp = os.path.join(here, 'triggers_scan.json')
        wp(outp, json.dumps(res, ensure_ascii=False, indent=1))
        print('скан ->', outp)
        # краткая сводка
        for k in ('empty_dirs', 'empty_txt', 'disabled', 'globals_unused', 'dead_funcs'):
            v = res.get(k)
            if v is not None:
                print(' ', k, len(v))
    elif '--delete' in sys.argv:
        del_json = sys.argv[sys.argv.index('--delete') + 1]
        d = json.load(io.open(del_json, 'rb'))
        # 19.09 (вечер): ДЕМО-РЕЖИМ (--dry) — показать что будет
        # удалено, БЕЗ записи в карту и без бэкапа
        DRY = '--dry' in sys.argv
        stamp = time.strftime('%Y-%m-%d_%H%M%S')
        # 21.10: пути чистки триггеров настраиваемые и рядом с конфигом
        # (консистентно с пайплайном): trigclean.log_dir / trigclean.backup_dir
        tcfg = cfg.get('trigclean', {})
        broot = tcfg.get('backup_dir') or os.path.join(here, cfg['safety']['backup_dir'], 'triggers')
        bdir = os.path.join(broot, stamp)
        if not DRY:
            os.makedirs(bdir, exist_ok=True)
        log = ['# %s триггеров %s' % ('ДЕМО (без записи):' if DRY else 'Чистка',
                                      time.strftime('%Y-%m-%d %H:%M:%S')), '']
        total = 0
        # 1. пустые папки + пустые txt
        for rel in d.get('empty_txt', []):
            p = os.path.join(tgt, rel)
            if os.path.exists(p):
                if DRY:
                    log.append('БУДЕТ удалён пустой .txt: %s' % rel)
                    total += 1
                    continue
                shutil.copy(p, os.path.join(bdir, 'txt_' + rel.replace('\\', '_')))
                os.remove(p)
                log.append('удалён пустой .txt: %s' % rel)
                total += 1
        for rel in sorted(d.get('empty_dirs', []), key=lambda x: -x.count('\\')):
            p = os.path.join(tgt, rel)
            if os.path.isdir(p) and not os.listdir(p):
                if DRY:
                    log.append('БУДЕТ удалена пустая папка: %s' % rel)
                    total += 1
                    continue
                os.rmdir(p)
                log.append('удалена пустая папка: %s' % rel)
                total += 1
        # 2. отключённые триггеры
        # 19.09 (вечер): страховка — исключённые папки не трогать
        excl = set(x.lower() for x in (cfg.get('cleanup', {}).get('exclude_dirs') or d.get('exclude_dirs') or []))
        for tr in d.get('disabled', []):
            parts = tr['cat_disk'].split(os.sep)
            if any(pt.lower() in excl for pt in parts):
                log.append('ПРОПУЩЕН (исключение): %s\\%s' % (tr['cat_disk'], tr['disk']))
                continue
            base = os.path.join(tgt, 'trigger', tr['cat_disk'], tr['disk'])
            if DRY:
                exts = [ext for ext in ('.j', '.lml', '.txt')
                        if os.path.exists(base + ext)]
                log.append('БУДЕТ удалён триггер: %s\\%s (%s) [%s]'
                           % (tr['cat_disk'], tr['disk'],
                              ','.join(tr.get('flags', [])),
                              ','.join(exts) or 'без файлов'))
                total += 1
                continue
            for ext in ('.j', '.lml', '.txt'):
                p = base + ext
                # 20.10: заметку не удаляем, если скан обещал её сохранить
                if ext == '.txt' and d.get('del_notes') is False:
                    log.append('заметка сохранена: %s' % os.path.relpath(p, tgt))
                    continue
                if os.path.exists(p):
                    rel = os.path.relpath(p, tgt)
                    dst = os.path.join(bdir, rel.replace('\\', '_'))
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copy(p, dst)
                    os.remove(p)
            log.append('удалён триггер: %s\\%s (%s)' % (tr['cat_disk'], tr['disk'], ','.join(tr.get('flags', []))))
            total += 1
        # 3. глобалки
        if d.get('globals'):
            p = os.path.join(tgt, 'trigger', 'variable.lml')
            if DRY:
                log.append('БУДУТ удалены глобалки (%d): %s'
                           % (len(d['globals']), ', '.join(d['globals'])))
                total += len(d['globals'])
            else:
                shutil.copy(p, os.path.join(bdir, 'variable.lml'))
                s = rp(p)
                lines = s.split('\n')
                out = []
                skip_next_attr = False
                removed_names = set(d['globals'])
                i = 0
                while i < len(lines):
                    t = lines[i].strip()
                    m = re.match(r'^([A-Za-z_][A-Za-z0-9_]*):\s*(\w+)$', t)
                    if m and m.group(1) in removed_names:
                        # пропускаю строку и её Array-атрибуты
                        j = i + 1
                        while j < len(lines) and lines[j].startswith('    '):
                            j += 1
                        i = j
                        continue
                    out.append(lines[i])
                    i += 1
                wp(p, '\n'.join(out))
                log.append('удалены глобалки: %s' % ', '.join(d['globals']))
                total += len(d['globals'])
        # 4. мёртвые функции
        if d.get('dead_funcs'):
            by_file = {}
            for name, rels in d['dead_funcs'].items():
                for rel in rels:
                    by_file.setdefault(rel, []).append(name)
            for rel, names in by_file.items():
                p = os.path.join(tgt, rel)
                if not os.path.exists(p):
                    continue
                # 19.09 (вечер): страховка — исключённые папки
                if any(pt.lower() in excl for pt in rel.split(os.sep)):
                    log.append('ПРОПУЩЕН файл (исключение): %s' % rel)
                    continue
                if DRY:
                    log.append('БУДУТ удалены функции (%d) из %s: %s'
                               % (len(names), rel, ', '.join(sorted(names))))
                    total += len(names)
                    continue
                shutil.copy(p, os.path.join(bdir, 'func_' + rel.replace('\\', '_')))
                s = rp(p)
                # удаляю функции целиком (от function до end на её уровне):
                # упрощённо — построчный парсинг вложенности
                lines = s.split('\n')
                out = []
                i = 0
                removed_set = set(names)
                while i < len(lines):
                    m = re.match(r'^(\s*)function\s+([A-Za-z_][A-Za-z0-9_]*)\s', lines[i])
                    if m and m.group(2) in removed_set:
                        depth = 0
                        j = i
                        while j < len(lines):
                            lj = lines[j]
                            if re.match(r'^\s*function\s', lj):
                                depth += 1
                            elif re.match(r'^\s*endfunction\b', lj):
                                depth -= 1
                                if depth == 0:
                                    break
                            j += 1
                        i = j + 1
                        continue
                    out.append(lines[i])
                    i += 1
                wp(p, '\n'.join(out))
                log.append('удалены функции из %s: %s' % (rel, ', '.join(names)))
                total += len(names)
        # каталог: чистка записей удалённых триггеров
        if d.get('disabled'):
            p = os.path.join(tgt, 'trigger', 'catalog.lml')
            # 19.09 (вечер): ДЕМО — только посчитать записи, не трогать
            if DRY:
                lines, cats, trigs = parse_catalog(tgt)
                del_set = set((tr['cat_disk'], tr['disk']) for tr in d['disabled'])
                n_skip = 0
                for tr in trigs:
                    cat_disk = tr['cat']['disk'] if tr.get('cat') else ''
                    if (cat_disk, tr['disk']) in del_set:
                        n_skip += 1 + len(tr['flag_lines'])
                log.append('БУДЕТ удалено записей из catalog.lml: ~%d' % n_skip)
            else:
                shutil.copy(p, os.path.join(bdir, 'catalog.lml'))
                lines, cats, trigs = parse_catalog(tgt)
                del_set = set((tr['cat_disk'], tr['disk']) for tr in d['disabled'])
                out = []
                skip = set()
                # 19.09 (fix): у триггеров из parse_catalog нет
                # 'cat_disk' — категория хранится объектом 'cat'
                for tr in trigs:
                    cat_disk = tr['cat']['disk'] if tr.get('cat') else ''
                    if (cat_disk, tr['disk']) in del_set:
                        skip.add(tr['line'])
                        for fl in tr['flag_lines']:
                            skip.add(fl)
                # категория целиком пустая после удаления?
                for cat in cats:
                    cat_trigs = [(tr['line'], tr) for tr in cat['triggers']]
                    if cat_trigs and all((cat['disk'], tr['disk']) in del_set for _, tr in cat_trigs):
                        skip.add(cat['line'])
                for i, l in enumerate(lines):
                    if i not in skip:
                        out.append(l)
                wp(p, '\n'.join(out))
                log.append('catalog.lml: удалено записей %d' % len(skip))
        # 19.09 (вечер): повторный проход пустых папок —
        # после удаления триггеров/заметок освободившиеся
        # папки тоже сносятся (за один прогон)
        if not DRY and d.get('empty_dirs') is not None:
            # 20.10: исключения действуют и во втором проходе
            ed2, et2 = scan_empty_dirs(tgt, True, exclude=list(excl))
            if ed2:
                for p in sorted(ed2, key=lambda x: -x.count(os.sep)):
                    try:
                        os.rmdir(p)
                    except OSError:
                        continue
                log.append('повторный проход: удалено папок %d' % len(ed2))
                total += len(ed2)
        log.append('ИТОГО %s: %d' % ('будет удалено (ДЕМО)' if DRY else 'удалено', total))
        if not DRY:
            log.append('Бэкап: %s' % bdir)
        # 21.10: лог чистки тоже настраиваемый и рядом с конфигом
        ldir = tcfg.get('log_dir') or cfg.get('log_dir') or os.path.join(here, 'logs')
        os.makedirs(ldir, exist_ok=True)
        lp = os.path.join(ldir, 'triggers-%s%s.md'
                          % (time.strftime('%Y-%m-%d'), '-demo' if DRY else ''))
        io.open(lp, 'ab').write(('\n'.join(log) + '\n\n').encode('utf-8'))
        # 19.09 (вечер): путь к логу отдельной строкой (GUI откроет его)
        print('ЛОГ: %s' % lp)
        for l in log:
            print(l)


if __name__ == '__main__':
    main()