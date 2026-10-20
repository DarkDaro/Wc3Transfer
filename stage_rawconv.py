# -*- coding: utf-8 -*-
# 21.09: конверт 0xXXXXXXXX -> 'RAWC' (base-256) в .j скриптах карты.
# 29.09: режим dec — десятичные литералы (1097691750 -> 'Amrf'):
# обфусцированные равкоды вида UnitRemoveAbility(u, 1097691750).
# Фильтр: конвертируются только числа, все 4 байта которых —
# печатаемые ASCII (0x21-0x7E). Обычные константы (2000000000 и т.п.)
# с непечатаемыми байтами пропускаются.
# 29.09: режим jhex — $-литералы JASS ($D000F, $A, $96). Печатаемые 4
# байта -> 'RAWC' ($416D7266 -> 'Amrf'), иначе -> десятичное ($D000F ->
# 851983, $A -> 10, $96 -> 150). Семантика не меняется никогда.
# 29.09 (вечер): снят минимум 5 цифр — конвертируются ВСЕ $-литералы,
# включая односимвольные $A/$B (по запросу пользователя).
# 29.09 (поздно): обратная конвертация (обфускация): 'Amrf' -> 0x/dec/$.
# Режим --reverse + --to hex|dec|jhex.
# Разовая операция режима Обслуживания. Вход: файл ИЛИ папка (тогда
# авто-поиск общего скрипта карты: war3map.j в корне, trigger/code.j).
# Алгоритм — скрипт пользователя (ASCII.py, 19.09), граница литерала
# добавлена: (?<![0-9a-fA-F])...(?![0-9a-fA-F]) — не режем длинные числа.
import io
import os
import re
import shutil
import time

HEX_PATTERN = re.compile(rb'(?<![0-9a-fA-F])0x([0-9a-fA-F]{8})(?![0-9a-fA-F])')
# 29.09: десятичные 8-10-значные; границы отсекают 0x-литералы,
# идентификаторы, числа с точкой/экспонентой; '-' в lookbehind —
# не трогаем отрицательные (29.09 поздно: -1097691750 -> -'Amrf')
DEC_PATTERN = re.compile(rb'(?<![0-9A-Za-z_.-])\d{8,10}(?![0-9A-Za-z_.])')
# 29.09: $-hex JASS, все длины (1+ цифр) — $A, $96, $D000F, $540BE3FF
JHEX_PATTERN = re.compile(rb'(?<![0-9A-Za-z_$.])\$([0-9a-fA-F]+)(?![0-9A-Za-z_])')
# 29.09: rawcode в одинарных кавычках — 4 печатаемых ASCII символа
RAWC_PATTERN = re.compile(rb"'([A-Za-z0-9]{4})'")


def _code_segments(s):
    """29.09 (поздно): разбивка байтов на [(сегмент, is_code)].
    Строки "..." (с учётом \\"), комментарии // и /* */ — НЕ код:
    замены в них не делаются. Иначе ломаются тексты игроку
    ('Amrf' в "..." -> 0x...) и комментарии."""
    segs = []
    i = 0
    n = len(s)
    code_start = 0
    while i < n:
        if s[i:i+1] == b'"':
            j = i + 1
            while j < n:
                if s[j:j+1] == b'\\':
                    j += 2
                    continue
                if s[j:j+1] == b'"':
                    break
                j += 1
            j = min(j + 1, n)
            segs.append((s[code_start:i], True))
            segs.append((s[i:j], False))
            code_start = j
            i = j
        elif s[i:i+2] == b'//':
            j = s.find(b'\n', i)
            if j == -1:
                j = n
            segs.append((s[code_start:i], True))
            segs.append((s[i:j], False))
            code_start = j
            i = j
        elif s[i:i+2] == b'/*':
            j = s.find(b'*/', i)
            j = n if j == -1 else j + 2
            segs.append((s[code_start:i], True))
            segs.append((s[i:j], False))
            code_start = j
            i = j
        else:
            i += 1
    segs.append((s[code_start:], True))
    return segs


def _patterns(mode):
    """29.09: режим -> список (имя, regex). hex | dec | jhex | both | all.
    29.09 (поздно): reverse-режимы: rawc_hex | rawc_dec | rawc_jhex."""
    if mode == 'rawc_hex':
        return [('rawc_hex', RAWC_PATTERN)]
    if mode == 'rawc_dec':
        return [('rawc_dec', RAWC_PATTERN)]
    if mode == 'rawc_jhex':
        return [('rawc_jhex', RAWC_PATTERN)]
    if mode == 'hex':
        return [('hex', HEX_PATTERN)]
    if mode == 'dec':
        return [('dec', DEC_PATTERN)]
    if mode == 'jhex':
        return [('jhex', JHEX_PATTERN)]
    if mode == 'all':
        return [('hex', HEX_PATTERN), ('dec', DEC_PATTERN), ('jhex', JHEX_PATTERN)]
    return [('hex', HEX_PATTERN), ('dec', DEC_PATTERN)]


def decimal2ascii(number):
    # число -> little-endian байты (младший байт первый), читаем как
    # big-endian rawcode 'A000' (как в исходном скрипте пользователя)
    rems = []
    while number >= 256:
        number, rem = divmod(number, 256)
        rems.append(rem)
    rems.append(number)
    return bytes(reversed(rems))


def dec2raw(number):
    """29.09: десятичное число -> 4-байтовый rawcode, если все байты
    печатаемые ASCII (0x21-0x7E). Иначе None (обычная константа, не трогаем)."""
    b = decimal2ascii(number)
    if len(b) != 4:
        return None
    for c in b:
        if c < 0x21 or c > 0x7E:
            return None
    return b


def num2raw(number):
    """29.09: число -> 4-байтовый rawcode (с паддингом нулями слева),
    если все байты печатаемые ASCII. Иначе None."""
    b = decimal2ascii(number)
    if len(b) > 4:
        return None
    b = b'\x00' * (4 - len(b)) + b
    for c in b:
        if c < 0x21 or c > 0x7E:
            return None
    return b


def find_scripts(path):
    """Вход: файл или папка. Папка -> кандидаты общего скрипта карты."""
    if os.path.isfile(path):
        return [path]
    if not os.path.isdir(path):
        return []
    cands = []
    # 21.09: lni-структура — war3map.j живёт в map/
    for rel in (os.path.join('map', 'war3map.j'), 'war3map.j',
                os.path.join('trigger', 'code.j')):
        p = os.path.join(path, rel)
        if os.path.isfile(p):
            cands.append(p)
    if not cands:
        # папка уже trigger/ или другая — ищем скрипт прямо в ней
        for name in ('war3map.j', 'code.j'):
            p = os.path.join(path, name)
            if os.path.isfile(p):
                cands.append(p)
    return cands


def scan(path, mode='both'):
    """Скан: [(файл, число литералов)]. Без записи."""
    out = []
    for p in find_scripts(path):
        s = io.open(p, 'rb').read()
        n = 0
        for _name, pat in _patterns(mode):
            if _name == 'dec':
                # dec: считаем только те, что пройдут ASCII-фильтр
                n += sum(1 for m in pat.finditer(s) if dec2raw(int(m.group(0))))
            else:
                n += len(pat.findall(s))
        out.append((p, n))
    return out


def convert(path, backup_dir, mode='both'):
    """Конверт одного файла: бэкап -> замена -> лог замен рядом с файлом.
    Возвращает (число замен, путь лога, путь бэкапа)."""
    s = io.open(path, 'rb').read()
    codes = {}  # ключ с префиксом (b'0x..' / b'$..' / dec-строка) -> замена

    def rep_hex(m):
        h = m.group(1)
        if h not in codes:
            codes[h] = b"'" + decimal2ascii(int(h, 16)) + b"'"
        return codes[h]

    def rep_dec(m):
        d = m.group(0)
        raw = dec2raw(int(d))
        if raw is None:
            return d  # не rawcode — не трогаем
        if d not in codes:
            codes[d] = b"'" + raw + b"'"
        return codes[d]

    def rep_jhex(m):
        h = m.group(1)
        key = b'$' + h
        if key not in codes:
            n = int(h, 16)
            raw = num2raw(n)
            # печатаемые 4 байта -> 'RAWC'; иначе -> десятичное (то же число)
            codes[key] = b"'" + raw + b"'" if raw else str(n).encode('ascii')
        return codes[key]

    def rep_rawc_hex(m):
        raw = m.group(1)
        key = b"'" + raw + b"'"
        if key not in codes:
            codes[key] = raw2hex(raw)
        return codes[key]

    def rep_rawc_dec(m):
        raw = m.group(1)
        key = b"'" + raw + b"'"
        if key not in codes:
            codes[key] = raw2dec(raw)
        return codes[key]

    def rep_rawc_jhex(m):
        raw = m.group(1)
        key = b"'" + raw + b"'"
        if key not in codes:
            codes[key] = raw2jhex(raw)
        return codes[key]

    # 29.09 (поздно): замены только в коде — строки и комментарии не трогаем
    parts = []
    for seg, is_code in _code_segments(s):
        if not is_code:
            parts.append(seg)
            continue
        s2 = seg
        for name, pat in _patterns(mode):
            if name == 'hex':
                rep = rep_hex
            elif name == 'dec':
                rep = rep_dec
            elif name == 'jhex':
                rep = rep_jhex
            elif name == 'rawc_hex':
                rep = rep_rawc_hex
            elif name == 'rawc_dec':
                rep = rep_rawc_dec
            elif name == 'rawc_jhex':
                rep = rep_rawc_jhex
            else:
                rep = lambda m: m.group(0)
            s2 = pat.sub(rep, s2)
        parts.append(s2)
    s2 = b''.join(parts)
    if not codes:
        return 0, None, None
    stamp = time.strftime('%Y%m%d-%H%M%S')
    bd = os.path.join(backup_dir, stamp)
    os.makedirs(bd, exist_ok=True)
    bdst = os.path.join(bd, os.path.basename(path))
    shutil.copy2(path, bdst)
    io.open(path, 'wb').write(s2)
    # 21.09/29.09: отдельный лог замен (формат ASCII log пользователя:
    # '0x41303030 -- 'A000'' и '1097691750 -- 'Amrf''), рядом с файлом
    logp = os.path.splitext(path)[0] + '.ascii-log.txt'
    with io.open(logp, 'wb') as f:
        for h in sorted(codes):
            a = codes[h][1:-1].decode('latin-1')
            key = h.decode('latin-1')
            rep = codes[h]
            if rep.startswith(b"'"):
                f.write(("%s -- '%s'" % (key, a) + '\n').encode('utf-8'))
            else:
                # dec-режим: замена тоже 'RAWC'; jhex непечатаемые: число -> число
                f.write(("%s -- %s" % (key, rep.decode('ascii')) + '\n').encode('utf-8'))
    return len(codes), logp, bdst


def run(path, backup_dir, apply=False, mode='both'):
    """Скан или конверт всех найденных скриптов. Возвращает строки отчёта."""
    lines = []
    found = scan(path, mode)
    if not found:
        return ['скрипт карты не найден (war3map.j / trigger/code.j): ' + str(path)]
    for p, n in found:
        rel = p
        if not apply:
            lines.append('СКАНИРОВАНИЕ %s [%s]: литералов %d' % (rel, mode, n))
            continue
        if not n:
            lines.append('ПРОПУСК %s [%s]: литералов нет' % (rel, mode))
            continue
        n_done, logp, bdst = convert(p, backup_dir, mode)
        lines.append('КОНВЕРТ %s: замен %d' % (rel, n_done))
        lines.append('  бэкап: %s' % bdst)
        lines.append('  лог замен: %s' % logp)
    return lines


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print('use: stage_rawconv.py <файл или папка карты> [--apply] [--hex|--dec|--jhex|--all]')
        print('      [--reverse] [--to hex|dec|jhex]')
        print('  --reverse: обратная конвертация (обфускация) RAWC -> hex/dec/$')
        print('  --to: целевая форма (hex=0x..., dec=число, jhex=$...); по умолчанию hex')
        sys.exit(2)
    tgt = sys.argv[1]
    do = '--apply' in sys.argv
    reverse = '--reverse' in sys.argv
    to_form = 'hex'
    for i, arg in enumerate(sys.argv):
        if arg == '--to' and i + 1 < len(sys.argv):
            to_form = sys.argv[i + 1]
    if to_form not in ('hex', 'dec', 'jhex'):
        print('ошибка: --to должен быть hex|dec|jhex')
        sys.exit(2)
    if reverse:
        mode = 'rawc_' + to_form
    elif '--all' in sys.argv:
        mode = 'all'
    elif '--jhex' in sys.argv:
        mode = 'jhex'
    elif '--hex' in sys.argv:
        mode = 'hex'
    elif '--dec' in sys.argv:
        mode = 'dec'
    else:
        mode = 'both'
    here = os.path.dirname(os.path.abspath(__file__))
    for l in run(tgt, os.path.join(here, 'transfer_backup', 'rawconv'), apply=do, mode=mode):
        print(l)
def raw2num(raw):
    """29.09: 4-байтовый rawcode -> число (big-endian чтение)."""
    n = 0
    for c in raw:
        n = n * 256 + c
    return n


def raw2hex(raw):
    """rawcode -> 0xXXXXXXXX."""
    return b'0x' + raw.hex().encode('ascii')


def raw2dec(raw):
    """rawcode -> десятичное число."""
    return str(raw2num(raw)).encode('ascii')


def raw2jhex(raw):
    """rawcode -> $XXXXXXXX."""
    return b'$' + raw.hex().encode('ascii')
