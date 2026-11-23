"""
Turn one or more match logs (logs/*.jsonl) into a metrics table.

  python analysis/metrics.py logs/*.jsonl

Reports, per match and in aggregate: winner, how it ended, turns/tool-calls,
wrong submissions, service-down events, uptime penalties, defense-window blocks,
and observed encryption attempts. Extend with your own offense/defense split
once you tag commands as attacking vs defending.
"""
import json, sys, glob
from collections import Counter


def load(path):
    with open(path) as f:
        return [json.loads(l) for l in f if l.strip()]


def summarize(events):
    out = {"winner": None, "reason": None, "mode": "?", "scoring": "?",
           "tool_calls": Counter(), "wrong_submits": 0, "service_down": 0,
           "dw_blocks": 0, "blobs": 0, "fs_events": 0,
           "penalty": {}, "end_kind": None}
    for e in events:
        k = e["kind"]
        if k == "match_start":
            out["mode"] = e.get("mode", "?"); out["scoring"] = e.get("scoring", "?")
        elif k == "tool_call":
            out["tool_calls"][e["agent"]] += 1
        elif k == "submit" and e.get("correct") is False:
            out["wrong_submits"] += 1
        elif k == "service_down":
            out["service_down"] += 1
        elif k == "defense_window_block":
            out["dw_blocks"] += 1
        elif k == "blob_observed":
            out["blobs"] += 1
        elif k == "fs_event":
            out["fs_events"] += 1
        elif k == "result":
            out["winner"] = e["winner"]; out["reason"] = e["reason"]
            out["penalty"] = {"A": e.get("a_penalty", 0), "B": e.get("b_penalty", 0)}
    r = (out["reason"] or "").lower()
    if "captured" in r:                              out["end_kind"] = "capture"
    elif "uptime" in r or "penalty" in r:            out["end_kind"] = "uptime"
    elif "lost its flag" in r or "off-box" in r or "blob" in r:
                                                     out["end_kind"] = "rule_forfeit"
    elif "deadline" in r or "turns" in r:            out["end_kind"] = "draw/timeout"
    else:                                            out["end_kind"] = "other"
    return out


def main(paths):
    agg_end, agg_win = Counter(), Counter()
    print(f"{'match':<10}{'mode':<9}{'winner':<9}{'end':<14}"
          f"{'wrong':<6}{'down':<5}{'dwblk':<6}{'blobs':<6}reason")
    for p in paths:
        s = summarize(load(p))
        mid = p.split("/")[-1].replace(".jsonl", "")
        print(f"{mid:<10}{s['mode']:<9}{str(s['winner']):<9}{s['end_kind']:<14}"
              f"{s['wrong_submits']:<6}{s['service_down']:<5}{s['dw_blocks']:<6}"
              f"{s['blobs']:<6}{s['reason']}")
        agg_end[s["end_kind"]] += 1
        agg_win[s["winner"]] += 1
    print("\n== aggregate ==")
    print("outcomes:", dict(agg_end))
    print("wins:", dict(agg_win))


if __name__ == "__main__":
    files = []
    for a in sys.argv[1:]:
        files += glob.glob(a)
    if not files:
        print(__doc__); sys.exit(1)
    main(sorted(files))
