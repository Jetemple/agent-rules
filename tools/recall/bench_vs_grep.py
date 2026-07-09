#!/usr/bin/env python3
"""
bench_vs_grep.py — the benchmark that was missing: recall vs the tool you'd
actually use instead (grep). For each labeled query, compare:
  - recall hybrid: rank of the correct note (hit@3?)
  - smart grep:    grep the single most-distinctive (rarest) query word.
                   haystack = how many files match; found = is the answer in them?
  - naive grep:    grep ANY content word (OR). haystack = the noise you'd wade through.
A grep "win" = answer found AND haystack tiny (<=3) -> recall adds nothing.
Recall earns its keep only where smart grep MISSES or buries the answer in a big haystack.
"""
import os, re, sys, subprocess
sys.path.insert(0, os.path.expanduser("~/.recall"))
import recall
from bench_quality import LABELED, rank_hybrid, first_hit_rank

ROOTS = [r for _, r in recall.SOURCES if os.path.isdir(r)]
STOP = set("the a an of to in on at and or but i my me you we it is are am do does did "
           "how what which when where who whom that this these those with for from into "
           "not no any can could should would will run runs running have has had get got "
           "about your his her their its been be was were as by".split())

def content_words(q):
    return [w for w in re.findall(r"[a-zA-Z0-9]+", q.lower()) if len(w) > 2 and w not in STOP]

def rg_files(word):
    """files (in corpus, excluding _scratch/_archive) containing whole-word `word`, case-insensitive."""
    try:
        out = subprocess.run(
            ["rg", "-l", "-i", "-w", "--", word, *ROOTS,
             "--glob", "!_scratch/**", "--glob", "!_archive/**", "--glob", "!.git/**"],
            capture_output=True, text=True, timeout=30)
        return [f for f in out.stdout.splitlines() if f.strip()]
    except Exception:
        return []

def main():
    con, cur = recall.connect()
    rows = []
    rec_hit3 = grep_smart_win = grep_only = rec_only = 0
    for q, exp in LABELED:
        # recall
        r = first_hit_rank(rank_hybrid(cur, q), exp)
        rec_ok = bool(r and r <= 3)
        # grep: per-word haystacks
        words = content_words(q)
        per = [(w, rg_files(w)) for w in words]
        per = [(w, fs) for w, fs in per if fs]            # drop zero-hit words
        # smart grep = rarest word that has any hits
        smart_w, smart_fs = (min(per, key=lambda t: len(t[1])) if per else ("-", []))
        smart_found = any(exp in f for f in smart_fs)
        smart_n = len(smart_fs)
        # naive OR grep haystack
        naive = set()
        for _, fs in per: naive.update(fs)
        naive_found = any(exp in f for f in naive)
        naive_n = len(naive)

        rec_hit3 += rec_ok
        grep_wins = smart_found and smart_n <= 3
        grep_smart_win += grep_wins
        if rec_ok and not smart_found: rec_only += 1
        if smart_found and not rec_ok: grep_only += 1
        rows.append((exp, r, rec_ok, smart_w, smart_n, smart_found, naive_n, naive_found, grep_wins))

    n = len(LABELED)
    print(f"\n=== recall vs grep over {n} labeled queries ===\n")
    hdr = f"{'expected':30} {'rec#':>4} {'smart-grep word':>16} {'hay':>4} {'fnd':>3} {'ORhay':>5} {'verdict'}"
    print(hdr); print("-"*len(hdr))
    for exp, r, rec_ok, sw, sn, sf, nn, nf, gw in rows:
        rc = (str(r) if r else "-")
        fnd = "Y" if sf else "n"
        if gw:           verdict = "grep alone suffices (tiny haystack)"
        elif not sf:     verdict = "grep MISSES -> recall needed" if rec_ok else "both weak"
        else:            verdict = f"grep finds it but in {sn}-file haystack; recall ranks #{rc}"
        print(f"{exp[:30]:30} {rc:>4} {sw[:16]:>16} {sn:>4} {fnd:>3} {nn:>5}  {verdict}")

    print(f"\nrecall hit@3:                 {rec_hit3}/{n}")
    print(f"smart-grep clean win (<=3 files): {grep_smart_win}/{n}  <- where recall adds little/nothing")
    print(f"grep MISSED, recall got it:   {rec_only}/{n}  <- recall's unique saves")
    print(f"grep got it, recall missed:   {grep_only}/{n}")
    median_naive = sorted(r[6] for r in rows)[n//2]
    print(f"median naive-OR-grep haystack: {median_naive} files  <- what dumb grep makes you wade through")

if __name__ == "__main__":
    main()
