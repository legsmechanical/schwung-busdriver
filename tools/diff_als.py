#!/usr/bin/env python3
"""diff_als.py — structural diff of two Live Sets.

For learning the format from Live rather than guessing it: generate a Set, let
Live repair/re-save it, then diff. Whatever Live changed is the answer, and it
is authoritative in a way that reading community docs is not.

Usage:  tools/diff_als.py <mine.als> <live-saved.als> [--focus SampleRef]
"""
import gzip, sys, argparse
import xml.etree.ElementTree as ET


def load(p):
    return ET.fromstring(gzip.open(p, 'rb').read().decode('utf-8'))


def flatten(root):
    """path -> value, for every element carrying a Value attribute. Sibling
    repeats are indexed so two tracks don't collapse onto one key."""
    out = {}
    def walk(e, path):
        counts = {}
        for c in e:
            i = counts.get(c.tag, 0); counts[c.tag] = i + 1
            p = f'{path}/{c.tag}[{i}]'
            if 'Value' in c.attrib:
                out[p] = c.attrib['Value']
            for k, v in c.attrib.items():
                if k != 'Value':
                    out[p + '@' + k] = v
            walk(c, p)
    walk(root, root.tag)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('mine'); ap.add_argument('theirs')
    ap.add_argument('--focus', help='only paths containing this substring')
    ap.add_argument('--limit', type=int, default=80)
    a = ap.parse_args()

    A, B = flatten(load(a.mine)), flatten(load(a.theirs))
    keys = sorted(set(A) | set(B))
    if a.focus:
        keys = [k for k in keys if a.focus in k]

    changed = [k for k in keys if A.get(k) != B.get(k)]
    print(f'{len(changed)} differing values'
          f'{" under " + a.focus if a.focus else ""}\n')
    for k in changed[:a.limit]:
        short = k.replace('Ableton/LiveSet/', '')
        print(f'  {short}')
        print(f'      mine : {A.get(k, "—")}')
        print(f'      live : {B.get(k, "—")}')
    if len(changed) > a.limit:
        print(f'\n  … {len(changed) - a.limit} more (raise --limit)')


if __name__ == '__main__':
    main()
