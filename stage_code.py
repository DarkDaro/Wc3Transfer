# 17.09: Этап code — замена литералов равкодов в .j коде по маппингу
# Вход: transfer_mapping.json + cfg['code']['trigger_dirs'] (пусто = только UFS-папки
# источника, заданные в cfg['code']['deploy_to']).
# Литералы: 'Xyyy' в одинарных кавычках. Заменяются ТОЛЬКО ID из маппинга,
# у которых old != new. B-литералы: проверка контекста не автоматизирована —
# B-замены требуют подтверждения (выводятся в отчёт, заменяются только с --allow-b).
import io, os, sys, json, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import deploy_manifest

def doo_unit_types(p):
    """21.09: типы юнитов на карте приёмника (map/war3mapUnits.doo).
    Формат: 'W3do'(4) ver(4) subver(4) num(4), записи с 16, шаг 111 байт
    (fixed + itemdata), typeId = первые 4 байта записи. Валидация:
    найденных позиций >= num-2 иначе предупреждение."""
    import struct
    out = set()
    if not os.path.exists(p):
        return out, 0
    s = io.open(p, 'rb').read()
    num = struct.unpack_from('<I', s, 12)[0]
    for i in range(num):
        off = 16 + i * 111
        if off + 4 > len(s):
            break
        rc = s[off:off + 4].decode('latin-1', errors='replace')
        if re.match(r'^[A-Za-z][0-9A-Za-z]{3}$', rc):
            out.add(rc)
    return out, num


def cat_parse_flags(text):
    """catalog.lml донора -> {плоский ключ: [флаги]}.
    21.09 фикс C: перенос флагов Run/Closed/Comment. Структура каталога:
    0-индент — папки, 4-индент — записи-триггеры, 8-индент — флаги
    записи. Ключ = 'папка запись' — ровно как деплой называет файлы
    (плоско, префикс папки), поэтому сопоставление идёт по базовому
    имени переносимого файла."""
    out = {}
    folder = None
    cur_key = None
    for l in text.splitlines():
        if re.match(r'^\S', l):              # 0-индент: папка/разделитель
            m = re.match(r"^'?(.*?)'?:", l)
            folder = m.group(1) if m else None
            cur_key = None
        elif re.match(r'^    \S', l):        # 4-индент: запись
            m = re.match(r"^    '?(.*?)'?:", l)
            if m and m.group(1):
                cur_key = (folder + ' ' + m.group(1)) if folder else m.group(1)
                out.setdefault(cur_key, [])
            else:
                cur_key = None
        elif cur_key is not None and re.match(r'^        \S', l):
            out[cur_key].append(l.strip())   # 8-индент: флаг записи
    return out

def main():
    cfgp = sys.argv[1]
    dry = '--dry-run' in sys.argv
    allow_b = '--allow-b' in sys.argv
    cfg = json.load(io.open(cfgp, 'rb'))
    here = os.path.dirname(os.path.abspath(cfgp))
    src = cfg['source']
    tgt = cfg['target']

    mp = json.load(io.open(os.path.join(here, cfg['mapping']['pkl'].replace('.pkl', '.json')), 'rb'))
    # литералы: old != new. 21.10: один и тот же равкод в разных типах
    # может получить разные ID — такую замену не угадываем, пропускаем.
    lit = {}
    amb = {}
    for k, new in mp.items():
        t, old = k.split(':', 1)
        if old != new:
            if old in lit and lit[old][0] != new:
                amb.setdefault(old, set()).update((lit[old][0], new))
                continue
            lit[old] = (new, t)
    for old in amb:
        lit.pop(old, None)
    if amb:
        print('ВНИМАНИЕ: равкод в разных типах получил разные ID — замена пропущена:')
        for old in sorted(amb):
            print('  %s -> %s' % (old, ', '.join(sorted(amb[old]))))

    # какие .j файлы источника содержат литералы
    # код: code-split/*.j (сплит) + trigger/*.j
    # war3map.j (монолит всей карты) — ТОЛЬКО если явно включён в
    # конфиге (полный перенос карты); для частичного он тащит чужой код
    trig_src = os.path.join(src, 'trigger')
    files = []
    if cfg['code'].get('include_monolith'):
        wj = os.path.join(src, 'map', 'war3map.j')
        if os.path.exists(wj):
            files.append(wj)
    cs = os.path.join(src, 'code-split')
    if os.path.isdir(cs):
        for f in sorted(os.listdir(cs)):
            if f.endswith('.j'):
                files.append(os.path.join(cs, f))
    # 18.09: only_dirs — переносить ТОЛЬКО выбранные подпапки
    only = [d.strip() for d in cfg['code'].get('only_dirs', []) if d.strip()]
    # 22.10: набор выбора — явные исключения триггеров (exclude_triggers):
    # матч по имени файла ('01-PA1.j'), по пути донора ('2-Triggers/файл')
    # или по базе без расширения ('WillZoero'). code-split не фильтруется
    # (вырезка функций из монолита должна остаться целой).
    import transfer_set as tset
    sel = tset.load(cfgp, cfg)
    _exc = sel.get('exclude_triggers', [])

    def trig_skipped(path):
        if not _exc:
            return False
        base = os.path.basename(path)
        rel = os.path.relpath(path, trig_src).replace(os.sep, '/')
        return (base in _exc or rel in _exc
                or os.path.splitext(base)[0] in _exc)

    if _exc:
        print('перенос-набор: исключений триггеров: %d (%s%s)' % (
            len(_exc), ', '.join(_exc[:6]), ' ...' if len(_exc) > 6 else ''))
    for root, dirs, fs in os.walk(trig_src):
        rel_root = os.path.relpath(root, trig_src)
        if only and rel_root != '.' and not any(rel_root == od or rel_root.startswith(od + os.sep) for od in only):
            dirs[:] = []
            continue
        for f in fs:
            if f.endswith('.j'):
                p = os.path.join(root, f)
                if trig_skipped(p):
                    continue
                files.append(p)

    # 21.09 фикс D: GUI-триггеры донора = пары .lml+.txt в trigger/.
    # .lml — тело GUI-триггера (редактор генерит из него Trig_X_Actions
    # и InitTrig_X при сборке), .txt — описание. Переносим их как есть
    # (нативный формат), НЕ инлайним в скрипт — инлайн ломал ссылки
    # gg_trg_X (TriggerEvaluate(null) = false, триггер мёртв).
    # Универсально: GUI-триггер = наличие .lml, .txt опционален.
    gui_pairs = []
    orphan_txts = []   # 22.10: .txt без пары .lml (текстовые триггеры/заметки)
    for root, dirs, fs in os.walk(trig_src):
        rel_root = os.path.relpath(root, trig_src)
        if only and rel_root != '.' and not any(rel_root == od or rel_root.startswith(od + os.sep) for od in only):
            dirs[:] = []
            continue
        for f in sorted(fs):
            if f.endswith('.lml') and f != 'catalog.lml' and f != 'variable.lml':
                lml_p = os.path.join(root, f)
                if trig_skipped(lml_p):
                    continue
                txt_p = lml_p[:-4] + '.txt'
                gui_pairs.append((lml_p, txt_p if os.path.exists(txt_p) else None))
            elif f.endswith('.txt') and not (rel_root == '.' and f == 'code.txt'):
                # 22.10: осиротевший .txt (БЕЗ парного .lml) — текстовый
                # триггер или заметка пользователя. Раньше его молча
                # выбрасывали — терялись «текстовые триггеры» донора.
                # Корневой code.txt — текстовый спутник code.j (шапка),
                # его не переносим.
                if (f[:-4] + '.lml') not in fs and not trig_skipped(os.path.join(root, f)):
                    orphan_txts.append(os.path.join(root, f))

    b_hits = []   # B-литералы (нужен контекст)
    plain_hits = {}
    # 21.09: типы юнитов приёмника (для null-конверта битых gg_unit)
    map_units = None
    null_hits = set()
    doo_p = os.path.join(tgt, 'map', 'war3mapUnits.doo')
    map_units, doo_n = doo_unit_types(doo_p)
    if map_units:
        print('типов юнитов на карте приёмника (doo):', len(map_units), '(записей:', str(doo_n) + ')')

    # 20.09 fix №3: однопроходная замена литералов. Цикл замен подряд
    # давал ЦЕПНЫЕ подмены (A001->B002, затем свежевставленный B002->X003).
    # Один re.sub по всем токенам сразу: вставленный new повторно не матчится.
    lit_sub = None
    if lit:
        toks = [t for t in lit if not (t[0] == 'B' and not allow_b)]
        if toks:
            # 20.09 fix №3b: ГРУППИРОВКА в скобки! Без них 'A001|B002' в
            # regex = "'A001" ИЛИ "B002'" — матчилась любая пара кавычек
            # ('ol' и пр.) → KeyError в _sub. Крах stage_code на живом прогоне.
            pat_l = re.compile("'(" + "|".join(re.escape(t) for t in toks) + ")'")

            def _sub(m):
                return "'" + lit[m.group(1)][0] + "'"

            lit_sub = (pat_l, _sub)

    # 18.09 (v5): префикс функций импорта.
    # Собираю имена всех функций донора из переносимых
    # файлов, потом переименовываю объявления и вызовы.
    prefix = cfg['code'].get('func_prefix', '').strip()
    donor_funcs = set()
    if prefix:
        for p in files:
            s = io.open(p, 'rb').read().decode('utf-8', errors='replace')
            for m in re.finditer(r'\bfunction\s+([A-Za-z_][A-Za-z0-9_]*)\b', s):
                # 21.09: InitTrig_* НЕ префиксуются — редактор генерит
                # вызовы InitTrig_<имя записи каталога> по значению
                # записи, префикс ломает линковку триггеров.
                if m.group(1).startswith('InitTrig_'):
                    continue
                donor_funcs.add(m.group(1))
        print('префикс функций:', prefix, '| функций донора:', len(donor_funcs),
              '| InitTrig_* пропущено')
    # 22.10: префиксация одним проходом. Прежний цикл («4 regexa на каждое
    # из ~12 тыс. имён на каждый из ~2 тыс. файлов») давал десятки млн
    # regex-операций и был корневой причиной медленного stage_code.
    # Один проход по идентификаторам: имя в множестве (O(1)) + контекст
    # (function X / call X( / executeFunc X( / ExecuteFunc("X") / X(
    # и пробелные варианты). Перебор альтернатив из 10+ тыс. имён тоже
    # оказался медленным на больших файлах, поэтому именно множество.
    prefix_sub = None
    if prefix and donor_funcs:
        _ctx_re = re.compile(
            r'(?:\bfunction\s+'
            r'|\b(?:call|(?i:executefunc))\s*\(\s*'
            r'|(?i:executefunc\s*\(\s*")'
            r')$')

        _ident_re = re.compile(r'\b[A-Za-z_][A-Za-z0-9_]*\b')

        def prefix_sub(text):
            out = []
            last = 0
            for m in _ident_re.finditer(text):
                nm = m.group(0)
                if nm not in donor_funcs:
                    continue
                start, end = m.span()
                # контекст: объявление function X, вызов call/executeFunc
                # X( (в т.ч. с пробелами), строковый ExecuteFunc("X"),
                # голый вызов X( (lineahead \s*\()
                before = text[max(0, start - 220):start]
                after = text[end:end + 4]
                if (_ctx_re.search(before)
                        or re.match(r'\s*\(', after)):
                    out.append(text[last:start])
                    out.append(prefix)
                    last = start
            out.append(text[last:])
            return ''.join(out)



    for p in files:
        s = io.open(p, 'rb').read().decode('utf-8', errors='replace')
        for m in re.finditer(r"'([0-9A-Za-z]{4})'", s):
            tok = m.group(1)
            if tok in lit:
                new, t = lit[tok]
                # 20.09 fix №6: было `tok.lower() in {k.lower() ...}` —
                # тавтология (tok уже B-литерал из lit). Любой B-токен
                # требует контекста — упрощено до проверки префикса.
                if tok[0] == 'B':
                    # B: и баффы и декор — нужен контекст
                    b_hits.append((p, tok, new, t))
                else:
                    plain_hits.setdefault(p, set()).add((tok, new))

    print('.j файлов источника:', len(files))
    print('обычных литералов для замены:', sum(len(v) for v in plain_hits.values()), 'в', len(plain_hits), 'файлах')
    for p2, pairs in sorted(plain_hits.items()):
        ps = sorted(pairs)
        print('  %s: %d (%s%s)' % (os.path.basename(p2), len(ps), ', '.join(a+'->'+b for a, b in ps[:6]), ' ...' if len(ps) > 6 else ''))
    print('B-литералов (нужен контекст):', len(b_hits))
    for p, tok, new, t in b_hits[:10]:
        print('  ', os.path.basename(p), tok, '->', new, '(' + t + ')')

    if dry:
        print('(dry-run: файлы не копируются)')
        return

    # 20.09: purge артефактов прошлого деплоя ПО МАНИФЕСТУ.
    # Смена версии утилиты / deploy_to / набора папок оставляла
    # "поколения" файлов (дубли в редакторе). Чистим только то,
    # что записано в манифесте — никогда не сканируем вслепую.
    # keep = файлы, которые НОВЫЙ прогон сейчас запишет (не трогаем).
    # deploy_to/entry_name нужны purge ДО записи — определяю здесь.
    deploy_to = cfg['code'].get('deploy_to', 'UFS')
    cat_p0 = os.path.join(tgt, 'trigger', 'catalog.lml')
    entry_name = deploy_to
    if os.path.exists(cat_p0):
        cat0 = io.open(cat_p0, 'rb').read().decode('utf-8', errors='replace')
        # 20.10 (фикс дым-теста): кавычки опциональны. Наш kv() пишет
        # ключи вида 213-LIA БЕЗ кавычек (need_q=False) — прежний regex
        # с обязательными кавычками на повторном прогоне entry не видел,
        # и файлы переезжали из <NNN-dep> в <dep> (purge+перекат).
        m0 = re.search(r"^'?(\d{3}-" + re.escape(deploy_to) + r")'?:", cat0, re.M)
        if m0:
            entry_name = m0.group(1)

    # 20.10: раскладка триггеров. Редактор триггеров НЕ поддерживает
    # вложенные папки, зато НЕ против нескольких папок верхнего уровня.
    # Прежняя раскладка сваливала весь импорт в <entry>\ : подпапка донора
    # превращалась в префикс имени файла — визуально одна папка-свалка.
    # Режим 'folders': каждая папка триггеров донора -> СВОЯ папка
    # верхнего уровня trigger\<имя донора>\ (имя сохраняется 1:1);
    # корень донора / code-split / монолит идут в <entry>\ как раньше.
    # 'flat' — прежняя раскладка (по умолчанию, обратная совместимость).
    folders_mode = cfg['code'].get('folders', 'flat')

    def _adj_name(folder):
        # вложенные уровни донора в ИМЕНИ файла запрещены ОС
        # ('a\b 1-x.j' на Windows — это папка 'a'), заменяю sep на '_'
        return folder.replace(os.sep, '_') if folder else ''

    warped_warned = set()

    def _dst(p):
        # 20.10: ЕДИНОЕ правило раскладки (раньше keep и запись дублировали
        # логику вручную и при смене раскладки разъезжались).
        # Возвращает путь от tgt (os.sep).
        base = os.path.basename(p)
        if base == 'war3map.j' and 'trigger' not in os.path.relpath(p, src):
            # 20.09 fix №1: монолит — явный путь <entry>\war3map.j
            return os.path.join('trigger', entry_name, 'war3map.j')
        if 'code-split' in p:
            return os.path.join('trigger', entry_name, 'code-split ' + base)
        rel_t = os.path.relpath(p, trig_src)
        folder = os.path.dirname(rel_t)
        if not folder or folder == '.':
            # корневой файл донора (не code.j — он в header)
            return os.path.join('trigger', entry_name, base)
        if os.sep in folder or '/' in folder:
            # вложенность донора в folders-режиме тоже плоским именем:
            # редактор вложенность не умеет
            if folder not in warped_warned:
                warped_warned.add(folder)
                print('ВНИМАНИЕ: вложенная папка донора', folder,
                      '-> плоское имя с "_" (редактор не умеет вложенность)')
            folder = _adj_name(folder)
        if folders_mode == 'folders' and folder not in FOREIGN:
            return os.path.join('trigger', folder, base)
        return os.path.join('trigger', entry_name, folder + ' ' + base)

    def _dst_gui(lml_p):
        # 20.10: GUI-пары (.lml+.txt) по тем же правилам раскладки
        rel_t = os.path.relpath(lml_p, trig_src)
        folder = os.path.dirname(rel_t)
        base = os.path.splitext(os.path.basename(lml_p))[0]
        if not folder or folder == '.':
            return os.path.join('trigger', entry_name, base + '.lml')
        if os.sep in folder or '/' in folder:
            folder = _adj_name(folder)
        if folders_mode == 'folders' and folder not in FOREIGN:
            return os.path.join('trigger', folder, base + '.lml')
        return os.path.join('trigger', entry_name, folder + ' ' + base + '.lml')

    def _dst_txt(txt_p):
        # 22.10: осиротевший .txt — та же раскладка, что у .lml
        rel_t = os.path.relpath(txt_p, trig_src)
        folder = os.path.dirname(rel_t)
        base = os.path.splitext(os.path.basename(txt_p))[0]
        if not folder or folder == '.':
            return os.path.join('trigger', entry_name, base + '.txt')
        if os.sep in folder or '/' in folder:
            folder = _adj_name(folder)
        if folders_mode == 'folders' and folder not in FOREIGN:
            return os.path.join('trigger', folder, base + '.txt')
        return os.path.join('trigger', entry_name, folder + ' ' + base + '.txt')

    # 20.10 (фикс дым-теста): FOREIGN определяем ЗАРАНЕЕ — _dst/_dst_gui
    # ссылаются на него, а folder_keys прогоняет _dst по всем файлам.
    # Ниже только МУТИРУЕМ (.add), не перепривязываем.
    FOREIGN = set()

    # 20.10: ключи каталога нового прогона (папки деплоя) — для keep_e
    def _folder_keys():
        ks = set()
        for p in files:
            parts = _dst(p).split(os.sep)
            if len(parts) >= 3 and parts[1] != entry_name:
                ks.add(parts[1])
        return ks

    folder_keys = _folder_keys()

    # 20.10: FOREIGN — папки приёмника, имя которых совпало с папкой
    # донора, но которые утилита НЕ записывала (нативный контент).
    # Файлы такой папки донора пойдут плоско в <entry> — без подмешивания.
    old_m = deploy_manifest.load_manifest(cfgp)
    old_files = set((old_m or {}).get('files') or [])
    if folders_mode == 'folders':
        for fk in sorted(folder_keys):
            dk = os.path.join(tgt, 'trigger', fk)
            ours = any(rel.startswith('trigger/' + fk + '/') for rel in old_files)
            if os.path.isdir(dk) and os.listdir(dk) and not ours:
                FOREIGN.add(fk)
                print('ВНИМАНИЕ: папка', fk, 'уже есть в приёмнике и не записана утилитой',
                      '— файлы этой папки донора пойдут плоско в <entry>')
        if FOREIGN:
            # fallback-файлы ушли в <entry> — пересчёт ключей каталога
            folder_keys = _folder_keys()
    keep = set()
    if old_m:    # 20.09 fix №6: dry выходит return-ом выше — not dry мёртвое
        # 20.10: keep по тем же правилам (_dst/_dst_gui), что и запись —
        # раньше правило дублировалось вручную и расползалось
        for p in files:
            keep.add(_dst(p).replace(os.sep, '/'))
        # 21.09 фикс D: GUI-пары тоже в keep (.txt — спутник .lml)
        for lml_p, txt_p in gui_pairs:
            d = _dst_gui(lml_p).replace(os.sep, '/')
            keep.add(d)
            if txt_p:
                keep.add(d[:-4] + '.txt')
        # 20.09: keep_e — ключи записей каталога нового прогона.
        # Даже если запись \d{3}-X уже есть (cat_add не добавит),
        # purge не должен сносить её: deploy_to и entry_name живут.
        # 20.10: + папки донора (режим folders)
        keep_e = {deploy_to, entry_name} | folder_keys
        removed, warns = deploy_manifest.purge(cfgp, tgt, keep=keep, keep_e=keep_e)
        for w in warns:
            print(w)

    # копируем файлы с заменами в target/trigger/<deploy_to>
    # (deploy_to/entry_name/cat_p0 определены выше — purge)

    # 18.09 (v4): подпапки раскладываю в КОРЕНЬ trigger/
    # (редактор ищет папки записей в корне, не в deploy_to).
    # Сам deploy_to остаётся ПУСТОЙ папкой-разделителем.
    trig_tgt = os.path.join(tgt, 'trigger')
    dst_dir = os.path.join(trig_tgt, entry_name)
    os.makedirs(dst_dir, exist_ok=True)
    n = 0
    written = []    # 20.09: манифест — что реально записали
    cat_added = []  # 20.09: манифест — ключи записей каталога, добавленных этим прогоном
    header_rel = None    # 20.09 fix №4: путь header-файла (file-режим) — исключение из секции каталога
    # 18.09 (v5-fix): шапка донора (code.j в корне trigger)
    # уходит в header-режим — из основного цикла исключаю,
    # иначе функции продублируются (<entry>_code.j + header)
    header_src = os.path.join(trig_src, 'code.j')
    skip_header = os.path.exists(header_src)
    for p in files:
        if skip_header and os.path.abspath(p) == os.path.abspath(header_src):
            continue
        s = io.open(p, 'rb').read().decode('utf-8', errors='replace')
        s2 = lit_sub[0].sub(lit_sub[1], s) if lit_sub else s
        # 18.09 (v5): префикс функций — объявления и вызовы.
        # Только имена функций донора, не нативы/константы.
        # 22.10: один предкомпилированный проход вместо 4 замены
        # на каждое имя (десятки млн regex-операций — до рефактора).
        if prefix_sub is not None:
            s2 = prefix_sub(s2)
        # 20.09: файлы донора без литералов/префикса тоже переносим
        # (копия как есть), иначе чистые триггеры молча терялись.
        # 20.09 fix №6: было `if s2 != s or True:` — выродившийся фикс
        # «файлы без литералов», всегда истина. Условие не нужно.
        # (s2 == s — копия как есть), иначе чистые триггеры молча
        # терялись. dst-правила те же (v6: плоско + префикс папки).

        # 21.09: битые gg_unit_XXX_YYYY -> null (по заказу юзера, ВКЛ
        # по умолчанию). Юнит-тип сверяется с map/war3mapUnits.doo
        # ПРИЁМНИКА: редактор объявляет gg_unit только для юнитов,
        # стоящих на карте. Ссылка на отсутствующий тип = undefined
        # переменная -> каскад ошибок компиляции.
        if cfg['code'].get('null_broken_gguits', True) and map_units is not None:
            def _gg_null(m):
                if m.group(1).lower() not in map_units and m.group(1) not in map_units:
                    null_hits.add(m.group(0))
                    return 'null'
                return m.group(0)
            s2 = re.sub(r'gg_unit_([A-Za-z0-9]{4})_\w+', _gg_null, s2)

        if True:
            # 20.10: раскладка общим правилом _dst — flat (префикс папки в
            # имени файла, всё в <entry>) или folders (папка донора -> своя
            # папка верхнего уровня trigger\). Монолит/code-split — в <entry>.
            dst = os.path.join(tgt, _dst(p))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            io.open(dst, 'wb').write(s2.encode('utf-8'))
            written.append(os.path.relpath(dst, tgt).replace(os.sep, '/'))
            n += 1
    print('файлов с заменами записано:', n,
          ('-> ' + deploy_to) if folders_mode == 'flat' else '(раскладка по папкам донора)')
    # 21.09: отчёт null-конверта
    if null_hits:
        print('битых gg_unit -> null: %d переменных (%d типов)' % (len(null_hits), len({h[8:12] for h in null_hits})))
    elif map_units is not None:
        print('битых gg_unit не найдено')
    if map_units is not None and not map_units:
        print('ВНИМАНИЕ: doo приёмника пуст/не найден — null-конверт пропущен')
    if b_hits and not allow_b:
        print('ВНИМАНИЕ: B-литералы НЕ заменены (нужен контекст, --allow-b)')

    # 21.09 фикс D: копирование GUI-пар (.lml+.txt) в папку деплоя,
    # плоско с префиксом папки — как .j файлы. Литералы в .lml живут
    # без кавычек (Const : A001) — lit_sub их не трогает; если GUI-
    # триггер ссылает литерал из маппинга, он заменяется на этапе
    # таблиц (ID в таблицах приёмника уже новые). Префиксация функций
    # к .lml не применяется: тела GUI генерит редактор.
    n_gui = 0
    for lml_p, txt_p in gui_pairs:
        # 20.10: раскладка общим правилом _dst_gui (flat/folders)
        d = os.path.join(tgt, _dst_gui(lml_p))
        # 22.10: ГЛАВНАЯ ПРАВКА (корень «триггеры не записались»):
        # папка приёмника могла не существовать (новая папка донора,
        # folders-режим) — open падал с FileNotFoundError, этап рушился
        # ПОСЛЕ копирования .j, но ДО записи каталога и манифеста,
        # и в журнале это выглядело как «триггеры частично перенеслись».
        os.makedirs(os.path.dirname(d), exist_ok=True)
        io.open(d, 'wb').write(io.open(lml_p, 'rb').read())
        written.append(os.path.relpath(d, tgt).replace(os.sep, '/'))
        n_gui += 1
        if txt_p:
            dtxt = d[:-4] + '.txt'    # спутник .lml — рядом с ним
            io.open(dtxt, 'wb').write(io.open(txt_p, 'rb').read())
            written.append(os.path.relpath(dtxt, tgt).replace(os.sep, '/'))
    if n_gui:
        print('GUI-триггеров (пары .lml+.txt) перенесено:', n_gui)

    # 22.10: осиротевшие .txt — текстовые триггеры/заметки донора.
    # Пишем тем же механизмом, что и GUI-пары; в built_rels запоминаем
    # свои пути, чтобы builder каталога сделал из них записи (обычные
    # .txt в каталог не попадают как спутники .lml).
    built_rels = set()
    n_orph = 0
    for txt_p in orphan_txts:
        d = os.path.join(tgt, _dst_txt(txt_p))
        os.makedirs(os.path.dirname(d), exist_ok=True)
        io.open(d, 'wb').write(io.open(txt_p, 'rb').read())
        rel_d = os.path.relpath(d, tgt).replace(os.sep, '/')
        written.append(rel_d)
        built_rels.add(rel_d)
        n_orph += 1
    if n_orph:
        print('текстовых триггеров (.txt без .lml) перенесено:', n_orph)


    # 18.09 (v5): шапка донора — header-режим.
    # Донор с триггерами имеет code.j в корне trigger
    # (шапка с хелперами, нужная триггерам ДО их компиляции).
    header_mode = cfg['code'].get('header_mode', 'file')
    if os.path.exists(header_src) and not dry:
        hs = io.open(header_src, 'rb').read().decode('utf-8', errors='replace')
        hs2 = lit_sub[0].sub(lit_sub[1], hs) if lit_sub else hs
        # 18.09 (v5-fix): префикс функций и в шапке тоже
        # 22.10: тот же один предкомпилированный проход
        if prefix_sub is not None:
            hs2 = prefix_sub(hs2)
        # 21.09: null-конверт и в шапке (code.j донора тоже ссылается на юнитов)
        if cfg['code'].get('null_broken_gguits', True) and map_units is not None:
            def _gg_null_h(m):
                if m.group(1).lower() not in map_units and m.group(1) not in map_units:
                    null_hits.add(m.group(0))
                    return 'null'
                return m.group(0)
            hs2 = re.sub(r'gg_unit_([A-Za-z0-9]{4})_\w+', _gg_null_h, hs2)
        if header_mode == 'append':
            # 21.09 v2: globals донора НЕ дописываются в конец —
            # редактор собирает все globals в ОДНУ секцию в начале
            # war3map.j, вторая globals-секция после функций = cascade
            # ('Statement outside of function' тысячи штук). Разбор:
            # globals-блок донора вливается в РОДНУЮ globals-секцию
            # приёмника (перед её endglobals), функции — в конец.
            tgt_header = os.path.join(trig_tgt, 'code.j')
            beg = '// === %s header (перенос) ===' % deploy_to
            endm = '// === конец %s header ===' % deploy_to
            if os.path.exists(tgt_header):
                th = io.open(tgt_header, 'rb').read().decode('utf-8', errors='replace')
                pat = re.escape(beg) + r'[\s\S]*?' + re.escape(endm) + r'\n?'
                th = re.sub(pat, '', th)
                # 21.09: разбор донорского header на globals-часть и код
                hlines = hs2.replace('\r\n', '\n').split('\n')
                # границы первой globals...endglobals (тела vJass library
                # уже свёрнуты в доноре? нет — code.j донора сырой: globals
                # на верху, внутри — только глобальные декларации)
                g_start = g_end = None
                depth = 0
                for i, l in enumerate(hlines := hs2.replace('\r\n', '\n').split('\n')):
                    st = l.strip()
                    if st == 'globals' and g_start is None:
                        g_start = i
                        depth += 1
                    elif st == 'endglobals' and g_start is not None:
                        g_end = i
                        break
                if g_start is not None and g_end is not None:
                    don_g = '\n'.join(hlines[g_start + 1:g_end]).rstrip()
                    donor_code = '\n'.join(hlines[:g_start] + hlines[g_end + 1:])
                    # родной globals приёмника: первая globals...endglobals
                    t_start = t_end = None
                    for i, l in enumerate(th.replace('\r\n', '\n').split('\n')):
                        st = l.strip()
                        if st == 'globals' and t_start is None:
                            t_start = i
                        elif st == 'endglobals' and t_start is not None:
                            t_end = i
                            break
                    if t_start is not None and t_end is not None:
                        tl = th.replace('\r\n', '\n').split('\n')
                        # 21.09: имя globals-строки = [constant] TYPE (array)? NAME
                        # ('boolean array seen' -> seen, 'integer n = 0' -> n)
                        GV = r'\s*(?:constant\s+)?(\w+)\s+(?:array\s+)?(\w+)\s*(?:=.*)?$'

                        def gname(line):
                            mm = re.match(GV, line)
                            return mm.group(2) if mm else None
                        have = set()
                        for l in tl[t_start + 1:t_end]:
                            nm = gname(l)
                            if nm:
                                have.add(nm)
                        add_lines = []
                        for l in hlines[g_start + 1:g_end]:
                            nm = gname(l)
                            if nm and nm not in have:
                                add_lines.append(l)
                        new_g = '\n'.join(tl[t_start + 1:t_end]).rstrip('\n')
                        if add_lines:
                            new_g += '\n' + '\n'.join(add_lines).rstrip()
                        # склейка: до globals + расширенный globals + после + донор-код
                        th2 = (('\n'.join(tl[:t_start]) + '\n'
                                if t_start else '')
                               + 'globals\n' + new_g + '\nendglobals\n'
                               + '\n'.join(tl[t_end + 1:])).rstrip()
                        print('шапка донора: globals слиты в родную секцию (%d строк добавлено)' % len(add_lines))
                    else:
                        # у приёмника нет globals — донорский код как есть
                        donor_code = hs2
                        th2 = th.rstrip()
                    th2 = th2.rstrip() + '\n\n' + beg + '\n' + donor_code.rstrip() + '\n' + endm + '\n'
                else:
                    # донор без globals-секции — старое поведение
                    th2 = th.rstrip() + '\n\n' + beg + '\n' + hs2.rstrip() + '\n' + endm + '\n'
                io.open(tgt_header, 'wb').write(th2.encode('utf-8'))
                print('шапка донора: дописана в code.j приёмника (блок %s)' % beg)
                header_block_name = deploy_to    # 20.09: в манифест (purge старого блока при смене deploy_to)
            else:
                print('шапка донора: code.j приёмника не найден — пропуск')
        else:
            # отдельный файл <entry>-header.j + запись в каталоге
            # ПЕРЕД разделителем <entry_name>
            hf = os.path.join(trig_tgt, entry_name + '-header.j')
            io.open(hf, 'wb').write(hs2.encode('utf-8'))
            written.append(os.path.relpath(hf, tgt).replace(os.sep, '/'))    # 20.09: манифест
            # 20.09 fix №4: header-файл НЕ должен попадать ребёнком в секцию
            # каталога — его запись уже вставляется top-level перед
            # разделителем (иначе дубль: top-level + ребёнок).
            header_rel = os.path.relpath(hf, tgt).replace(os.sep, '/')
            print('шапка донора: записана в', hf)
            cat_p2 = os.path.join(trig_tgt, 'catalog.lml')
            if os.path.exists(cat_p2):
                cat2 = io.open(cat_p2, 'rb').read().decode('utf-8', errors='replace')
                hname = entry_name + '-header'
                have_h = re.search(r"^'?" + re.escape(hname) + r"'?:", cat2, re.M)
                if have_h:
                    print('catalog.lml: запись', hname, 'уже есть')
                else:
                    cat_added.append(hname)    # 20.09: манифест
                    # вставить ПЕРЕД разделителем <entry_name>
                    # 20.09 fix №4: esc() — апостроф в имени ломал каталог
                    esc_h = lambda x: x.replace(chr(39), chr(39) * 2)
                    m_ins = re.search(r"^'?" + re.escape(entry_name) + r"'?:", cat2, re.M)
                    hline = "'" + esc_h(hname) + "': '" + esc_h(deploy_to) + " header'\n"
                    if m_ins:
                        cat2 = cat2[:m_ins.start()] + hline + cat2[m_ins.start():]
                        io.open(cat_p2, 'wb').write(cat2.encode('utf-8'))
                        print('catalog.lml: запись', hname, 'вставлена перед', entry_name)
                    else:
                        cat2 = cat2.rstrip() + "\n" + hline
                        io.open(cat_p2, 'wb').write(cat2.encode('utf-8'))
                        print('catalog.lml: запись', hname, 'дописана в конец (разделитель не найден)')

    # 20.09 ПЕРЕПИСАНО: каталог приёмника НЕ СКАНИРУЕМ НИКОГДА
    # (инцидент MAPTEST: автодописка вписала 1938 строк мусора —
    # все папки «не из каталога», включая отключённые и пустые;
    # редактор показал их живыми триггерами, карта развалилась).
    # Пишем ТОЛЬКО свою секцию: разделитель deploy_to + наши файлы.
    # Секция идемпотентна: при повторе прогона заменяется целиком,
    # дубли имён невозможны по построению.
    if (n or n_gui) and cfg['code'].get('update_catalog', True):
        cat_p = os.path.join(tgt, 'trigger', 'catalog.lml')
        if os.path.exists(cat_p):
            cat = io.open(cat_p, 'rb').read().decode('utf-8', errors='replace')

            def esc(x):
                return x.replace(chr(39), chr(39) * 2)

            def need_q(x):
                return not re.match(r'^[0-9A-Za-z_-]+$', x)

            # 20.09 fix №10: значение записи = ИМЯ ТРИГГЕРА (после
            # номера файла), НЕ 'папка+файл'. Редактор генерит
            # InitTrig_<значение> и gg_trg_<значение>: при значении
            # 'Main 1-notepad' редактор создаст InitTrig_Main_1_notepad,
            # а код зовёт InitTrig_notepad -> триггеры не слинкуются.
            # Донор: '2-InicHero': 'InicHero'; имя может быть с пробелом:
            # '5-Damage Engine' -> 'Damage Engine'.
            def disp_of(x):
                m = re.search(r'\s\d+-', x)
                return x[m.end():] if m else (x.split('-', 1)[-1] if '-' in x else x)

            def kv(key, disp, indent):
                q = need_q(key) or need_q(disp)
                k = ("'" + esc(key) + "'") if q else key
                d = ("'" + esc(disp) + "'") if q else disp
                return indent + k + ': ' + d

            # наша секция: разделитель + наши файлы (с отступом 4)
            # 20.09 fix №2: ключ секции = entry_name (имя ПАПКИ деплоя),
            # не deploy_to — при нумерованной записи '213-JAR' в каталоге
            # файлы лежат в 213-JAR/, а дети должны быть под '213-JAR:',
            # иначе редактор не свяжет их с папкой.
            # 21.09 фикс C: флаги записей (Run/Closed/Comment) берём из
            # каталога ДОНОРА — сопоставление по плоскому ключу
            # 'папка запись' (= базовое имя файла деплоя).
            donor_flags = {}
            cat_src_p = os.path.join(trig_src, 'catalog.lml')
            if os.path.exists(cat_src_p):
                donor_flags = cat_parse_flags(
                    io.open(cat_src_p, 'rb').read().decode('utf-8', errors='replace'))
            # 20.10: секции каталога по факту РЕАЛЬНОЙ раскладки (written).
            # flat — одна секция entry_name; folders — отдельная секция на
            # каждую папку донора. Инцидент автодописки не повторяем:
            # пишем ТОЛЬКО свои секции, приёмник не сканируем.
            groups = {}      # секция -> [(запись, ключ флагов донора)]
            for rel in sorted(written):
                # 20.09 fix №4: header-файл (file-режим) в секцию не пишем —
                # его запись уже стоит top-level перед разделителем
                if rel == header_rel:
                    continue
                # 21.09 фикс D: обычный .txt (описание GUI-триггера) — не
                # запись каталога, это спутник .lml; запись уже добавлена
                # с .lml. Но 22.10: осиротевшие .txt (built_rels) — САМИ
                # записи каталога (текстовые триггеры без .lml).
                if rel.endswith('.txt') and rel not in built_rels:
                    continue
                parts = rel.split('/')
                if len(parts) != 3 or parts[0] != 'trigger':
                    continue    # страховка: ждём trigger/<секция>/<файл>
                _, sec, stem = parts[0], parts[1], os.path.splitext(parts[2])[0]
                # 21.09 фикс C: флаги берём из каталога донора по плоскому
                # ключу 'папка запись'. В flat префикс папки уже В имени
                # файла (совпадает с донорским ключом), в folders имя
                # записи чистое — собираем ключ из секции+записи.
                fkey = stem if (folders_mode != 'folders' or sec == entry_name) \
                    else sec + ' ' + stem
                groups.setdefault(sec, []).append((stem, fkey))
            if not groups:
                print('catalog.lml: записей для секций нет — пропускаю')
            else:
                # порядок секций: entry_name (разделитель), потом папки донора
                secs = []
                for sec in ([entry_name] if entry_name in groups else []) + \
                        sorted(k for k in groups if k != entry_name):
                    out = [kv(sec, disp_of(sec), '')]
                    for stem, fkey in groups[sec]:
                        # 20.09 fix №10: значение = ИМЯ ТРИГГЕРА (после номера),
                        # InitTrig_<значение> линкуется с кодом
                        out.append(kv(stem, disp_of(stem), '    '))
                        # 21.09 фикс C: флаги донора под записью (8-индент)
                        for fl in donor_flags.get(fkey, []):
                            out.append('        ' + fl)
                    secs.append((sec, chr(10).join(out) + chr(10)))
                # purge старых секций: наши ключи + deploy_to/entry_name
                # (смена нумерации/режима не оставляет старые)
                for sec_key in {deploy_to, entry_name} | set(groups):
                    pat = re.compile(r"^'?" + re.escape(sec_key) + r"'?:[^\n]*\n(?:(?:    [^\n]*)\n)*", re.M)
                    cat = pat.sub('', cat, count=1)
                cat2 = cat.rstrip() + chr(10) + chr(10).join(t for _, t in secs)
                io.open(cat_p, 'wb').write(cat2.encode('utf-8'))
                cat_added.extend(sec for sec, _ in secs)
                print('catalog.lml: секций %d, записей %d (%s)' % (
                    len(secs), len(groups) and sum(len(v) for v in groups.values()),
                    'flat' if folders_mode == 'flat' else 'папки донора'))
        else:
            print('catalog.lml не найден в приёмнике — пропускаю')

    # 20.09: запись манифеста деплоя (purge следующего прогона).
    # header_block: имя header-блока в code.j (append-режим), если писали.
    # merge_section: манифест общий с globals/code_cut — пишем
    # только свою секцию, чужие секции не затираем.
    if not dry:
        m = {
            'deploy_to': deploy_to,
            'files': sorted(written),
            # 20.09 fix: deploy_to/entry_name — в манифесте ВСЕГДА:
            # purge следующего прогона обязан снести запись каталога
            # при смене deploy_to (разделитель пишет автодописка ИЛИ
            # он уже есть от прошлого деплоя — в обоих случаях он наш).
            # 20.10: + ключи папок донора (folders) — purge следующего
            # прогона удалит их из каталога при смене режима/набора папок
            'catalog_entries': sorted(set(cat_added) | {deploy_to, entry_name}
                                      | set(folder_keys)),
            'header_block': locals().get('header_block_name'),
        }
        deploy_manifest.merge_section(cfgp, 'code', m)
        # хеши: по files нашей секции (merge сохранил чужие)
        full = deploy_manifest.load_manifest(cfgp) or {}
        deploy_manifest.record_hashes(cfgp, full, tgt)
        print('манифест деплоя: %d файлов, %d записей каталога' % (len(m['files']), len(m['catalog_entries'])))

if __name__ == '__main__':
    main()
