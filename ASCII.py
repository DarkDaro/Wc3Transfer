import re


def decimal2ascii(number: int) -> str:
    reminders = []
    while number >= 256:
        number, rem = divmod(number, 256)
        reminders.append(chr(rem))
    reminders.append(chr(number))

    return ''.join(reversed(reminders))


def ascii2decimal(number: str) -> int:
    result = 0
    pw = 1
    for c in reversed(number):
        result += ord(c) * pw
        pw *= 256
    return result


def main():
    input_j = r"D:\Downloads\war3map.j"
    output_j = 'output.j'
    pattern = re.compile(r'0x([\dabcdef]{8})', re.IGNORECASE)
    codes = {}

    def replace_hex(m: re.Match) -> str:
        h = m.group(1)
        if r := codes.get(h):
            return r
        a = f"'{decimal2ascii(int(h, 16))}'"
        codes[h] = a
        return a

    with open(input_j, 'r') as f, open(output_j, 'w') as out:
        for line in f:
            out.write(pattern.sub(replace_hex, line))

    for h, a in sorted(codes.items()):
        print(f'0x{h} -- {a}')


if __name__ == '__main__':
    main()
