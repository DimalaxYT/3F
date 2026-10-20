#!/usr/bin/env python3
"""
critique.py — boucle d'autocritique NOTÉE (1-10, seuil de livraison 9.5).

L'agent (LLM) est son propre contrôleur qualité. Le code fournit la structure :
métriques objectives, fiche de critique, validation anti-triche, historique.
La NOTE vient de l'agent après lecture des photos — chaque point perdu doit
correspondre à une issue concrète, sinon le verdict est rejeté.

Règle d'or (celle du prompt d'autocritique) :
    note < 9.5  ->  PAUFINER : corriger le spec, régénérer, re-critiquer.
    note >= 9.5 ->  LIVRER (avec --deliver explicite).
    Jamais de faux 9.5 : à la fin du budget d'itérations, livraison forcée
    avec issues résiduelles documentées (FORCE_DELIVER).

Sous-commandes :
    brief   --dir out/objet --iter N   génère iter_N/critique_brief.md
    verdict --dir out/objet --iter N --note 8.7 --issue "S|..." [--deliver]
    status  --dir out/objet            historique des notes + décision

Barème (10 points) :
    S  silhouette & proportions   0-3   IoU 3 vues + lecture des photos
    V  volume inter-faces         0-2   face/dos/gauche = même objet
    M  matériaux & textures       0-2   palette, overlays, stabilité
    D  détails à respecter        0-2   checklist Stage 0 visible sur photos
    T  technique                  0-1   watertight, budget, dégénérés
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

THRESHOLD_DEFAULT = 9.5
MAX_ITERS_DEFAULT = 4
AXES = {
    "S": "silhouette & proportions (0-3)",
    "V": "volume inter-faces (0-2)",
    "M": "matériaux & textures (0-2)",
    "D": "détails à respecter (0-2)",
    "T": "technique (0-1)",
}


# --------------------------------------------------------------------------
# Lecture des métriques objectives depuis report.json
# --------------------------------------------------------------------------

def load_report(dirpath, it):
    p = os.path.join(dirpath, f"iter_{it}", "report.json")
    if not os.path.isfile(p):
        raise FileNotFoundError(
            f"{p} introuvable — lance d'abord meshgen.py --out {dirpath}/iter_{it}")
    with open(p) as fh:
        return json.load(fh)


def objective_metrics(rep):
    v = rep.get("validation", {})
    iou = v.get("iou_views", rep.get("coherence", {}).get("per_view", {}))
    budget = int(rep.get("params", {}).get("budget_tris", 15000))
    tris = int(v.get("triangles", 0))
    refs = rep.get("references") or {}
    details = refs.get("details_to_respect", [])
    photos = rep.get("photos", {})
    m = {
        "iou_views": iou,
        "iou_mean": v.get("iou_mean", rep.get("coherence", {}).get("mean", 0.0)),
        "watertight": bool(v.get("watertight", False)),
        "winding_consistent": bool(v.get("winding_consistent", False)),
        "triangles": tris,
        "budget_tris": budget,
        "over_budget": bool(v.get("over_budget", tris > budget > 0)),
        "components": int(v.get("components", 0)),
        "degenerate_faces": int(v.get("degenerate_faces", 0)),
        "volume_m3": float(v.get("volume_m3", 0.0)),
        "n_details": len(details),
        "details": details,
        "has_all_faces": "all_faces" in photos,
        "has_turntable": "turntable" in photos,
    }
    # note T suggérée automatiquement (l'agent peut la remonter avec preuve)
    t = 0.0
    if m["watertight"]:
        t += 0.5
    if not m["over_budget"]:
        t += 0.2
    if m["degenerate_faces"] == 0:
        t += 0.15
    if m["winding_consistent"]:
        t += 0.15
    m["t_suggested"] = round(t, 2)
    return m


def formative_iou(m):
    """IoU de formatage : moyenne des DEUX MEILLEURES vues.

    Sur 3 axes, l'un peut être structurellement dégénéré (objet plat : la
    silhouette side d'une lame de 0.7 cm est quasi-1D, IoU plafonné ~0.4
    quel que soit la qualité). Le plafond de note et le garde anti-triche
    utilisent donc les deux meilleures vues, pas la moyenne brute.
    """
    vals = sorted((v for v in m["iou_views"].values()), reverse=True)
    if not vals:
        return 0.0
    top2 = vals[:2]
    return round(sum(top2) / len(top2), 4)


def photo_list(rep):
    """Toutes les photos que l'agent DOIT regarder avant de noter."""
    out, photos = [], rep.get("photos", {})
    for key in ("all_faces", "turntable"):
        if key in photos:
            out.append((f"planche {key}", photos[key]))
    for p in photos.get("faces", []):
        out.append(("face", p))
    for p in photos.get("turn_images", []):
        out.append(("turntable", p))
    for key, label in (("renders", "vue de contrôle"), ("internal_views", "vue interne")):
        for p in rep.get(key, []):
            out.append((label, p))
    refs = rep.get("references") or {}
    if refs.get("sheet"):
        out.append(("références web (détails à respecter)", refs["sheet"]))
    return out


# --------------------------------------------------------------------------
# brief — la fiche de critique
# --------------------------------------------------------------------------

def cmd_brief(args):
    rep = load_report(args.dir, args.iter)
    m = objective_metrics(rep)
    itdir = os.path.join(args.dir, f"iter_{args.iter}")
    iou = m["iou_views"]
    iou_disp = ", ".join(f"{k}={v}" for k, v in iou.items()) or "n/a"
    photos = photo_list(rep)

    L = []
    L.append(f"# Fiche d'autocritique — itération {args.iter}")
    L.append("")
    L.append(f"> Objet : **{rep.get('prompt') or rep.get('pipeline', '?')}**  ")
    L.append(f"> Seuil de livraison : **{args.threshold}** / 10 — ")
    L.append("> **note < seuil => PAUFINER (nouvelle itération obligatoire), "
             "note >= seuil => LIVRER.**")
    L.append("")
    L.append("## 1. Métriques objectives (déjà mesurées par le code)")
    L.append("")
    L.append(f"- IoU multi-vues : {iou_disp} (moyenne {m['iou_mean']}, "
             f"formatage 2 meilleures vues {formative_iou(m)})")
    L.append(f"- Watertight : {m['watertight']} | winding : "
             f"{m['winding_consistent']} | composants : {m['components']}")
    L.append(f"- Triangles : {m['triangles']} / budget {m['budget_tris']} "
             f"(over_budget={m['over_budget']}) | dégénérés : "
             f"{m['degenerate_faces']}")
    L.append(f"- Note T (technique) suggérée par le code : **{m['t_suggested']}** / 1")
    L.append("")
    L.append("## 2. Photos à inspecter — TOUTES, avant de noter")
    L.append("")
    for label, p in photos:
        rp = os.path.relpath(p, itdir) if os.path.isabs(p) else p
        L.append(f"- [ ] `{rp}` ({label})")
    L.append("")
    L.append("## 3. Checklist des détails à respecter (Stage 0 — recherche web)")
    L.append("")
    if m["details"]:
        for d in m["details"]:
            L.append(f"- [ ] DÉTAIL : {d}")
    else:
        L.append("- (aucune référence chargée => axe D plafonné à 1.0/2 — "
                 "lance meshgen avec --references)")
    L.append("")
    L.append("## 4. Barème — chaque point perdu = une issue concrète")
    L.append("")
    L.append("| Axe | Points | Question à te poser devant les photos |")
    L.append("|-----|--------|----------------------------------------|")
    L.append("| S | 0-3 | Les proportions tiennent-elles face/profil/dessus ? "
             "IoU bas = points perdus (plafond sur la moyenne des DEUX "
             "MEILLEURES vues : S<=2 si <0.65, S<=1 si <0.5 — l'axe le plus "
             "faible est exclu car structurellement dégénéré sur objets "
             "plats : lame de 0.7 cm d'épaisseur = silhouette side quasi-1D) |")
    L.append("| V | 0-2 | Face/dos/gauche racontent-ils le MÊME volume ? "
             "partie flottante, aplatie, écrasée ? |")
    L.append("| M | 0-2 | Palette crédible ? overlays (rouille/usure/wrap) "
             "visibles et STABLES entre les angles ? zones peintes qui fuient ? |")
    L.append("| D | 0-2 | Chaque détail de la checklist section 3 est-il VISIBLE "
             "sur une photo ? (1 détail manquant = -0.5) |")
    L.append("| T | 0-1 | Reprends la note T suggérée ci-dessus |")
    L.append("")
    L.append("## 5. Questions guidées (réponds mentalement, note ce qui coince)")
    L.append("")
    L.append("- Quelle partie du rendu te ferait honte si l'utilisateur la "
             "zoomait ?")
    L.append("- Si tu montres cette épée/objet à 10 personnes, combien "
             "reconnaissent l'objet immédiatement ? (<10 => décrémenter S ou V)")
    L.append("- Les textures glissent-elles entre face et profil ?")
    L.append("- Y a-t-il une issue que tu as laissée « parce que ça passe » ?")
    L.append("")
    L.append("## 6. Enregistre ton verdict")
    L.append("")
    L.append("```bash")
    L.append(f"python3 scripts/critique.py verdict --dir {args.dir} "
             f"--iter {args.iter} \\")
    L.append("    --note 8.7 --justification \"...\" \\")
    L.append("    --issue \"S|la pointe s'affine trop tôt : 2 dernières rangées "
             "de la vue front sont mangées par le lissage|monte res 80->96 "
             "et baisse smooth 10->7\" \\")
    L.append("    --issue \"D|le fuller n'est visible qu'en face|-\"")
    L.append("```")
    L.append("")
    L.append("Format d'issue : `AXE|problème observé|correctif proposé` avec "
             "AXE dans " + "/".join(AXES) + ".")
    L.append(f"Rappel : note >= {args.threshold} sans issue OUVERTE, sinon le "
             "verdict est rejeté (pas de 9.5 de complaisance).")
    L.append("")

    out = os.path.join(itdir, "critique_brief.md")
    with open(out, "w") as fh:
        fh.write("\n".join(L))
    print(f"fiche de critique -> {out}")
    print(f"  IoU {iou_disp} | T suggéré {m['t_suggested']} | "
          f"{len(m['details'])} détails | {len(photos)} photos à lire")
    print(f"  règle : note < {args.threshold} => PAUFINER, sinon --deliver")
    return 0


# --------------------------------------------------------------------------
# verdict — validation anti-triche + historique
# --------------------------------------------------------------------------

def load_log(dirpath):
    p = os.path.join(dirpath, "critique_log.json")
    if os.path.isfile(p):
        with open(p) as fh:
            return json.load(fh)
    return {"threshold": THRESHOLD_DEFAULT, "entries": []}


def parse_issues(raw_issues):
    out = []
    for raw in raw_issues or []:
        parts = raw.split("|")
        if len(parts) < 2 or parts[0].strip().upper() not in AXES:
            raise ValueError(
                f"issue invalide : {raw!r} — format attendu "
                f"AXE|problème|correctif avec AXE dans {'/'.join(AXES)}")
        axe = parts[0].strip().upper()
        problem = parts[1].strip()
        fix = parts[2].strip() if len(parts) > 2 else ""
        if not problem or problem == "-":
            raise ValueError("une issue doit décrire un problème observé")
        out.append({"axe": axe, "problem": problem, "fix": fix})
    return out


def cmd_verdict(args):
    rep = load_report(args.dir, args.iter)
    m = objective_metrics(rep)
    issues = parse_issues(args.issue)
    log = load_log(args.dir)
    threshold = args.threshold or log.get("threshold", THRESHOLD_DEFAULT)
    max_iters = args.max_iters or log.get("max_iters", MAX_ITERS_DEFAULT)

    # --- validation anti-triche -------------------------------------------
    if not (1.0 <= args.note <= 10.0):
        print(f"REFUSÉ : note {args.note} hors [1, 10].", file=sys.stderr)
        return 2
    if args.note >= threshold and issues:
        print(f"REFUSÉ : note {args.note} >= seuil {threshold} avec "
              f"{len(issues)} issue(s) ouverte(s) — corrige d'abord ou baisse "
              "la note. Pas de 9.5 de complaisance.", file=sys.stderr)
        return 2
    if args.note < threshold and not issues:
        print("REFUSÉ : note < seuil sans AUCUNE issue — un diagnostic est "
              "obligatoire (que paufiner, et comment ?).", file=sys.stderr)
        return 2
    if args.note >= threshold and not args.deliver:
        print(f"note {args.note} >= seuil {threshold} mais --deliver absent : "
              "verdict enregistré, décision en attente (relance avec --deliver "
              "pour clore la boucle).")
    # décote S si IoU très bas, cohérence note/évidence
    fiou = formative_iou(m)
    if fiou < 0.5 and args.note >= threshold:
        print(f"REFUSÉ : IoU de formatage {fiou} (2 meilleures vues) < 0.5 "
              f"incompatible avec une note >= {threshold} — les silhouettes "
              "sont objectivement hors proportions.", file=sys.stderr)
        return 2

    # --- décision ----------------------------------------------------------
    forced = args.iter >= max_iters
    if args.note >= threshold and args.deliver:
        decision = "DELIVER"
    elif forced:
        decision = "FORCE_DELIVER"
    else:
        decision = "REFINE"

    entry = {
        "iter": args.iter,
        "note": round(args.note, 1),
        "justification": (args.justification or "").strip(),
        "issues": issues,
        "decision": decision,
        "threshold": threshold,
        "metrics_snapshot": {k: m[k] for k in
                             ("iou_views", "iou_mean", "watertight",
                              "triangles", "budget_tris", "components",
                              "degenerate_faces", "t_suggested")},
        "formative_iou": formative_iou(m),
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    log["threshold"] = threshold
    log["max_iters"] = max_iters
    log["object"] = rep.get("prompt", "")
    log["entries"] = [e for e in log.get("entries", [])
                      if e.get("iter") != args.iter] + [entry]
    log["entries"].sort(key=lambda e: e["iter"])
    logp = os.path.join(args.dir, "critique_log.json")
    with open(logp, "w") as fh:
        json.dump(log, fh, indent=2, ensure_ascii=False)

    # --- sortie lisible -----------------------------------------------------
    print(f"\n== AUTOCRITIQUE itération {args.iter} : note "
          f"{entry['note']}/10 (seuil {threshold}) ==")
    if entry["justification"]:
        print(f"  justification : {entry['justification']}")
    for i in issues:
        print(f"  [{i['axe']}] {i['problem']}")
        if i["fix"] and i["fix"] != "-":
            print(f"        correctif : {i['fix']}")
    if decision == "DELIVER":
        print("  DÉCISION : LIVRER — le résultat est au niveau demandé.")
        print(f"  log -> {logp}")
    elif decision == "FORCE_DELIVER":
        print(f"  DÉCISION : LIVRAISON FORCÉE (budget {max_iters} itérations "
              "atteint).")
        print(f"  {len(issues)} issue(s) résiduelle(s) documentée(s) dans le "
              "log — elles partent avec la livraison, jamais cachées.")
        print(f"  log -> {logp}")
    else:
        nxt = args.iter + 1
        print(f"  DÉCISION : PAUFINER — note < {threshold}, livraison "
              "interdite à ce stade.")
        print(f"  => applique les correctifs ci-dessus au spec, puis "
              f"régénère dans {args.dir}/iter_{nxt} et re-critique :")
        print(f"     python3 scripts/critique.py brief --dir {args.dir} "
              f"--iter {nxt}")
    return 0


# --------------------------------------------------------------------------
# status — historique de la boucle
# --------------------------------------------------------------------------

def cmd_status(args):
    log = load_log(args.dir)
    entries = log.get("entries", [])
    if not entries:
        print(f"aucun verdict enregistré dans {args.dir}")
        return 1
    threshold = log.get("threshold", THRESHOLD_DEFAULT)
    print(f"== Boucle d'autocritique : {log.get('object', '?')} ==")
    print(f"   seuil {threshold} | budget {log.get('max_iters', '?')} itérations")
    notes = []
    for e in entries:
        notes.append(e["note"])
        bar = "#" * int(round(e["note"] * 4))
        open_issues = len(e.get("issues", [])) if e["decision"] == "REFINE" else 0
        print(f"   iter {e['iter']} : {e['note']:5.1f} {bar:<40} "
              f"{e['decision']}" + (f" ({open_issues} issues)" if open_issues
                                    else ""))
    delta = notes[-1] - notes[0] if len(notes) > 1 else 0.0
    print(f"   tendance : {delta:+.1f} depuis l'itération 1")
    last = entries[-1]
    if last["decision"] in ("DELIVER", "FORCE_DELIVER"):
        print(f"   BOUCLE CLOSE — note finale {last['note']}/10 "
              f"({last['decision']}).")
    else:
        print(f"   boucle ouverte : {last['note']}/10 < {threshold} — "
              "paufiner (nouvelle itération).")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Boucle d'autocritique notée (1-10, seuil 9.5)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("brief", help="générer la fiche de critique d'une itération")
    b.add_argument("--dir", required=True)
    b.add_argument("--iter", type=int, required=True)
    b.add_argument("--threshold", type=float, default=THRESHOLD_DEFAULT)
    b.set_defaults(fn=cmd_brief)

    v = sub.add_parser("verdict", help="enregistrer la note de l'agent + décision")
    v.add_argument("--dir", required=True)
    v.add_argument("--iter", type=int, required=True)
    v.add_argument("--note", type=float, required=True,
                   help="note globale de l'agent (1-10)")
    v.add_argument("--justification", default="",
                   help="une phrase de justification globale")
    v.add_argument("--issue", action="append", default=[],
                   help="AXE|problème|correctif (répétable)")
    v.add_argument("--deliver", action="store_true",
                   help="clôturer la boucle si note >= seuil")
    v.add_argument("--threshold", type=float, default=None)
    v.add_argument("--max-iters", type=int, default=None)
    v.set_defaults(fn=cmd_verdict)

    s = sub.add_parser("status", help="historique des notes + décision courante")
    s.add_argument("--dir", required=True)
    s.set_defaults(fn=cmd_status)

    args = ap.parse_args(argv)
    try:
        return args.fn(args)
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"REFUSÉ : {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
