# 20.09: манифест деплоя — что утилита записала в приёмник.
# Решает проблему "поколений": смена версии утилиты / deploy_to /
# набора папок оставляла старые файлы и записи каталога навсегда.
# Манифест хранится рядом с конфигом (как state, привязан к паре карт).
# Формат:
# {
#   "deploy_to": "JAR",            # имя деплоя из конфига НА МОМЕНТ записи
#   "files": ["trigger/213-FW/x.j", ...],   # относительные пути в target
#   "catalog_entries": ["213-FW", "213-FW-header", ...],  # ключи записей каталога
#   "header_block": "JAR",          # имя header-блока в code.j (append-режим)
#   "globals_file": "trigger/213-FW-Globals.j"  # файл глобалов (если был)
# }
import io, os, json, hashlib, re

def manifest_path(cfgp):
    return os.path.join(os.path.dirname(os.path.abspath(cfgp)), 'deploy_manifest.json')

def load_manifest(cfgp):
    p = manifest_path(cfgp)
    if os.path.exists(p):
        try:
            return json.load(io.open(p, 'rb'))
        except (ValueError, OSError):
            return None
    return None

def save_manifest(cfgp, m):
    io.open(manifest_path(cfgp), 'wb').write(
        json.dumps(m, indent=1, ensure_ascii=False).encode('utf-8'))

def fhash(p):
    """Хеш файла на момент записи — purge предупредит, если
    файл правили руками после переноса (всё равно снесёт:
    это артефакт переноса, но пользователь должен знать)."""
    try:
        return hashlib.md5(io.open(p, 'rb').read()).hexdigest()
    except OSError:
        return None

def record_hashes(cfgp, m, tgt):
    """Для каждого файла манифеста — хеш сразу после записи."""
    h = {}
    for rel in m.get('files', []):
        p = os.path.join(tgt, rel.replace('/', os.sep))
        v = fhash(p)
        if v:
            h[rel] = v
    m['hashes'] = h
    save_manifest(cfgp, m)

def merge_section(cfgp, section, data):
    """20.09: манифест общий для stage_code/globals/code_cut.
    Каждый этап пишет СВОЮ секцию, не затирая чужие:
      code:    files, catalog_entries, header_block, deploy_to
      globals: globals_file, globals_entry
      code_cut: cut_file, cut_entry
    deploy_to — общий (последний писавший)."""
    m = load_manifest(cfgp) or {}
    m.update(data)
    save_manifest(cfgp, m)

def purge_section_files(cfgp, tgt, section, keep, log=print):
    """20.09: purge файлов ОДНОЙ секции (globals/code_cut).
    stage_code чистит свою секцию через общий purge()."""
    m = load_manifest(cfgp)
    if not m:
        log('purge: манифест не найден — нечего чистить (первый прогон?)')
        return [], []
    rels = m.get(section) or []
    # 20.09 fix: секция может быть строкой (globals_file/cut_file) —
    # без этого цикл перебирал СИМВОЛЫ строки
    if isinstance(rels, str):
        rels = [rels]
    removed, warns = [], []
    for rel in rels:
        if rel in keep:
            continue
        p = os.path.join(tgt, rel.replace('/', os.sep))
        rp = os.path.normpath(p)
        if os.sep + 'trigger' + os.sep not in rp + os.sep:
            warns.append('purge: %s вне trigger/ — ПРОПУЩЕН' % rel)
            continue
        if os.path.exists(p):
            h0 = (m.get('hashes') or {}).get(rel)
            if h0 and fhash(p) != h0:
                warns.append('purge: %s менялся после переноса — удаляю (артефакт деплоя)' % rel)
            try:
                os.remove(p)
                removed.append(rel)
            except OSError as e:
                warns.append('purge: не удалён %s (%s)' % (rel, e))
    if removed:
        log('purge %s: удалено %d' % (section, len(removed)))
    return removed, warns

def purge_catalog_entry(cfgp, tgt, key, log=print):
    """20.09: точечное удаление ОДНОЙ записи каталога
    (+ её дочерних строк с отступом) по regex-ключу."""
    cat_p = os.path.join(tgt, 'trigger', 'catalog.lml')
    if not os.path.exists(cat_p):
        return False
    cat = io.open(cat_p, 'rb').read().decode('utf-8', errors='replace')
    pat = re.compile(r"^[ \t]*'?" + re.escape(key) + r"'?:[^\n]*\n(?:[ \t]+[^\n]*\n)*", re.M)
    cat2 = pat.sub('', cat, count=1)
    if cat2 != cat:
        io.open(cat_p, 'wb').write(cat2.encode('utf-8'))
        log('purge: удалена запись каталога %s' % key)
        return True
    return False

def purge(cfgp, tgt, keep=None, keep_e=None, log=print):
    """Удалить артефакты прошлого деплоя по манифесту.
    keep: файлы, которые НОВЫЙ прогон сохранит — не трогаем.
    keep_e: ключи записей каталога нового прогона — не трогаем.
    Удаляем ТОЛЬКО из манифеста — никогда не сканируем
    trigger/ вслепую. Возвращает (удалено, предупреждения)."""
    m = load_manifest(cfgp)
    if not m:
        log('purge: манифест не найден — нечего чистить (первый прогон?)')
        return [], []
    keep = keep or set()
    removed, warns = [], []
    for rel in m.get('files', []):
        if rel in keep:
            continue
        p = os.path.join(tgt, rel.replace('/', os.sep))
        # страховка: только внутри trigger/ приёмника
        rp = os.path.normpath(p)
        if os.sep + 'trigger' + os.sep not in rp + os.sep:
            warns.append('purge: %s вне trigger/ — ПРОПУЩЕН' % rel)
            continue
        if os.path.exists(p):
            # правили руками после переноса?
            h0 = (m.get('hashes') or {}).get(rel)
            if h0 and fhash(p) != h0:
                warns.append('purge: %s менялся после переноса — удаляю (артефакт деплоя)' % rel)
            try:
                os.remove(p)
                removed.append(rel)
            except OSError as e:
                warns.append('purge: не удалён %s (%s)' % (rel, e))
    # пустые папки-артефакты (снизу вверх)
    dirs = sorted({os.path.dirname(rel) for rel in m.get('files', [])}, key=lambda d: -d.count('/'))
    for d in dirs:
        if d in ('trigger', '', '.'):
            continue
        p = os.path.join(tgt, d.replace('/', os.sep))
        if os.path.isdir(p) and not os.listdir(p):
            try:
                os.rmdir(p)
            except OSError:
                pass
    if removed:
        log('purge: удалено файлов прошлого деплоя: %d' % len(removed))
    # записи каталога прошлого деплоя, которых НЕТ в keep_entries
    # (смена deploy_to / набора папок) — точечное удаление строк
    # по regex-ключу (не по точному тексту: редактор мог
    # переформатировать catalog.lml).
    keep_entries = keep_e or set()
    cat_p = os.path.join(tgt, 'trigger', 'catalog.lml')
    n_cat = 0
    if m.get('catalog_entries') and os.path.exists(cat_p):
        cat = io.open(cat_p, 'rb').read().decode('utf-8', errors='replace')
        for key in m['catalog_entries']:
            if key in keep_entries:
                continue
            # строка записи верхнего уровня + её дочерние (отступ)
            pat = re.compile(r"^[ \t]*'?" + re.escape(key) + r"'?:[^\n]*\n(?:[ \t]+[^\n]*\n)*", re.M)
            cat2 = pat.sub('', cat, count=1)
            if cat2 != cat:
                cat = cat2
                n_cat += 1
        if n_cat:
            io.open(cat_p, 'wb').write(cat.encode('utf-8'))
            log('purge: удалено записей каталога: %d' % n_cat)
    # header-блок старого deploy_to в code.j (append-режим)
    hb = m.get('header_block')
    if hb and hb not in keep_entries:
        cj = os.path.join(tgt, 'trigger', 'code.j')
        if os.path.exists(cj):
            s = io.open(cj, 'rb').read().decode('utf-8', errors='replace')
            beg = '// === %s header (перенос) ===' % hb
            endm = '// === конец %s header ===' % hb
            pat = re.escape(beg) + r'[\s\S]*?' + re.escape(endm) + r'\n?'
            s2 = re.sub(pat, '', s)
            if s2 != s:
                io.open(cj, 'wb').write(s2.encode('utf-8'))
                log('purge: удалён header-блок %s из code.j' % hb)
    return removed, warns
