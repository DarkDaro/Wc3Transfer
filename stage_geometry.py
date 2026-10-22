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
    """Высоты рельефа приёмника: {(tx, ty): height_float} по центрам тайлов."""
    d = io.open(path, 'rb').read()
    # 21.10 (аудит): мёртвый черновик разбора заголовка оставлен
    # закомментированным (ничего не удаляем), рабочий блок ниже.
    # off = 0
    assert d[0:4] == b'W3E!'
    # off = 4
    # ver = int.from_bytes(d[off:off+4], 'little'); off += 4
    # off += 4  # saves
    # off += 4  # editor
    # ng = int.from_bytes(d[off:off+4], 'little'); off += 4 + ng*4
    # nc = int.from_bytes(d[off:off+4], 'little'); off += 4 + nc*4 if False else off
    # аккуратно:
    off = 4 + 4 + 4 + 4
    ng = int.from_bytes(d[off:off+4], 'little'); off += 4
    off += ng * 4
    nc = int.from_bytes(d[off:off+4], 'little'); off += 4
    off += nc * 4
    Mx = int.from_bytes(d[off:off+4], 'little'); off += 4
    My = int.from_bytes(d[off:off+4], 'little'); off += 4
    off += 8  # center
    heights = {}
    for j in range(My):
        for i in range(Mx):
            o = off + (j*Mx + i)*7
            # gH: unsigned 14-бит, смещение 8192, масштаб /4
            # (проверено на UFS->LoW, ufs_shift_512.py)
            gh = int.from_bytes(d[o:o+2], 'little')
            heights[(i, j)] = (gh - 8192) / 4.0
    return heights, Mx, My

def terrain_z(heights, Mx, My, x, y):
    """Высота рельефа в мировой точке (x, y). Тайл 128 юнитов."""
    tx = int((x + 16384.0) / 128.0)
    ty = int((y + 12288.0) / 128.0)
    tx = max(0, min(Mx-1, tx))
    ty = max(0, min(My-1, ty))
    return heights.get((tx, ty), 0.0)

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
    heights, Mx, My = read_w3e_heights(os.path.join(tgt_map, 'war3map.w3e'))
    recount_z = geo.get('recount_z', True)
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
            for r in s_recs:
                nid = mp.get('doodad:' + r['id']) or mp.get('destructable:' + r['id']) or r['id']
                nx, ny = r['x'] + dx, r['y'] + dy
                if not (-16384 <= nx <= 16384) or not (-12288 <= ny <= 12288):
                    skipped += 1
                    continue
                max_num += 1
                nz = terrain_z(heights, Mx, My, nx, ny) if recount_z else r['z']
                raw = bytearray(r['raw'])
                struct.pack_into('<f', raw, 16, nz)  # z на +16
                new_recs.append({'raw': bytes(raw), 'new_id': nid, 'x': nx, 'y': ny, 'num': max_num})
                added += 1
            print('doo: было %d, добавится %d, пропущено (вне карты) %d' % (len(t_recs), added, skipped))
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
            rec[0:4] = nid.encode('ascii')
            struct.pack_into('<f', rec, 8, nx)
            struct.pack_into('<f', rec, 12, ny)
            if recount_z:
                struct.pack_into('<f', rec, 16, terrain_z(heights, Mx, My, nx, ny))
            new_units += rec
            added_u += 1
        struct.pack_into('<I', new_units, 12, t_cnt + added_u)
        print('units: было %d, добавится %d, пропущено %d' % (t_cnt, added_u, skipped_u))
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