# 17.09: Этап geometry — вставка декора/юнитов в doo+units приёмника
# Логика из ufs_insert_doo_units.py, параметризованная через конфиг.
# Вход: cfg['geometry'] = {enabled, offset: [dx, dy] или null, recount_z,
#       22.10: types = {decor: True, units: True} — что переносить;
#       отсутствующая секция = переносятся оба (старое поведение)}
# offset null = авто-подбор по воде (как в UFS->LoW) — требует подтверждения.
# Маппинг: transfer_mapping.json
# Dry-run: только отчёт, файлы не пишутся.
import io, os, sys, json, struct, re

def parse_doo_records(d):
    cnt = int.from_bytes(d[12:16], 'little')
    off = 16
    recs = []
    for i in range(cnt):
        start = off
        did = d[off:off+4].decode('ascii', errors='replace')
        x, y, z = struct.unpack('<3f', d[off+8:off+20])
        droplist = int.from_bytes(d[off+38:off+42], 'little', signed=True)
        count = int.from_bytes(d[off+42:off+46], 'little', signed=True)
        off += 46
        if droplist > 0 and count > 0:
            off += 8 * count
        num = int.from_bytes(d[off:off+4], 'little', signed=True)
        off += 4
        recs.append({'raw': d[start:off], 'id': did, 'x': x, 'y': y, 'z': z, 'num': num})
    tail = len(d) - off
    assert tail in (0, 8), 'doo хвост %d байт' % tail
    return recs

def write_doo(recs, out_path):
    out = io.BytesIO()
    out.write(b'W3do')
    out.write(struct.pack('<i', 8))
    out.write(struct.pack('<i', 11))
    out.write(struct.pack('<I', len(recs)))
    for r in recs:
        raw = bytearray(r['raw'])
        if 'new_id' in r:
            raw[0:4] = r['new_id'].encode('ascii')
            struct.pack_into('<f', raw, 8, r['x'])
            struct.pack_into('<f', raw, 12, r['y'])
            struct.pack_into('<i', raw, len(raw)-4, r['num'])
        out.write(raw)
    io.open(out_path, 'wb').write(out.getvalue())

def read_w3e_heights(path):
    """Высоты рельефа приёмника: {(tx, ty): height_float} по центрам тайлов.
    22.10: разбор теперь через parse_w3e (перебор схем с проверкой длин).
    Старая схема (off=16, «saves+editor») на w3e ver 11 молча давала
    Mx=My=0 и пустой словарь высот: recount_z ставил всем вставкам z=0.
    Теперь либо честные высоты, либо ValueError (молчаливый мусор
    невозможен)."""
    m = parse_w3e(path)
    heights = {}
    tiles = m['tiles']
    for j in range(m['My']):
        for i in range(m['Mx']):
            o = (j*m['Mx'] + i)*7
            # gH: unsigned 14-бит, смещение 8192, масштаб /4
            # (проверено на UFS->LoW, ufs_shift_512.py)
            gh = int.from_bytes(tiles[o:o+2], 'little')
            heights[(i, j)] = (gh - 8192) / 4.0
    return heights, m['Mx'], m['My']

def terrain_z(heights, Mx, My, x, y):
    """Высота рельефа в мировой точке (x, y). Тайл 128 юнитов."""
    tx = int((x + 16384.0) / 128.0)
    ty = int((y + 12288.0) / 128.0)
    tx = max(0, min(Mx-1, tx))
    ty = max(0, min(My-1, ty))
    return heights.get((tx, ty), 0.0)

# 22.10: ===== ландшафт (war3map.w3e) — вставка со смещением =====
# Формат (классический): 'W3E!' + version + NG + NG*4 (groundTilesets)
# + NC + NC*4 (cliffTilesets) + Mx + My + центр (2 float) + Mx*My*7 клеток.
# НАБЛЮДЕНИЕ на живой паре карт (ver 11): заголовок там нестандартный
# (перед списком два целых, длины зон не сходятся с таблицей длин), поэтому
# разбор делается перебором схем с проверкой Mx/My и длины клеток;
# ни одна схема не подошла = ландшафт пропущен с диагностикой, файл
# приёмника не трогается. Клетки: 7 байт (высота — первые 2 байта).
# Вставка: в области перекрытия запись приёмника заменяется донорской;
# за пределами донора клетки приёмника остаются. При совпадающих
# тайлсетах байты копируются как есть. Повторы безвредны: замена
# идемпотентна (те же байты).

def _tiles_start_ok(d, tiles_start, Mx, My):
    return (tiles_start >= 32 and 32 <= Mx <= 1024 and 32 <= My <= 1024
            and len(d) - tiles_start == Mx * My * 7)

def parse_w3e(path):
    """Разбор заголовка с перебором схем. ValueError = непонятно,
    ландшафт не переносится (диагностика в сообщении)."""
    d = io.open(path, 'rb').read()
    if d[0:4] != b'W3E!':
        raise ValueError('w3e magic: %s' % d[0:4])
    ver = int.from_bytes(d[4:8], 'little')
    # схема A: ver, NG, NG*4, NC, NC*4, Mx, My, центр, клетки
    # схема B: ver, A, B, NG, NG*4, NC, NC*4, Mx, My, центр, клетки
    for skip in (0, 8):
        off = 8 + skip
        ng = int.from_bytes(d[off:off+4], 'little'); off += 4
        if not (1 <= ng <= 64):
            continue
        off += ng * 4
        nc = int.from_bytes(d[off:off+4], 'little'); off += 4
        if not (1 <= nc <= 64):
            continue
        off += nc * 4
        Mx = int.from_bytes(d[off:off+4], 'little'); off += 4
        My = int.from_bytes(d[off:off+4], 'little'); off += 4
        tiles_start = off + 8
        if not _tiles_start_ok(d, tiles_start, Mx, My):
            continue
        return {'ver': ver, 'head': d[:tiles_start-8],
                'cx': d[tiles_start-8:tiles_start-4],
                'cy': d[tiles_start-4:tiles_start],
                'Mx': Mx, 'My': My, 'tiles': d[tiles_start:],
                'gt': d[12+skip:12+skip+ng*4],
                'ct': d[20+skip+ng*4:20+skip+ng*4+nc*4]}
    # диагностика честная: первые целые после magic для журнала
    ints_after = [int.from_bytes(d[k:k+4], 'little') for k in (8, 12, 16)]
    raise ValueError('w3e v%d: заголовок не распознан ни одной схемой '
                     '(целые после magic: %s; длина файла %d байт)'
                     % (ver, ints_after, len(d)))

def shifted_tiles(s, t, tx, ty):
    """Клетки приёмника в перекрытии заменяются клетками донора.
    (i, j) приёмника <- (i - tx, j - ty) донора."""
    out = bytearray(t['tiles'])
    for j in range(t['My']):
        dj = j - ty
        if not (0 <= dj < s['My']):
            continue
        for i in range(t['Mx']):
            di = i - tx
            if not (0 <= di < s['Mx']):
                continue
            o = (j * t['Mx'] + i) * 7
            so = (dj * s['Mx'] + di) * 7
            out[o:o+7] = s['tiles'][so:so+7]
    return bytes(out)

def w3e_heights_dict(m):
    """Высоты из разобранного w3e: {(i, j): float} — формат read_w3e_heights."""
    heights = {}
    for j in range(m['My']):
        for i in range(m['Mx']):
            o = (j * m['Mx'] + i) * 7
            gh = int.from_bytes(m['tiles'][o:o+2], 'little')
            heights[(i, j)] = (gh - 8192) / 4.0
    return heights

def place_w3e(src_map, tgt_map, dx, dy, dry, cfg_w3e):
    """Вставка ландшафтной сетки со смещением. Возвращает словарь высот
    merged-рельефа (донор поверх приёмника в зоне перекрытия) или None,
    если ландшафт не менялся или его нельзя перенести."""
    sw = os.path.join(src_map, 'war3map.w3e')
    tw = os.path.join(tgt_map, 'war3map.w3e')
    if not (os.path.exists(sw) and os.path.exists(tw)):
        print('geometry: нет war3map.w3e (%s) — ландшафт пропущен'
              % ('источник' if not os.path.exists(sw) else 'приёмник'))
        return None
    try:
        s = parse_w3e(sw)
    except ValueError as ex:
        print('geometry: ландшафт пропущен (донор) — %s' % ex)
        return None
    try:
        t = parse_w3e(tw)
    except ValueError as ex:
        print('geometry: ландшафт пропущен (приёмник) — %s' % ex)
        return None
    if s['gt'] != t['gt'] or s['ct'] != t['ct']:
        if cfg_w3e.get('force'):
            print('geometry ВНИМАНИЕ: тайлсеты донора и приёмника различаются, '
                  'перенос ландшафта принудительный (force) — текстуры могут '
                  'исказиться: индексы клеток ссылаются на другие наборы')
        else:
            print('geometry: тайлсеты (ground/cliff) донора и приёмника РАЗЛИЧАЮТСЯ, '
                  'ландшафт не переносится (принудительно: geometry.w3e.force = true)')
            return None
    tx, ty = round(dx / 128.0), round(dy / 128.0)
    if abs(dx - tx * 128) > 1 or abs(dy - ty * 128) > 1:
        print('geometry: offset не кратен 128 (тайлу) — сдвиг выровнен на сетку')
    merged = shifted_tiles(s, t, tx, ty)
    if merged == t['tiles']:
        print('landscape: перекрытие совпадает или пусто — w3e без изменений')
        return None
    repl = sum(1 for k in range(0, len(merged), 7)
               if merged[k:k+7] != t['tiles'][k:k+7])
    print('landscape: заменено клеток %d из %d (сдвиг клеток tx=%d ty=%d)'
          % (repl, t['Mx'] * t['My'], tx, ty))
    merged_h = w3e_heights_dict({'Mx': t['Mx'], 'My': t['My'], 'tiles': merged})
    if dry:
        print('(dry-run: w3e не записан)')
    else:
        out = t['head'] + t['cx'] + t['cy'] + merged
        io.open(tw, 'wb').write(out)
        print('w3e записан, размер', len(out), 'байт (было', len(t['head']) + 8 + len(t['tiles']), ')')
    return merged_h

def main():
    cfgp = sys.argv[1]
    dry = '--dry-run' in sys.argv
    cfg = json.load(io.open(cfgp, 'rb'))
    here = os.path.dirname(os.path.abspath(cfgp))
    src = cfg['source']
    tgt = cfg['target']
    geo = cfg['geometry']
    if not geo.get('enabled'):
        print('geometry выключена в конфиге')
        return
    offset = geo.get('offset')
    if not offset:
        print('geometry.offset не задан (авто-подбор не реализован в v1 — задай [dx, dy] в конфиге)')
        return
    dx, dy = offset

    mp = json.load(io.open(os.path.join(here, cfg['mapping']['pkl'].replace('.pkl', '.json')), 'rb'))
    def map_id(kind, did):
        return mp.get(kind + ':' + did) or did

    src_map = os.path.join(src, 'map')
    tgt_map = os.path.join(tgt, 'map')

    # рельеф приёмника для z
    # 22.10: если w3e не разобрать (ver 11 нестандартный), recount_z
    # отключается: z берётся из донора, а не ставится 0 молча
    try:
        heights, Mx, My = read_w3e_heights(os.path.join(tgt_map, 'war3map.w3e'))
    except ValueError as ex:
        print('geometry: высоты рельефа недоступны (%s) — recount_z выключен, '
              'z вставок берётся из донора' % ex)
        heights, Mx, My = {}, 1, 1
        recount_z_dis = True
    else:
        recount_z_dis = False
    recount_z = geo.get('recount_z', True) and not recount_z_dis
    # 22.10: ландшафт (w3e) — вставка со смещением. По умолчанию ВЫКЛ,
    # включается в GUI/конфиге (geometry.w3e.enabled). Если клетки заменены,
    # пересчёт z у декора/юнитов идёт уже по merged-рельефу (высоты донора
    # в зоне переноса).
    cfg_w3e = geo.get('w3e', {})
    if cfg_w3e.get('enabled'):
        mh = place_w3e(src_map, tgt_map, dx, dy, dry, cfg_w3e)
        if mh:
            heights = mh
    # 22.10: разделение декора и юнитов. Секция отсутствует/частичная = True:
    # старые конфиги работают по-прежнему (переносятся оба типа)
    types = geo.get('types', {})
    do_decor = bool(types.get('decor', True))
    do_units = bool(types.get('units', True))
    if not do_decor and not do_units:
        print('geometry: обе категории выключены (geometry.types) — этап пропущен')
        return

    # ===== doo (декорации, war3map.doo) =====
    if do_decor:
        sd = os.path.join(src_map, 'war3map.doo')
        td = os.path.join(tgt_map, 'war3map.doo')
        if not (os.path.exists(sd) and os.path.exists(td)):
            print('geometry: нет war3map.doo (%s) — декор пропущен' % ('источник' if not os.path.exists(sd) else 'приёмник'))
        else:
            s_doo = io.open(sd, 'rb').read()
            t_doo = io.open(td, 'rb').read()
            s_recs = parse_doo_records(s_doo)
            t_recs = parse_doo_records(t_doo)
            # 20.10: пустой doo приёмника больше не роняет max()
            max_num = max([r['num'] for r in t_recs] or [0])
            new_recs = list(t_recs)
            added = skipped = 0
            # 22.10 (защита): дедупликация вставок — не вставлять запись,
            # если в приёмнике УЖЕ есть такая же (id, координаты) с точностью
            # 0.05 юнита. Повторный прогон с тем же offset больше не задваивает
            # декор; state для этого не нужен (проверка идёт по самому doo)
            t_keys = set((r['id'], round(r['x'], 1), round(r['y'], 1))
                         for r in t_recs)
            dup = 0
            for r in s_recs:
                nid = mp.get('doodad:' + r['id']) or mp.get('destructable:' + r['id']) or r['id']
                nx, ny = r['x'] + dx, r['y'] + dy
                if not (-16384 <= nx <= 16384) or not (-12288 <= ny <= 12288):
                    skipped += 1
                    continue
                key = (nid, round(nx, 1), round(ny, 1))
                if key in t_keys:
                    dup += 1
                    continue
                max_num += 1
                nz = terrain_z(heights, Mx, My, nx, ny) if recount_z else r['z']
                raw = bytearray(r['raw'])
                struct.pack_into('<f', raw, 16, nz)  # z на +16
                new_recs.append({'raw': bytes(raw), 'new_id': nid, 'x': nx, 'y': ny, 'num': max_num})
                t_keys.add(key)   # две одинаковые записи в доноре = одна вставка
                added += 1
            print('doo: было %d, добавится %d, пропущено (вне карты) %d, дублей %d'
                  % (len(t_recs), added, skipped, dup)
                  + (' (повторный прогон — вставки уже стоят)' if dup else ''))
            if dry:
                print('(dry-run: doo не записан)')
            else:
                write_doo(new_recs, os.path.join(tgt_map, 'war3map.doo'))

    # ===== units (юниты, war3mapUnits.doo) =====
    if do_units:
        su = os.path.join(src_map, 'war3mapUnits.doo')
        tu = os.path.join(tgt_map, 'war3mapUnits.doo')
        if not (os.path.exists(su) and os.path.exists(tu)):
            print('geometry: нет war3mapUnits.doo — units пропущены')
            return
        s_u = io.open(su, 'rb').read()
        t_u = io.open(tu, 'rb').read()
        if len(t_u) < 16 or len(s_u) < 16:
            print('geometry: war3mapUnits.doo короче заголовка — units пропущены')
            return
        t_cnt = int.from_bytes(t_u[12:16], 'little')
        s_cnt = int.from_bytes(s_u[12:16], 'little')
        new_units = bytearray(t_u)
        added_u = skipped_u = 0
        # 22.10 (защита): дедупликация как в декоре — если в приёмнике
        # уже стоит запись с теми же (id, x, y), вставка пропускается.
        # Повторный прогон не задваивает юнитов
        u_keys = set()
        for i in range(t_cnt):
            o = 16 + i * 111
            ux, uy = struct.unpack('<2f', t_u[o+8:o+16])
            u_keys.add((t_u[o:o+4].decode('ascii', errors='replace'),
                        round(ux, 1), round(uy, 1)))
        dup_u = 0
        for i in range(s_cnt):
            off = 16 + i * 111
            rec = bytearray(s_u[off:off+111])
            uid = rec[0:4].decode('ascii', errors='replace')
            if uid == 'sloc':
                continue
            x, y, z = struct.unpack('<3f', bytes(rec[8:20]))
            nx, ny = x + dx, y + dy
            if not (-16384 <= nx <= 16384) or not (-12288 <= ny <= 12288):
                skipped_u += 1
                continue
            nid = mp.get('unit:' + uid) or uid
            key = (nid, round(nx, 1), round(ny, 1))
            if key in u_keys:
                dup_u += 1
                continue
            rec[0:4] = nid.encode('ascii')
            struct.pack_into('<f', rec, 8, nx)
            struct.pack_into('<f', rec, 12, ny)
            if recount_z:
                struct.pack_into('<f', rec, 16, terrain_z(heights, Mx, My, nx, ny))
            new_units += rec
            u_keys.add(key)   # повтор в доноре = одна вставка
            added_u += 1
        struct.pack_into('<I', new_units, 12, t_cnt + added_u)
        print('units: было %d, добавится %d, пропущено %d, дублей %d'
              % (t_cnt, added_u, skipped_u, dup_u)
              + (' (повторный прогон — вставки уже стоят)' if dup_u else ''))
        if dry:
            print('(dry-run: units не записан)')
        else:
            io.open(os.path.join(tgt_map, 'war3mapUnits.doo'), 'wb').write(bytes(new_units))
            # проверка
            chk = io.open(os.path.join(tgt_map, 'war3mapUnits.doo'), 'rb').read()
            exp = 16 + (t_cnt + added_u) * 111
            assert len(chk) == exp, 'units размер %d != %d' % (len(chk), exp)
            print('units записан, размер ок:', exp)

if __name__ == '__main__':
    main()