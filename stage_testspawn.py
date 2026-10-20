# 17.09: Этап testspawn — генерация TestSpawn .j для перенесённых героев
# Логика ufs_testspawn_v2.py, параметризованная:
#   cfg['testspawn'] = {enabled, heroes: [ID источника] (пусто = все unit из deps),
#                       rect: 'gg_rct_team_1_spawn', items: true}
# Выход: <target>/trigger/<deploy_to>/90-TestSpawn.j
import io, os, sys, json, re

def main():
    cfgp = sys.argv[1]
    dry = '--dry-run' in sys.argv
    cfg = json.load(io.open(cfgp, 'rb'))
    here = os.path.dirname(os.path.abspath(cfgp))
    ts = cfg.get('testspawn', {})
    if not ts.get('enabled'):
        print('testspawn выключен в конфиге')
        return
    src = cfg['source']
    tgt = cfg['target']
    mp = json.load(io.open(os.path.join(here, cfg['mapping']['pkl'].replace('.pkl', '.json')), 'rb'))

    # герои: из конфига или все unit из deps
    heroes = ts.get('heroes', [])
    if not heroes:
        deps_p = os.path.join(here, 'deps_result.json')
        if os.path.exists(deps_p):
            deps = json.load(io.open(deps_p, 'rb'))
            heroes = deps['objects'].get('unit', [])
    if not heroes:
        print('героев для TestSpawn нет (cfg.testspawn.heroes или deps)')
        return

    # имена героев из unit.ini источника
    s = io.open(os.path.join(src, 'table', 'unit.ini'), 'rb').read().decode('utf-8', errors='replace')
    names = {}
    cur = None
    for l in s.splitlines():
        m = re.match(r'^\[([^\]]+)\]', l)
        if m:
            cur = m.group(1)
        elif cur and re.match(r'^Name\s*=', l):
            names[cur] = re.sub(r'\|c[0-9A-Fa-f]{8}|\|r', '', l.split('=', 1)[1]).strip()

    hmap = []
    for old in heroes:
        new = mp.get('unit:' + old)
        if new:
            hmap.append((old, new, names.get(old, old)))
        else:
            print('  герой %s не в маппинге — пропуск' % old)

    # предметы (кастомные из deps, кроме prebuilt)
    items = []
    deps_p = os.path.join(here, 'deps_result.json')
    if ts.get('items', True) and os.path.exists(deps_p):
        deps = json.load(io.open(deps_p, 'rb'))
        for old in deps['objects'].get('item', []):
            new = mp.get('item:' + old)
            if new:
                items.append(new)

    # 22.09: точка спавна. 'center' или пусто = центр карты (0, 0) — видно точно.
    rect = (ts.get('rect') or 'center').strip()
    at_center = rect.lower() in ('center', '0,0', '')
    lines = []
    lines.append('// 17.09: TestSpawn (утилита переноса) — %d героев + %d предметов' % (len(hmap), len(items)))
    lines.append('// Спавн: ' + ('центр карты (0, 0)' if at_center else 'центр региона %s' % rect))
    lines.append('// Вызов: call ExecuteFunc("TestSpawn__I")')
    lines.append('')
    if items:
        lines.append('function TestSpawn__ItemId takes integer i returns integer')
        for n, new in enumerate(items):
            kw = 'if' if n == 0 else 'elseif'
            lines.append('    %s i == %d then' % (kw, n))
            lines.append("        return '%s'" % new)
        lines.append('    endif')
        lines.append('    return 0')
        lines.append('endfunction')
        lines.append('')
    lines.append('function TestSpawn__I takes nothing returns nothing')
    if at_center:
        lines.append('    local real cx = 0.0')
        lines.append('    local real cy = 0.0')
    else:
        lines.append('    local real cx = GetRectCenterX(%s)' % rect)
        lines.append('    local real cy = GetRectCenterY(%s)' % rect)
    lines.append('    local integer i = 0')
    lines.append('    local real ang = 0.0')
    lines.append('    local item it')
    for n, (old, new, name) in enumerate(hmap):
        # 22.09: сетка 20 в ряд (шаг 150), ряды вниз (шаг 150) — 331 герой
        # в один ряд улетал за границы карты (x до 48750), спавн молчал.
        x = -1500.0 + (n % 20) * 150.0
        y = 300.0 + (n // 20) * 150.0
        lines.append("    call CreateUnit(Player(0), '%s', cx + %.1f, cy + %.1f, 270.0) // %s %s" % (new, x, y, old, name))
    if items:
        lines.append('    // предметы: по кругу радиуса 500')
        lines.append('    loop')
        lines.append('        exitwhen i >= %d' % len(items))
        lines.append('        set it = CreateItem(TestSpawn__ItemId(i), cx + 500.0 * Cos(ang * bj_DEGTORAD), cy + 500.0 * Sin(ang * bj_DEGTORAD))')
        lines.append('        set it = null')
        lines.append('        set i = i + 1')
        lines.append('        set ang = ang + %.4f' % (360.0 / len(items)))
        lines.append('    endloop')
    lines.append('endfunction')

    body = chr(10).join(lines) + chr(10)
    deploy_to = cfg['code'].get('deploy_to', 'UFS')
    out = os.path.join(tgt, 'trigger', deploy_to, '90-TestSpawn.j')
    if dry:
        print('(dry-run) TestSpawn: %d героев, %d предметов -> %s' % (len(hmap), len(items), out))
    else:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        io.open(out, 'wb').write(body.encode('utf-8'))
        print('TestSpawn записан: %s (%d героев, %d предметов)' % (out, len(hmap), len(items)))

if __name__ == '__main__':
    main()