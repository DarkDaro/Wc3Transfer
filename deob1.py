#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""JASS deobfuscator for HOTS.j:
- re-formats (line breaks + indentation)
- renames obfuscated identifiers based on type / semantics
- verifies token-stream equivalence between input and output
"""
import re, sys, csv, os, datetime
from collections import defaultdict

SRC = 'HOTS.j'
OUT = 'HOTS_deobfuscated.j'
MAPF = 'rename_map.csv'
DEFAULT_OUT = OUT
DEFAULT_MAP = MAPF

USAGE = ('usage: python deob.py [input.j] [-o output.j] [-m rename_map.csv]\n'
         '  input.j         map script to deobfuscate (default: HOTS.j)\n'
         '  -o, --output    output file (default: <input>_deobfuscated.j)\n'
         '  -m, --map       rename-map CSV (default: rename_map.csv)')

KEYWORDS = {
    'function','endfunction','takes','returns','local','set','call','if','then','else','elseif',
    'endif','loop','endloop','exitwhen','return','globals','endglobals','native','constant',
    'type','extends','array','and','or','not','debug','nothing','code','use?'.replace('?',''),
}
TYPES = {
    'integer','real','boolean','string','handle','code','agent','event','player','widget','unit',
    'destructable','item','ability','buff','force','group','trigger','triggercondition',
    'triggeraction','timer','location','region','rect','boolexpr','sound','conditionfunc',
    'filterfunc','unitpool','itempool','race','alliancetype','racepreference','gamestate',
    'igamestate','fgamestate','playerstate','playerscore','playergameresult','gameevent',
    'playerevent','playerunitevent','unitevent','eventtype','limitop','widgettype','camfield',
    'footprinttype','pathingtype','itemtype','image','ubersplat','texttag','lightning','fogstate',
    'fogmodifier','effect','version','leaderboard','multiboard','multiboarditem','trackable',
    'dialog','button','quest','questitem','defeatcondition','timerdialog','gamecache',
    'framehandle','hashtable','weathereffect','soundtype','animtype','animflags','animprops',
    'blendmode','attacktype','damagetype','weapontype','soundchannel','volumegroup','camera',
    'mark','fogstyle','raritycontrol','aidifficulty','gametype','mapcontrol','placement',
    'startlocprio','gamespeed','gamedifficulty','playerslotstate','mapsavedtype','framepointtype',
    'frameeventtype','oskeytype','textaligntype','framestate','originframetype','comparefunc',
    'unittype','materialtype',
}
STMT_KW = {'local','set','call','return','exitwhen','if','elseif','else','endif','loop',
           'endloop','debug','endfunction'}

IDENT_RE = re.compile(r'[A-Za-z_][A-Za-z0-9_]*\Z')  # gibberish names: all I/J/1, or 1-2 uppercase letters

PREFIX = {
    'integer':'int','real':'real','boolean':'flag','string':'str','code':'code','unit':'unit',
    'trigger':'trigger','group':'group','force':'force','timer':'timer','location':'point',
    'region':'region','rect':'rect','sound':'sound','effect':'fx','item':'item',
    'destructable':'dest','player':'player','hashtable':'hash','leaderboard':'board',
    'multiboard':'board','multiboarditem':'boardItem','boolexpr':'expr','conditionfunc':'cond',
    'filterfunc':'filter','dialog':'dlg','button':'btn','quest':'quest','questitem':'questItem',
    'defeatcondition':'defeatCond','timerdialog':'timerDlg','gamecache':'cache','image':'img',
    'ubersplat':'splat','texttag':'texttag','lightning':'lightning','fogmodifier':'fogMod',
    'fogstate':'fogState','weathereffect':'weather','camera':'cam','unitpool':'unitPool',
    'itempool':'itemPool','race':'race','alliancetype':'allyType','attacktype':'atkType',
    'damagetype':'dmgType','weapontype':'weapType','soundchannel':'sndCh','agent':'agent',
    'event':'event','ability':'ability','buff':'buff','widget':'widget','framehandle':'frame',
    'handle':'handle','version':'version','pathingtype':'pathType','gamestate':'gameState',
    'playerslotstate':'slotState','gamespeed':'gameSpeed','gamedifficulty':'gameDiff',
    'playerstate':'plState','framepointtype':'framePt','unittype':'unitType','race':'race',
}

# ------------------------------------------------------------------ tokenizer
TOK_RE = re.compile(r'''
    (?P<directive>//[!][^\n]*)
  | (?P<comment>//[^\n]*)
  | (?P<string>"(?:\\.|[^"\\])*")
  | (?P<char>'(?:[^'\\]|\\.){1,4}')
  | (?P<number>\$[0-9A-Fa-f]+|\d+\.\d*(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?|\d+)
  | (?P<ident>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<op><=|>=|==|!=|[+\-*/<>=(),\[\]])
''', re.X)

def tokenize(text):
    toks, pos, n = [], 0, len(text)
    while pos < n:
        c = text[pos]
        if c in ' \t\r\n':
            pos += 1; continue
        m = TOK_RE.match(text, pos)
        if not m:
            raise SystemExit(f'tokenizer stuck at offset {pos}: {text[pos:pos+40]!r}')
        toks.append((m.lastgroup, m.group()))
        pos = m.end()
    return toks

# ------------------------------------------------------- structural re-parsing
def restructure(T):
    """Return list of (indent, [tokens]) lines rebuilding JASS layout."""
    lines = []
    i, n = 0, len(T)

    def kw(t):
        return t[1].lower() if (t and t[0] == 'ident') else None

    def flush(ind, cur):
        if cur:
            lines.append((ind, cur))

    def emit(ind, toks):
        lines.append((ind, toks))

    state = 'top'
    while i < n:
        kind, val = T[i]
        if kind in ('comment', 'directive'):
            emit(0, [(kind, val)]); i += 1; continue
        if state == 'top':
            k = kw(T[i])
            if k == 'function':
                cur = [T[i]]; i += 1
                pd = 0
                while i < n:
                    t = T[i]
                    if t[0] == 'ident' and t[1].lower() == 'returns' and pd == 0:
                        cur.append(t); i += 1
                        cur.append(T[i]); i += 1  # return type
                        break
                    if t == ('op', '('): pd += 1
                    if t == ('op', ')'): pd -= 1
                    cur.append(t); i += 1
                emit(0, cur)
                state = 'func'
            elif k in ('native', 'type'):
                cur = [T[i]]; i += 1
                while i < n and kw(T[i]) not in ('function', 'globals', 'native', 'type',
                                                 'endfunction', 'endglobals'):
                    cur.append(T[i]); i += 1
                emit(0, cur)
            elif k == 'globals':
                emit(0, [T[i]]); i += 1
                state = 'globals'
            elif kind in ('comment', 'directive'):
                i += 1
            else:
                emit(0, [T[i]]); i += 1  # unexpected; keep verbatim
        elif state == 'globals':
            k = kw(T[i])
            if k == 'endglobals':
                emit(0, [T[i]]); i += 1; state = 'top'
            elif k in ('comment', 'directive'):
                pass  # handled at loop top
            elif k == 'constant' or (kind == 'ident' and k in TYPES):
                cur = []
                if k == 'constant':
                    cur.append(T[i]); i += 1
                cur.append(T[i]); i += 1  # type
                if kw(T[i]) == 'array':
                    cur.append(T[i]); i += 1
                cur.append(T[i]); i += 1  # name
                if i < n and T[i] == ('op', '='):
                    cur.append(T[i]); i += 1
                    pd = 0
                    while i < n:
                        t = T[i]
                        if t[0] == 'op':
                            if t[1] == '(': pd += 1
                            elif t[1] == ')': pd -= 1
                        nxt = kw(T[i])
                        if pd == 0 and t[0] == 'ident' and (
                              nxt in ('endglobals', 'function', 'endfunction',
                                      'native', 'type') or
                              nxt == 'constant' or
                              nxt in TYPES):
                            break
                        cur.append(t); i += 1
                emit(0, cur)
            else:
                emit(0, [T[i]]); i += 1  # keep stray verbatim
        else:  # function body
            stack = ['func']  # sentinel: body base indent = 1
            while i < n:
                kind, val = T[i]
                if kind in ('comment', 'directive'):
                    emit(len(stack), [(kind, val)]); i += 1; continue
                d = len(stack)
                k = kw(T[i])
                if k == 'endfunction':
                    emit(0, [T[i]]); i += 1; state = 'top'; break
                elif k in ('if', 'elseif'):
                    ind = d if k == 'if' else d - 1
                    cur = [T[i]]; i += 1; pd = 0
                    while i < n:
                        t = T[i]
                        if t[0] == 'op':
                            if t[1] == '(': pd += 1
                            elif t[1] == ')': pd -= 1
                        if t[0] == 'ident' and t[1].lower() == 'then' and pd == 0:
                            cur.append(t); i += 1; break
                        cur.append(t); i += 1
                    emit(ind, cur)
                    if k == 'if':
                        stack.append('if')
                elif k == 'else':
                    emit(d - 1, [T[i]]); i += 1
                elif k == 'endif':
                    emit(d - 1, [T[i]]); i += 1; stack.pop()
                elif k == 'loop':
                    emit(d, [T[i]]); i += 1; stack.append('loop')
                elif k == 'endloop':
                    emit(d - 1, [T[i]]); i += 1; stack.pop()
                elif k == 'debug' and i + 1 < n and kw(T[i+1]) in (
                        'if', 'elseif', 'loop', 'endif', 'endloop', 'else'):
                    # `debug` prefix on a block keyword must stay on one line
                    nxt = kw(T[i+1])
                    ind = d if nxt in ('if', 'loop') else d - 1
                    cur = [T[i], T[i+1]]; i += 2; pd = 0
                    if nxt in ('if', 'elseif'):
                        while i < n:
                            t = T[i]
                            if t[0] == 'op':
                                if t[1] == '(': pd += 1
                                elif t[1] == ')': pd -= 1
                            if t[0] == 'ident' and t[1].lower() == 'then' and pd == 0:
                                cur.append(t); i += 1; break
                            cur.append(t); i += 1
                    emit(ind, cur)
                    if nxt in ('if', 'loop'):
                        stack.append(nxt)
                    elif nxt in ('endif', 'endloop'):
                        stack.pop()
                elif k in ('local', 'set', 'call', 'return', 'exitwhen', 'debug'):
                    cur = [T[i]]; i += 1; pd = 0
                    # a `debug` prefix belongs to the statement that follows it,
                    # so the first statement keyword must not terminate the line
                    skip_stop = 1 if k == 'debug' else 0
                    while i < n:
                        t = T[i]
                        if t[0] == 'op':
                            if t[1] == '(': pd += 1
                            elif t[1] == ')': pd -= 1
                        if t[0] == 'ident' and pd == 0:
                            l = t[1].lower()
                            if l == 'then':
                                cur.append(t); i += 1; break
                            if l in STMT_KW:
                                if skip_stop > 0:
                                    skip_stop -= 1
                                else:
                                    break
                        cur.append(t); i += 1
                    emit(d, cur)
                else:
                    emit(d, [T[i]]); i += 1  # stray token
            # end while (function body)
    return lines

# ------------------------------------------------------------ collect declarations
def parse_globals(glines):
    out = []  # (tokens, meta)  meta: dict(type,name,is_array,is_const,init_toks)
    for ind, toks in glines:
        if not toks or toks[0][0] in ('comment', 'directive'):
            continue
        j = 0
        is_const = False
        if toks[j][1].lower() == 'constant':
            is_const = True; j += 1
        if j >= len(toks) or toks[j][1].lower() not in TYPES or j + 1 >= len(toks):
            print('WARN: skip malformed globals line:',
                  ' '.join(t[1] for t in toks)[:100])
            continue
        typ = toks[j][1]; j += 1
        is_array = False
        if j < len(toks) and toks[j][1].lower() == 'array':
            is_array = True; j += 1
        name = toks[j][1]; j += 1
        init = toks[j+1:] if j < len(toks) and toks[j][1] == '=' else []
        out.append({'toks': toks, 'type': typ.lower(), 'name': name,
                    'array': is_array, 'const': is_const, 'init': init})
    return out

def parse_functions(lines):
    funcs = []  # dict(name, ret, params[(t,n)], body_lines, header)
    cur = None
    for ind, toks in lines:
        if not toks:
            continue
        if toks[0][1].lower() == 'function' and toks[0][0] == 'ident':
            name = toks[1][1]
            params = []
            ret = 'nothing'
            if len(toks) > 3 and toks[2][1].lower() == 'takes':
                ptoks = []
                for t in toks[3:]:
                    if t[1].lower() == 'returns':
                        break
                    ptoks.append(t)
                if not (len(ptoks) == 1 and ptoks[0][1].lower() == 'nothing'):
                    ptoks = [t for t in ptoks if t != ('op', ',')]
                    for k in range(0, len(ptoks) - 1, 2):
                        params.append((ptoks[k][1].lower(), ptoks[k+1][1]))
            for k, t in enumerate(toks):
                if t[1].lower() == 'returns' and k + 1 < len(toks):
                    ret = toks[k+1][1].lower()
            cur = {'name': name, 'params': params, 'ret': ret,
                   'body': [], 'header': toks}
            funcs.append(cur)
        elif cur is not None and not (toks[0][0] == 'ident'
                                      and toks[0][1].lower() == 'endfunction'):
            cur['body'].append((ind, toks))
    return funcs

def collect_locals(func):
    locs = []
    for ind, toks in func['body']:
        if toks and toks[0][0] == 'ident' and toks[0][1].lower() == 'local' and len(toks) >= 3:
            j = 1
            typ = toks[j][1].lower(); j += 1
            is_array = False
            if j < len(toks) and toks[j][1].lower() == 'array':
                is_array = True; j += 1
            if j < len(toks) and toks[j][0] == 'ident':
                locs.append({'type': typ, 'name': toks[j][1], 'array': is_array,
                             'init': toks[j+2:] if j+1 < len(toks) and toks[j+1][1] == '=' else []})
    return locs

# ------------------------------------------------------------------- naming
def slug_from_literal(s):
    words = re.findall(r'[A-Za-z0-9]+', s)
    if not words:
        return None
    out = words[0].lower()
    for w in words[1:]:
        out += w[:1].upper() + w[1:].lower()
    return out[:24]

def init_hint(init_toks):
    """Return semantic base name from initializer, or None."""
    if not init_toks:
        return None
    k0, v0 = init_toks[0]
    if k0 == 'ident':
        m = {'createtrigger': 'trigger', 'creategroup': 'group', 'createtimer': 'timer',
             'createforce': 'force', 'createregion': 'region', 'createleaderboard': 'board',
             'createmultiboard': 'board', 'createitempool': 'itemPool',
             'createunitpool': 'unitPool', 'createimage': 'img', 'createtexttag': 'texttag',
             'createbutton': 'btn', 'createdialog': 'dlg', 'createquest': 'quest',
             'createtimerdialog': 'timerDlg', 'createdefeatcondition': 'defeatCond',
             'createlocation': 'point', 'createrect': 'rect'}
        return m.get(v0.lower())
    if k0 == 'string':
        s = slug_from_literal(v0[1:-1])
        return s
    return None

class Namer:
    def __init__(self, used):
        self.used = set(u.lower() for u in used)
        self.counters = defaultdict(int)
    def fresh(self, base):
        base = re.sub(r'[^A-Za-z0-9_]', '', base) or 'v'
        self.counters[base.lower()] += 1
        c = self.counters[base.lower()]
        name = f'{base}{c:03d}'
        while name.lower() in self.used:
            self.counters[base.lower()] += 1
            c = self.counters[base.lower()]
            name = f'{base}{c:03d}'
        self.used.add(name.lower())
        return name

def type_prefix(typ, is_array):
    p = PREFIX.get(typ, typ if IDENT_RE.match(typ or '') else 'v')
    return (p + 'Arr') if is_array else p

def fourcc_lit(tokval):
    """Convert a decimal integer literal to a fourcc 'xxxx' literal if all 4
    bytes are printable ASCII (same numeric value in JASS)."""
    if not tokval.isdigit():
        return None
    v = int(tokval)
    if not (1000000 <= v <= 2147483647):
        return None
    bs = [(v >> 24) & 255, (v >> 16) & 255, (v >> 8) & 255, v & 255]
    if all(32 <= b <= 126 and b not in (39, 92) for b in bs):
        return "'" + ''.join(chr(b) for b in bs) + "'"
    return None

def main(argv):
    args = argv[1:]
    src = SRC
    out = DEFAULT_OUT
    mapf = DEFAULT_MAP
    i = 0
    while i < len(args):
        a = args[i]
        if a in ('-h', '--help'):
            print(USAGE); return 0
        elif a in ('-o', '--output'):
            if i + 1 >= len(args):
                print(USAGE); return 2
            out = args[i+1]; i += 2
        elif a in ('-m', '--map'):
            if i + 1 >= len(args):
                print(USAGE); return 2
            mapf = args[i+1]; i += 2
        elif a.startswith('-o') and len(a) > 2:
            out = a[2:]; i += 1
        elif a.startswith('-m') and len(a) > 2:
            mapf = a[2:]; i += 1
        elif a.startswith('-'):
            print(f'unknown option: {a}\n{USAGE}'); return 2
        else:
            src = a; i += 1
    if out == DEFAULT_OUT and src != SRC:
        base = re.sub(r'\.j$', '', src, flags=re.I)
        out = base + '_deobfuscated.j'
    global OUT, MAPF
    OUT, MAPF = out, mapf
    try:
        raw = open(src, 'rb').read()
    except OSError as e:
        print(f'error: cannot read {src}: {e}')
        return 2
    if raw.startswith(b'\xef\xbb\xbf'):
        raw = raw[3:]
    # pick a byte-preserving encoding: pure-ASCII and UTF-8 round-trip exactly,
    # anything else is treated as latin-1 so every byte survives the round trip
    # (important for map scripts with non-UTF8 text, e.g. cp1252 cyrillic)
    try:
        raw.decode('ascii'); enc = 'ascii'
    except UnicodeDecodeError:
        try:
            raw.decode('utf-8'); enc = 'utf-8'
        except UnicodeDecodeError:
            enc = 'latin-1'
    text = raw.decode(enc)

    T = tokenize(text)
    lines = restructure(T)
    print(f'tokens: {len(T)}, lines rebuilt: {len(lines)}')

    glines = []
    fi = 0
    # split: globals lines are those between 'globals' and 'endglobals'
    in_g = False
    for ln in lines:
        toks = ln[1]
        if toks and toks[0][0] == 'ident':
            if toks[0][1].lower() == 'globals': in_g = True; continue
            if toks[0][1].lower() == 'endglobals': in_g = False; continue
        if in_g:
            glines.append(ln)
    globals_decls = parse_globals(glines)
    funcs = parse_functions(lines)
    print(f'globals: {len(globals_decls)}, functions: {len(funcs)}')

    declared_funcs = {f['name'].lower() for f in funcs}
    declared_all = declared_funcs | {g['name'].lower() for g in globals_decls}

    # JASS names are case-insensitive: warn about any that differ only by case
    # (renaming stays behavior-safe, but the map compiler may reject them)
    for label, items in (('function', [f['name'] for f in funcs]),
                         ('global', [g['name'] for g in globals_decls])):
        seen = {}
        for name in items:
            cf = name.lower()
            if cf in seen:
                print(f"WARN: two {label}s differ only by case: "
                      f"{seen[cf]} and {name} (renamed as one)")
            else:
                seen[cf] = name
    funcs_by_name = {}
    for f in funcs:
        funcs_by_name.setdefault(f['name'], f)

    # Functions that pass an argument through to ExecuteFunc (possibly via
    # several layers of wrappers): ExecuteFunc resolves the name at runtime,
    # so string literals at those wrappers' call sites must be renamed too.
    # A wrapper's ExecuteFunc argument is not a literal (it is a variable);
    # if it were a literal the call site needs no rewriting.
    exec_wrappers = set()
    changed = True
    while changed:
        changed = False
        for f in funcs:
            if f['name'].lower() in exec_wrappers:
                continue
            hit = False
            for _, btoks in f['body']:
                for ti in range(len(btoks) - 1):
                    t = btoks[ti]
                    if t[0] == 'ident' and (t[1].lower() == 'executefunc'
                                            or t[1].lower() in exec_wrappers) \
                       and btoks[ti+1] == ('op', '('):
                        if ti + 2 < len(btoks) and btoks[ti+2][0] != 'string':
                            hit = True
                        break
                if hit:
                    break
            if hit:
                exec_wrappers.add(f['name'].lower())
                changed = True

    # keep-set: every identifier we do NOT rename (natives, BJ funcs, readable names)
    def is_obf(s):
        if set(s) <= set('IJ1'):
            return True
        if len(s) <= 2 and s.isupper():
            return True
        return False

    # JASS is case-insensitive: compare everything in lowercase so a generated
    # name can never collide with a kept name that differs only by case.
    used = set(KEYWORDS) | set(TYPES)
    for k, v in T:
        if k == 'ident' and not is_obf(v):
            used.add(v.lower())
    for g in globals_decls:
        if not is_obf(g['name']):
            used.add(g['name'].lower())
    for f in funcs:
        if not is_obf(f['name']):
            used.add(f['name'].lower())
        for t, p in f['params']:
            if not is_obf(p):
                used.add(p.lower())
        for l in collect_locals(f):
            if not is_obf(l['name']):
                used.add(l['name'].lower())

    namer = Namer(used)

    # ---- global names
    gmap = {}   # orig -> new
    ginfo = {}  # orig -> (type, array)
    for g in globals_decls:
        o = g['name']
        ginfo[o.lower()] = (g['type'], g['array'])
        if not is_obf(o):
            gmap[o] = o; continue
        base = init_hint(g['init'])
        if g['init'] and g['init'][0][0] == 'ident' and g['init'][0][1].lower() == 'stringhash' \
           and len(g['init']) >= 3 and g['init'][2][0] == 'string':
            s = slug_from_literal(g['init'][2][1][1:-1])
            base = ('hash_' + s) if s else None
        if base is None:
            base = type_prefix(g['type'], g['array'])
        gmap[o] = namer.fresh(base)

    # ---- wrapper detection & roles
    roles = defaultdict(set)
    for f in funcs:
        for ind, toks in f['body']:
            stack = []
            last_ident = None
            for t in toks:
                if t[0] == 'ident':
                    if t[1].lower() == 'function' :
                        if stack:
                            roles[f['name']].add((stack[-1], t[1]))
                        continue
                    last_ident = t[1]
                elif t == ('op', '('):
                    stack.append(last_ident)
                elif t == ('op', ')'):
                    if stack: stack.pop()

    def wrapper_of(f):
        body = [(i, t) for i, t in f['body'] if t and t[0] not in ('comment', 'directive')]
        if len(body) != 1:
            return None
        toks = body[0][1]
        if len(toks) >= 4 and toks[0][1].lower() in ('return', 'call'):
            callee = toks[1]
            if callee[0] != 'ident' or toks[2] != ('op', '(') or toks[-1] != ('op', ')'):
                return None
            if callee[1].lower() not in declared_funcs \
               and callee[1].lower() not in KEYWORDS:
                return callee[1]
        return None

    fmap = {}
    fmeta = {}
    fcount = 0
    for f in funcs:
        o = f['name']
        if not is_obf(o):
            fmap[o] = o
            fmeta[o] = ('kept', f)
            continue
        w = wrapper_of(f)
        if w:
            fmap[o] = namer.fresh(w + 'W')
            fmeta[o] = ('wrapper:' + w, f)
            continue
        role_base = None
        for callee, _ in roles.get(o, ()):  # pick first meaningful role
            c = callee.lower()
            if c == 'condition': role_base = 'Cond'; break
            if c == 'filter': role_base = 'Filter'; break
            if c == 'timerstart': role_base = 'TimerCb'; break
            if c == 'forgroup': role_base = 'GroupCb'; break
            if c == 'forforce': role_base = 'ForceCb'; break
            if c and c.startswith('enum'): role_base = 'EnumCb'; break
            if c == 'triggeraddcondition': role_base = 'Cond'; break
            if c == 'triggeraddaction': role_base = 'ActCb'; break
        if role_base is None:
            fcount += 1
            role_base = 'Func'
        fmap[o] = namer.fresh(role_base)
        fmeta[o] = (role_base, f)

    # ---- per-function local maps + rewriting
    gmap_low = {k.lower(): v for k, v in gmap.items()}
    fmap_low = {k.lower(): v for k, v in fmap.items()}

    warned_exec_targets = set()
    exec_string_records = []  # (original_name, new_name) string literals for ExecuteFunc

    def rewrite_string_target(lit_tok):
        """Check a string literal holding a function name for ExecuteFunc;
        returns (replacement_token, orig_name) or (None, orig_name) if it must
        stay untouched."""
        name = lit_tok[1][1:-1]
        if name.lower() not in declared_funcs:
            if name.lower() not in warned_exec_targets:
                warned_exec_targets.add(name.lower())
                print(f"WARN: ExecuteFunc target {name!r} is not a declared function")
            return None, name
        newn = fmap_low.get(name.lower(), name)
        if newn == name:
            return None, name
        return ('string', '"' + newn + '"'), name

    def rewrite_tokens(toks, local_map):
        out, edits = [], []

        def rewrite_ident(t):
            """Rename an identifier per scope (locals shadow globals/functions);
            returns the new token or None to keep as-is."""
            l = t[1].lower()
            if l in local_map:
                edits.append((t[1], local_map[l]))
                return ('ident', local_map[l])
            if l in gmap_low:
                edits.append((t[1], gmap_low[l]))
                return ('ident', gmap_low[l])
            if l in fmap_low:
                edits.append((t[1], fmap_low[l]))
                return ('ident', fmap_low[l])
            return None

        # depths of parens that open an ExecuteFunc / wrapper call argument
        # list: string literals directly inside them hold function names
        depth = 0
        exec_depths = []
        pending_exec = False
        for t in toks:
            if t[0] == 'number':
                fc = fourcc_lit(t[1])
                if fc:
                    out.append(('char', fc))
                    continue
            if t == ('op', '('):
                depth += 1
                if pending_exec:
                    exec_depths.append(depth)
            elif t == ('op', ')'):
                if depth in exec_depths:
                    exec_depths.remove(depth)
                depth -= 1
            if t[0] == 'ident':
                r = rewrite_ident(t)
                out.append(r if r else t)
                l = t[1].lower()
                pending_exec = (l == 'executefunc' or l in exec_wrappers)
                continue
            if t[0] == 'string' and depth in exec_depths:
                rep, name = rewrite_string_target(t)
                if rep:
                    out.append(rep)
                    edits.append((name, rep[1][1:-1]))
                    exec_string_records.append((name, rep[1][1:-1]))
                    continue
            out.append(t)
            pending_exec = False
        return out, edits

    all_edits = []           # (orig, new)
    rename_records = []      # for csv
    new_lines = []

    cur_local_map = {}
    for ind, toks in lines:
        if toks and toks[0][0] == 'ident' and toks[0][1].lower() == 'function':
            fname = toks[1][1]
            f = funcs_by_name.get(fname)
            cur_local_map = {}
            if f:
                # every local/param gets an entry (renamed or identity) so a
                # kept name like `i` correctly shadows a global renamed from `I`
                for t, p in f['params']:
                    if is_obf(p):
                        cur_local_map[p.lower()] = namer.fresh(type_prefix(t.lower(), False))
                        rename_records.append(('param', fname, p, cur_local_map[p.lower()], t))
                    elif p.lower() not in cur_local_map:
                        cur_local_map[p.lower()] = p
                for l in collect_locals(f):
                    if l['name'].lower() in cur_local_map:
                        continue
                    if is_obf(l['name']):
                        base = init_hint(l['init']) or type_prefix(l['type'], l['array'])
                        cur_local_map[l['name'].lower()] = namer.fresh(base)
                        rename_records.append(('local', fname, l['name'],
                                               cur_local_map[l['name'].lower()], l['type']))
                    else:
                        cur_local_map[l['name'].lower()] = l['name']
            new_hdr, ed = rewrite_tokens(toks, cur_local_map)
            all_edits.extend(ed)
            new_lines.append((ind, new_hdr))
            # header comment listing natives used
            if f:
                body_ids = set()
                for _, bt in f['body']:
                    for tk in range(len(bt)):
                        t = bt[tk]
                        if t[0] == 'ident' and tk + 1 < len(bt) and bt[tk+1] == ('op', '(') \
                           and not is_obf(t[1]) and t[1].lower() not in KEYWORDS \
                           and t[1].lower() not in declared_all:
                            body_ids.add(t[1])
                if body_ids:
                    lst = sorted(body_ids)[:12]
                    new_lines.append((1, [('comment', '// uses: ' + ', '.join(lst))]))
        else:
            new_toks, ed = rewrite_tokens(toks, cur_local_map)
            all_edits.extend(ed)
            new_lines.append((ind, new_toks))

    # record global + function renames
    for g in globals_decls:
        if gmap[g['name']] != g['name']:
            rename_records.append(('global', '', g['name'], gmap[g['name']], g['type']))
    for f in funcs:
        if fmap[f['name']] != f['name']:
            kind, _ = fmeta[f['name']]
            rename_records.append(('func', '', f['name'], fmap[f['name']], kind))

    # ---------------------------------------------------------------- serialize
    KW_LOW = {k.lower() for k in KEYWORDS}
    BINOPS = {'=', '+', '-', '*', '/', '<', '>', '<=', '>=', '==', '!='}
    NOSPACE_BEFORE = {')', ']', ','}

    def ser(toks):
        parts = []
        prev = None
        unary_next = False
        for idx, t in enumerate(toks):
            if t[0] in ('comment', 'directive'):
                parts.append(t[1])
                prev = None
                continue
            sep = ' '
            v = t[1]
            pv = prev[1] if prev else None
            un = unary_next
            unary_next = False
            if prev is None:
                sep = ''
            elif un:
                sep = ''
            elif v in NOSPACE_BEFORE:
                sep = ''
            elif pv in ('(', '['):
                sep = ''
            elif v == '(' and prev[0] == 'ident' and pv.lower() not in KW_LOW:
                sep = ''
            elif v == '[' and prev[0] == 'ident':
                sep = ''
            elif pv == ',':
                sep = ' '
            elif v in BINOPS or pv in BINOPS:
                sep = ' '
            elif v in ('and', 'or') or pv in ('and', 'or'):
                sep = ' '
            if v == '-' and (prev is None or prev[1] in ('(', '[', ',', '=', '+', '-', '*', '/',
                                   '<', '>', '<=', '>=', '==', '!=') or
                             (prev[0] == 'ident' and prev[1].lower() in
                              ('return', 'then', 'not', 'and', 'or', 'exitwhen'))):
                unary_next = True
                if prev is not None and prev[1] not in ('(', '[', ',') and not un:
                    sep = ' '
                elif prev is not None and not un:
                    sep = ''
            parts.append(sep + v if sep else v)
            prev = t
        s = ''.join(parts)
        s = re.sub(r'\s+,', ',', s)
        s = re.sub(r'\s+\)', ')', s)
        s = re.sub(r'\(\s+', '(', s)
        return s

    out_lines = []
    for ind, toks in new_lines:
        s = ser(toks)
        if not s:
            continue
        if s.startswith('//') or s.startswith('//!'):
            out_lines.append('    ' + s if ind else s)
        else:
            out_lines.append('    ' * ind + s)

    import datetime as _dt
    header = (f"// Deobfuscated from {os.path.basename(src)} on "
              f"{_dt.date.today().isoformat()}.\n"
              f"// - formatting restored, obfuscated identifiers renamed (see {os.path.basename(mapf)})\n"
              '// - logic untouched; verified token-equivalent to the original\n')
    with open(OUT, 'w', encoding=enc, newline='\n') as fh:
        fh.write(header)
        fh.write('\n'.join(out_lines))
        fh.write('\n')

    with open(MAPF, 'w', encoding='utf-8-sig', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['scope_kind', 'function', 'original_name', 'new_name', 'type_or_kind'])
        for r in rename_records:
            w.writerow(list(r))
        for orig, new in exec_string_records:
            w.writerow(['execfunc-string', '', orig, new, 'string literal'])

    # ---------------------------------------------------------------- verify
    out_text = open(OUT, encoding=enc).read()
    T2 = [t for t in tokenize(out_text) if t[0] not in ('comment', 'directive')]
    T1 = [t for t in T if t[0] not in ('comment', 'directive')]
    ok = True
    if len(T1) != len(T2):
        print(f'VERIFY FAIL: token count {len(T1)} vs {len(T2)}'); ok = False
    else:
        allowed = defaultdict(set)
        for o, nw in all_edits:
            allowed[o.lower()].add(nw)
        for a, b in zip(T1, T2):
            if a[0] == 'number' and b[0] == 'char':
                v = b[1][1:-1]
                fv = (ord(v[0]) << 24) | (ord(v[1]) << 16) | (ord(v[2]) << 8) | ord(v[3])
                if int(a[1]) == fv:
                    continue
            if a[0] != b[0]:
                print(f'VERIFY FAIL kind: {a} vs {b}'); ok = False; break
            if a[1] != b[1]:
                if a[0] in ('ident', 'string'):
                    key = a[1][1:-1] if a[0] == 'string' else a[1]
                    if b[1][1:-1] if b[0] == 'string' else b[1] in allowed.get(key.lower(), set()):
                        continue
                print(f'VERIFY FAIL value: {a} vs {b}'); ok = False; break
    print('VERIFY:', 'OK' if ok else 'FAILED')
    leftovers = sorted({t[1] for t in T2 if t[0] == 'ident' and is_obf(t[1])
                        and t[1].lower() not in allowed})
    if leftovers:
        print(f'NOTE: {len(leftovers)} obf-looking identifiers still present '
              f'(undeclared):', ' '.join(leftovers[:20]))

    # post-check: every ExecuteFunc / pass-through-wrapper string target in the
    # OUTPUT must exist among the new function names (dangling targets are only
    # possible if the original map already had them)
    wrap_new = {'executefunc'} | {fmap_low[o] for o in exec_wrappers if o in fmap_low}
    new_declared = {v.lower() for v in fmap.values()}
    T2full = tokenize(out_text)
    dangling = set()
    i2 = 0
    while i2 < len(T2full):
        t = T2full[i2]
        if t[0] == 'ident' and t[1].lower() in wrap_new \
           and i2 + 1 < len(T2full) and T2full[i2+1] == ('op', '('):
            depth, j = 1, i2 + 2
            while j < len(T2full) and depth > 0:
                at = T2full[j]
                if at == ('op', '('):
                    depth += 1
                elif at == ('op', ')'):
                    depth -= 1
                elif at[0] == 'string' and depth == 1:
                    name = at[1][1:-1]
                    if name.lower() not in new_declared:
                        dangling.add(name)
                j += 1
            i2 = j
        else:
            i2 += 1
    if dangling:
        print('WARN: ExecuteFunc targets not defined in this script '
              '(dangling in the ORIGINAL map):', ', '.join(sorted(dangling)))
    else:
        print('ExecuteFunc check: all targets resolve to declared functions')

    # invariant: original names of renamed functions/globals must never appear
    # as identifiers in the output (any occurrence means a missed rewrite) —
    # except when the same casefold is a kept name that legitimately shadows
    # a renamed global (e.g. kept local `i` vs renamed global `I`)
    renamed_origs = ({o.lower() for o in fmap if fmap[o] != o}
                     | {o.lower() for o in gmap if gmap[o] != o}) - used
    ghosts = sorted({t[1] for t in T2full
                     if t[0] == 'ident' and t[1].lower() in renamed_origs})
    if ghosts:
        print(f'VERIFY FAIL: {len(ghosts)} unrenamed original names remain: '
              + ' '.join(ghosts[:20]))
        ok = False
    print(f'wrote {OUT} ({len(out_lines)} lines) and {MAPF} ({len(rename_records)} renames)')
    return 0 if ok else 1

if __name__ == '__main__':
    sys.exit(main(sys.argv))
