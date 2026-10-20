# 17.09: stage_code_cut — вырезание куска героя из монолита донора
# Режим 2 (карта без исходника редактора):
#   1. Точки входа (cfg['code_cut']['entries'] = ['GLAS4__I', ...])
#   2. BFS по вызовам: call X(, function X, ExecuteFunc("X")
#   3. Сбор: вырезанные функции + использованные globals
#   4. Замена литералов по маппингу
#   5. Отчёт: внешние globals (не вырезаны), РО-литералы (дамми/баффы/
#      способности/предметы для переноса), непокрытые литералы
# Выход: target/trigger/<deploy_to>/<имя>.j + code_cut_report.txt
import io, os, sys, json, re, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import deploy_manifest

def parse_monolith2(s):
    # корректный парсер: function ... endfunction, вне их — globals
    funcs = {}
    order = []
    globals_lines = []
    other_lines = []
    cur = None
    in_globals = False
    for l in s.splitlines():
        if cur is None:
            m = re.match(r'^function\s+(\S+)\s+takes', l)
            if m:
                cur = m.group(1)
                funcs[cur] = [l]
                order.append(cur)
                continue
            if re.match(r'^globals\b', l):
                in_globals = True
                globals_lines.append(l)
                continue
            if in_globals:
                globals_lines.append(l)
                if l.strip() == 'endglobals':
                    in_globals = False
                continue
            other_lines.append(l)
        else:
            funcs[cur].append(l)
            if l.strip() == 'endfunction':
                cur = None
    return funcs, order, globals_lines, other_lines

def calls(fn_body):
    out = set()
    for l in fn_body:
        for m in re.finditer(r'function\s+(\w+)', l):
            out.add(m.group(1))
        for m in re.finditer(r'\bcall\s+(\w+)\s*\(', l):
            out.add(m.group(1))
        for m in re.finditer(r'ExecuteFunc\(\s*"(\w+)"\s*\)', l):
            out.add(m.group(1))
    return out

def main():
    cfgp = sys.argv[1]
    dry = '--dry-run' in sys.argv
    cfg = json.load(io.open(cfgp, 'rb'))
    here = os.path.dirname(os.path.abspath(cfgp))
    cc = cfg.get('code_cut', {})
    if not cc.get('enabled'):
        print('code_cut выключен в конфиге')
        return
    entries = cc.get('entries', [])
    if not entries:
        print('code_cut.entries пуст — укажи init-функции героев')
        return
    src = cfg['source']
    mp = json.load(io.open(os.path.join(here, cfg['mapping']['pkl'].replace('.pkl', '.json')), 'rb'))
    lit = {}
    for k, new in mp.items():
        t, old = k.split(':', 1)
        if old != new:
            lit[old] = (new, t)

    mono_p = os.path.join(src, 'map', 'war3map.j')
    s = io.open(mono_p, 'rb').read().decode('utf-8', errors='replace')
    funcs, order, globals_lines, other_lines = parse_monolith2(s)
    print('монолит: функций %d, глобалок %d' % (len(funcs), len([l for l in globals_lines if '=' in l or re.match(r'^\s*(unit|group|integer|real|boolean|string|player|location|trigger|timer|item|ability|effect|sound|lightning|force|rect|widget|button|texttag|multiboard|trackable|gamecache|handle|agent|event|framehandle|timerdialog|leaderboard|quest|defeatcondition|ubersplat|weathereffect|fogmodifier|hashtable|conditionfunc|filterfunc|boolexpr|sound|dialog|button)\b', l)])))

    # BFS от точек входа
    seen = set()
    q = collections.deque(entries)
    while q:
        f = q.popleft()
        if f in seen or f not in funcs:
            continue
        seen.add(f)
        q.extend(calls(funcs[f]))
    print('точек входа: %d, вырезано функций: %d' % (len(entries), len(seen)))
    for e in entries:
        if e not in funcs:
            print('  ВНИМАНИЕ: точка входа %s не найдена в монолите' % e)

    # globals, используемые вырезанными функциями
    gnames = {}
    for l in globals_lines:
        m = re.match(r'^\s*(?:constant\s+)?(\w+)\s+(\w+)', l)
        if m:
            gnames[m.group(2)] = l.strip()
    used_g = set()
    for f in seen:
        for l in funcs[f]:
            for m in re.finditer(r'\b(\w+)\b', l):
                if m.group(1) in gnames:
                    used_g.add(m.group(1))
    internal_g = set()
    for f in seen:
        for l in funcs[f]:
            m = re.match(r'^\s*local\s+(?:constant\s+)?(\w+)\s+(\w+)', l)
            if m:
                internal_g.add(m.group(2))
    ext_g = sorted(used_g - internal_g)

    # литералы в вырезанном коде
    lit_hits = {}
    uncovered = set()
    for f in sorted(seen):
        for l in funcs[f]:
            for m in re.finditer(r"'([0-9A-Za-z]{4})'", l):
                tok = m.group(1)
                if tok in lit:
                    new, t = lit[tok]
                    lit_hits.setdefault(tok, (new, t))
                else:
                    uncovered.add(tok)

    # сборка выходного файла
    out_lines = []
    out_lines.append('// 17.09: вырезано из монолита %s' % os.path.basename(mono_p))
    out_lines.append('// точки входа: %s' % ', '.join(entries))
    out_lines.append('// функций: %d' % len(seen))
    out_lines.append('')
    out_lines.append('globals')
    for g in ext_g:
        out_lines.append('    ' + gnames[g])
    out_lines.append('endglobals')
    out_lines.append('')
    for f in order:
        if f in seen:
            out_lines.extend(funcs[f])
            out_lines.append('')
    body = chr(10).join(out_lines) + chr(10)
    # замена литералов (20.10: один проход, без цепочки old->new->old)
    def _lit_repl(m):
        tok = m.group(1)
        if tok in lit_hits:
            return chr(39) + lit_hits[tok][0] + chr(39)
        return m.group(0)
    body = re.sub(r"'([A-Za-z0-9]{4})'", _lit_repl, body)

    deploy_to = cfg['code'].get('deploy_to', 'UFS')
    # 20.10: папка триггеров могла получить номер (213-LIA) — писать
    # вырезку в неё, а не в голый deploy_to рядом.
    entry_name = deploy_to
    has_entry = False
    cat_p0 = os.path.join(cfg['target'], 'trigger', 'catalog.lml')
    if os.path.exists(cat_p0):
        cat0 = io.open(cat_p0, 'rb').read().decode('utf-8', errors='replace')
        m0 = re.search(r"^'?(\d{3}-" + re.escape(deploy_to) + r")'?:", cat0, re.M)
        if m0:
            entry_name = m0.group(1)
            has_entry = True
    out_name = cc.get('output', 'cut_code.j')
    out_p = os.path.join(cfg['target'], 'trigger', entry_name, out_name)
    if dry:
        print('(dry-run) вырезано: %d функций, внешних globals: %d, литералов: %d, непокрытых: %d' % (len(seen), len(ext_g), len(lit_hits), len(uncovered)))
    else:
        os.makedirs(os.path.dirname(out_p), exist_ok=True)
        # 20.09: purge старой вырезки ПО МАНИФЕСТУ — смена deploy_to
        # или output оставляла старый cut-файл навсегда.
        rel_new = os.path.relpath(out_p, cfg['target']).replace(os.sep, '/')
        m_old = deploy_manifest.load_manifest(cfgp)
        if m_old:
            old_c = m_old.get('cut_file')
            if old_c and old_c != rel_new:
                deploy_manifest.purge_section_files(cfgp, cfg['target'], 'cut_file', {rel_new})
        io.open(out_p, 'wb').write(body.encode('utf-8'))
        print('вырезано: %s (%d функций)' % (out_p, len(seen)))
        # отчёт
        rep = []
        rep.append('=== ОТЧЁТ ВЫРЕЗАНИЯ ===')
        rep.append('Точки входа: %s' % ', '.join(entries))
        rep.append('Вырезано функций: %d' % len(seen))
        rep.append('')
        rep.append('ВНЕШНИЕ GLOBALS (%d) — не в вырезанном куске, нужны вручную:' % len(ext_g))
        for g in ext_g:
            rep.append('  ' + gnames[g])
        rep.append('')
        rep.append('РО-ЛИТЕРАЛЫ В КОДЕ (перенесены маппингом):')
        for tok, (new, t) in sorted(lit_hits.items()):
            rep.append('  %s -> %s (%s)' % (tok, new, t))
        rep.append('')
        rep.append('НЕПОКРЫТЫЕ ЛИТЕРАЛЫ (нет в маппинге — проверить вручную):')
        for tok in sorted(uncovered):
            rep.append('  ' + tok)

        # авто-расширение deps: непокрытые литералы -> deps_result.json
        if cc.get('auto_expand') and uncovered:
            deps_p2 = os.path.join(here, 'deps_result.json')
            deps = json.load(io.open(deps_p2, 'rb')) if os.path.exists(deps_p2) else {'objects': {}, 'assets': []}
            added = []
            for tok in sorted(uncovered):
                # тип по наличию секции в таблицах источника
                typ = None
                for t2 in ('ability', 'buff', 'unit', 'item', 'doodad', 'destructable'):
                    tp2 = os.path.join(src, 'table', t2 + '.ini')
                    if os.path.exists(tp2) and re.search(r'^\[' + re.escape(tok) + r'\]', io.open(tp2, 'rb').read().decode('utf-8', errors='replace'), re.M):
                        typ = t2
                        break
                if not typ:
                    rep.append('  (auto-expand) %s: тип не определён — не добавлен' % tok)
                    continue
                lst = deps['objects'].setdefault(typ, [])
                if tok not in lst:
                    lst.append(tok)
                    added.append((typ, tok))
                al = deps.setdefault('auto_added', {}).setdefault(typ, [])
                if tok not in al:
                    al.append(tok)
            if added:
                io.open(deps_p2, 'wb').write(json.dumps(deps, indent=1, ensure_ascii=False).encode('utf-8'))
                rep.append('')
                rep.append('AUTO-EXPAND: добавлено в deps (%d) — перезапусти stage_deps:' % len(added))
                for typ, tok in sorted(added):
                    rep.append('  %s:%s' % (typ, tok))
                print('auto-expand: +%d в deps (перезапусти deps->mapping->tables->import->code_cut)' % len(added))
            else:
                print('auto-expand: нечего добавлять')
        rp = os.path.join(os.path.dirname(out_p), 'code_cut_report.txt')
        io.open(rp, 'wb').write(chr(10).join(rep).encode('utf-8'))
        print('отчёт:', rp)
        # автодописка catalog.lml (17.09)
        if cfg['code'].get('update_catalog', True):
            cat_p = os.path.join(cfg['target'], 'trigger', 'catalog.lml')
            if os.path.exists(cat_p):
                cat = io.open(cat_p, 'rb').read().decode('utf-8', errors='replace')
                if not has_entry:
                    nums = [int(m.group(1)) for m in re.finditer(r"^'?(\d{3})-", cat, re.M)]
                    nxt = max(nums) + 1 if nums else 1
                    line = "'%03d-%s': '%s'" % (nxt, deploy_to, deploy_to)
                    cat = cat.rstrip() + chr(10) + line + chr(10)
                    io.open(cat_p, 'wb').write(cat.encode('utf-8'))
                    print('catalog.lml: дописана папка %03d-%s' % (nxt, deploy_to))
                else:
                    print('catalog.lml: папка', entry_name, 'уже есть')

        # 20.09: своя секция манифеста (merge — чужие секции не трогаю)
        deploy_manifest.merge_section(cfgp, 'code_cut', {
            'cut_file': rel_new,
        })
        full = deploy_manifest.load_manifest(cfgp) or {}
        deploy_manifest.record_hashes(cfgp, full, cfg['target'])

if __name__ == '__main__':
    main()