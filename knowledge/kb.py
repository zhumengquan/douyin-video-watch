#!/usr/bin/env python
"""知识树的读写工具。把 DESIGN.md 里的三个动作变成可执行命令。

为什么要有脚本：手改 YAML 迟早出错，而且「修正要留痕」这条靠自觉一定守不住。
脚本强制：不能直接覆盖旧值，推翻必须走 revise，冲突必须开 conflicts 条目。

命令:
    python kb.py list [--topic vbt] [--status active]
    python kb.py show <fact_id>
    python kb.py absorb --file new_facts.json
    python kb.py revise <fact_id> --file new_value.json
    python kb.py conflict --file clash.json
    python kb.py source --file author.yaml
    python kb.py check
"""
import argparse
import datetime as dt
import json
import os
import sys

try:
    import yaml
except ImportError:
    sys.exit("需要 pyyaml：pip install pyyaml")

HERE = os.path.dirname(os.path.abspath(__file__))
KB = HERE


def now():
    return dt.datetime.now().strftime("%Y-%m-%d")


def load_all(sub):
    d = os.path.join(KB, sub)
    out = {}
    if not os.path.isdir(d):
        return out
    for fn in sorted(os.listdir(d)):
        if not fn.endswith((".yaml", ".yml")):
            continue
        p = os.path.join(d, fn)
        with open(p, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if isinstance(data, dict):
            out[fn] = data
    return out


def facts_index():
    """返回 {fact_id: (文件名, 内容)}。每个文件可以放多条 facts。"""
    idx = {}
    for fn, data in load_all("facts").items():
        for fact in (data.get("facts") or []):
            idx[fact["id"]] = (fn, fact)
    return idx


def write_yaml(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False,
                       default_flow_style=False, width=100)


def read_yaml_or(path, default):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or default
    return default


def file_for_topic(topic):
    safe = topic.replace(".", "_").replace("/", "_")
    return os.path.join(KB, "facts", f"{safe}.yaml")


def merge_sources(fact, sources):
    """往已有 fact 追加来源，去重（同 aweme_id + 同 t 视为同一证据）。"""
    have = {(s.get("aweme_id"), round(float(s.get("t") or -1), 2))
            for s in (fact.get("sources") or [])}
    added = 0
    for s in sources:
        key = (s.get("aweme_id"), round(float(s.get("t") or -1), 2))
        if key not in have:
            fact.setdefault("sources", []).append(s)
            have.add(key)
            added += 1
    return added


def recompute_confidence(fact):
    """来源越多越可信，但有上限；disputed 时压低。

    这不是精确科学，是一个防止"单来源就写 0.9"的闸门。
    单来源 0.5，两个独立来源 0.7，三个 0.8，四个以上 0.85 封顶。
    disputed 打 0.6 折 —— 有反证的东西不该显得很确定。
    """
    n = len({(s.get("aweme_id")) for s in (fact.get("sources") or [])})
    if n >= 4:
        c = 0.85
    elif n == 3:
        c = 0.8
    elif n == 2:
        c = 0.7
    elif n == 1:
        c = 0.5
    else:
        c = 0.1
    if fact.get("status") == "disputed":
        c *= 0.6
    return round(c, 2)


# ---------------- 命令 ----------------

def cmd_list(args):
    idx = facts_index()
    rows = []
    for fid, (fn, fact) in idx.items():
        if args.topic and not fid.startswith(args.topic):
            continue
        if args.status and fact.get("status") != args.status:
            continue
        rows.append((fid, fact))
    if not rows:
        print("(空)")
        return
    print(f"{'id':38s} {'status':11s} {'conf':>5}  claim")
    for fid, fact in sorted(rows):
        print(f"{fid:38s} {fact.get('status','?'):11s} "
              f"{fact.get('confidence',0):5.2f}  {str(fact.get('claim'))[:60]}")


def cmd_show(args):
    idx = facts_index()
    if args.fact_id not in idx:
        sys.exit(f"没有这条 fact: {args.fact_id}")
    fn, fact = idx[args.fact_id]
    print(yaml.safe_dump(fact, allow_unicode=True, sort_keys=False, width=100))


def cmd_absorb(args):
    """吸纳：不存在则新建；已存在且一致则追加来源并提置信度。"""
    with open(args.file, encoding="utf-8") as f:
        payload = yaml.safe_load(f) if args.file.endswith((".yaml", ".yml")) \
            else json.load(f)
    incoming = payload.get("facts") if isinstance(payload, dict) else payload
    if not incoming:
        sys.exit("没有读到 facts")

    idx = facts_index()
    created, merged, revised, clashed = [], [], [], []

    for item in incoming:
        fid = item["id"]
        topic = item.get("topic") or fid.split(".")[0]

        if fid not in idx:
            fact = dict(item)
            fact.setdefault("status", "active")
            fact["first_seen"] = now()
            fact["last_seen"] = now()
            fact["confidence"] = recompute_confidence(fact)
            path = file_for_topic(topic)
            box = read_yaml_or(path, {"facts": []})
            box.setdefault("facts", []).append(fact)
            write_yaml(path, box)
            idx[fid] = (os.path.basename(path), fact)
            created.append(fid)
            continue

        fn, fact = idx[fid]
        same = str(fact.get("value")) == str(item.get("value"))
        if same:
            n = merge_sources(fact, item.get("sources") or [])
            fact["last_seen"] = now()
            fact["confidence"] = recompute_confidence(fact)
            path = os.path.join(KB, "facts", fn)
            box = read_yaml_or(path, {"facts": []})
            for k, f in enumerate(box["facts"]):
                if f["id"] == fid:
                    box["facts"][k] = fact
            write_yaml(path, box)
            if n:
                merged.append(f"{fid} (+{n} 来源 → conf {fact['confidence']})")
            else:
                merged.append(f"{fid} (来源已存在，未变)")
        else:
            # 值不一致 —— 交给 revise 或 conflict 处理，这里只报告
            clashed.append(f"{fid}: 已有 {fact.get('value')} vs 新 {item.get('value')}")

    print(json.dumps({"created": created, "merged": merged,
                      "needs_decision": clashed}, ensure_ascii=False, indent=2))
    if clashed:
        print("\n以上值不一致，需要你决定：走 revise（推翻旧值）还是 conflict（并存标记冲突）。")


def cmd_revise(args):
    """修正：旧 fact 标 superseded，新建一条 supersedes 它。禁止直接覆盖。"""
    with open(args.file, encoding="utf-8") as f:
        new = yaml.safe_load(f) if args.file.endswith((".yaml", ".yml")) else json.load(f)

    idx = facts_index()
    if args.fact_id not in idx:
        sys.exit(f"没有这条 fact: {args.fact_id}")
    fn, old = idx[args.fact_id]

    if not new.get("why"):
        sys.exit("revise 必须给 why：写清为什么推翻旧结论")

    # 新 id 的版本号 = 这条知识被推翻过几次 + 2。
    # 不能按来源数量算（那是我一开始写错的）：来源多说明证据多，
    # 和"改过几次主意"是两件事。这里顺着 supersedes 链往上数。
    gen = 2
    probe = old
    while probe.get("supersedes"):
        gen += 1
        prev = idx.get(probe["supersedes"])
        if not prev:
            break
        probe = prev[1]
        if gen > 50:      # 防环
            break
    # 去掉已有的版本后缀，得到基础 id。
    # 注意不能用 args.fact_id.split(".v")[0] —— 对 "barbell.velocity_by_lift_type"
    # 这种不含 .v 的 id，它会切在第一个 "." 上，把 id 砍成 "barbell"，
    # 生成出 "barbell.v2" 这种丢了主体的名字（踩过）。
    import re as _re
    base_id = _re.sub(r"\.v\d+$", "", args.fact_id)
    new_fact = {
        "id": new.get("new_id") or f"{base_id}.v{gen}",
        "claim": new["claim"],
        "value": new.get("value"),
        "unit": new.get("unit"),
        "topic": old.get("topic"),
        "sources": new.get("sources") or [],
        "status": "active",
        "supersedes": args.fact_id,
        "note": new["why"],
        "first_seen": now(),
        "last_seen": now(),
    }
    new_fact["confidence"] = recompute_confidence(new_fact)

    old["status"] = "superseded"
    old["superseded_by"] = new_fact["id"]
    old["superseded_on"] = now()
    old["superseded_reason"] = new["why"]

    path = os.path.join(KB, "facts", fn)
    box = read_yaml_or(path, {"facts": []})
    for k, f in enumerate(box["facts"]):
        if f["id"] == args.fact_id:
            box["facts"][k] = old
    if new_fact["topic"] and new_fact["topic"].replace(".", "_") != fn[:-5]:
        # 跨文件的新事实，单独存
        write_yaml(path, box)
        np2 = file_for_topic(new_fact["topic"])
        nb = read_yaml_or(np2, {"facts": []})
        nb.setdefault("facts", []).append(new_fact)
        write_yaml(np2, nb)
    else:
        box["facts"].append(new_fact)
        write_yaml(path, box)

    print(json.dumps({"superseded": args.fact_id, "new": new_fact["id"],
                      "why": new["why"]}, ensure_ascii=False, indent=2))


def cmd_conflict(args):
    with open(args.file, encoding="utf-8") as f:
        c = yaml.safe_load(f) if args.file.endswith((".yaml", ".yml")) else json.load(f)
    c.setdefault("resolution", "unresolved")
    c.setdefault("opened", now())
    path = os.path.join(KB, "conflicts", f"{c['id']}.yaml")
    if os.path.exists(path):
        sys.exit(f"冲突已存在: {c['id']}（要追加立场请直接改文件）")
    write_yaml(path, c)
    # 涉及的 fact 标 disputed
    idx = facts_index()
    touched = []
    for pos in c.get("positions") or []:
        for fid in pos.get("facts") or []:
            if fid in idx:
                fn, fact = idx[fid]
                fact["status"] = "disputed"
                fact["confidence"] = recompute_confidence(fact)
                p2 = os.path.join(KB, "facts", fn)
                box = read_yaml_or(p2, {"facts": []})
                for k, f in enumerate(box["facts"]):
                    if f["id"] == fid:
                        box["facts"][k] = fact
                write_yaml(p2, box)
                touched.append(fid)
    print(json.dumps({"conflict": c["id"], "marked_disputed": touched},
                     ensure_ascii=False, indent=2))


def cmd_source(args):
    with open(args.file, encoding="utf-8") as f:
        s = yaml.safe_load(f) if args.file.endswith((".yaml", ".yml")) else json.load(f)
    key = s.get("sec_uid") or s.get("nickname") or "unknown"
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in key)
    # sec_uid 前缀高度雷同（都以 MS4wLjABAAAA 开头），截断文件名的做法会让
    # 不同博主撞到同一个文件、互相覆盖。所以超过 80 字符时用「前缀 + 哈希」。
    if len(safe) > 80:
        import hashlib
        digest = hashlib.sha1(safe.encode("utf-8")).hexdigest()[:8]
        safe = safe[:70] + "_" + digest
    path = os.path.join(KB, "sources", f"{safe}.yaml")
    old = read_yaml_or(path, {})
    merged = {**old, **s}
    merged.setdefault("first_seen", now())
    merged["last_seen"] = now()
    # observed 是累积的，不要被覆盖
    if old.get("observed") and s.get("observed"):
        seen = {o.get("aweme_id") for o in old["observed"]}
        merged["observed"] = old["observed"] + [
            o for o in s["observed"] if o.get("aweme_id") not in seen]
    write_yaml(path, merged)
    print(json.dumps({"saved": os.path.basename(path),
                      "reliability": merged.get("reliability"),
                      "observed": len(merged.get("observed") or [])},
                     ensure_ascii=False))


def cmd_check(args):
    """体检：找悬空引用、格式问题。"""
    idx = facts_index()
    problems = []
    for fid, (fn, fact) in idx.items():
        for k in ("claim", "topic", "sources", "status"):
            if k not in fact:
                problems.append(f"{fid}: 缺字段 {k}")
        if fact.get("status") == "superseded" and not fact.get("superseded_by"):
            problems.append(f"{fid}: superseded 但没写 superseded_by")
        if fact.get("supersedes") and fact["supersedes"] not in idx:
            problems.append(f"{fid}: supersedes 指向不存在的 {fact['supersedes']}")
        if not (fact.get("sources") or []):
            problems.append(f"{fid}: 没有来源（知识必须有出处）")

    for fn, c in load_all("conflicts").items():
        for pos in (c.get("positions") or []):
            for fid in (pos.get("facts") or []):
                if fid not in idx:
                    problems.append(f"conflict {c.get('id')}: 引用不存在的 {fid}")
        if c.get("resolution", "unresolved") not in ("unresolved", "unresolvable") \
                and not str(c.get("resolution", "")).startswith("resolved_by"):
            problems.append(f"conflict {c.get('id')}: resolution 格式不对")

    n = len(idx)
    n_act = sum(1 for _, (_, f) in idx.items() if f.get("status") == "active")
    n_dis = sum(1 for _, (_, f) in idx.items() if f.get("status") == "disputed")
    n_sup = sum(1 for _, (_, f) in idx.items() if f.get("status") == "superseded")
    print(json.dumps({"facts": n, "active": n_act, "disputed": n_dis,
                      "superseded": n_sup,
                      "conflicts": len(load_all("conflicts")),
                      "sources": len(load_all("sources")),
                      "problems": problems}, ensure_ascii=False, indent=2))
    return 0 if not problems else 1


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("list"); p.add_argument("--topic"); p.add_argument("--status")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("show"); p.add_argument("fact_id"); p.set_defaults(func=cmd_show)

    p = sub.add_parser("absorb"); p.add_argument("--file", required=True)
    p.set_defaults(func=cmd_absorb)

    p = sub.add_parser("revise"); p.add_argument("fact_id")
    p.add_argument("--file", required=True); p.set_defaults(func=cmd_revise)

    p = sub.add_parser("conflict"); p.add_argument("--file", required=True)
    p.set_defaults(func=cmd_conflict)

    p = sub.add_parser("source"); p.add_argument("--file", required=True)
    p.set_defaults(func=cmd_source)

    p = sub.add_parser("check"); p.set_defaults(func=cmd_check)

    args = ap.parse_args()
    rc = args.func(args)
    sys.exit(rc or 0)


if __name__ == "__main__":
    main()
