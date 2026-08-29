"""
demo_artifacts.py

Proof-of-concept walkthrough for the persistent route-artifacts feature
(docs/feature-route-artifacts-and-proximity.md), driven by the pipeline's
REAL OCR output: it reads current_distance from a stream_hud JSONL and uses
it as the rider's route position. So this exercises the actual
"position comes from OCR" path, not a synthetic stream.

It simulates three ride sessions on the SAME route, days apart, sharing one
persistent store file:

  Session 1 (Alice): store empty      -> finds nothing, drops 2 notes.
  Session 2 (Bob):   Alice's 2 exist  -> finds them as he crosses, drops 1.
  Session 3 (Carol): all 3 exist      -> finds all 3.

Each session opens a FRESH ArtifactStore from the same file, so the only way
data reaches a later session is the file on disk -- that is the persistence
claim, demonstrated rather than asserted.

Usage:
    # generate a position stream first (any stream_hud run works):
    python stream_hud.py --video data/training/trimmed-video.mp4 --end-time 59 --fps 1 --out run.jsonl
    python demo_artifacts.py --reset          # clean run of all 3 sessions
"""

import argparse
import json
import os

from route_artifacts import ArtifactDiscoverer, ArtifactStore

ROUTE_ID = "brookline-north"

# This POC lives in a subfolder; anchor default data paths to the project dir
# (its parent) so the script runs the same from anywhere.
_PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_positions(stream_path: str):
    """current_distance (km) per frame from a stream_hud JSONL; Nones dropped.

    unit_value readings are [number, unit] pairs in the JSONL, so we take
    element 0. An unreadable frame (None / malformed) is simply skipped --
    the discoverer's high-water logic tolerates the gaps.
    """
    positions = []
    with open(stream_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            cd = rec.get("readings", {}).get("current_distance")
            if isinstance(cd, list) and cd and isinstance(cd[0], (int, float)):
                positions.append(float(cd[0]))
    return positions


def run_session(store_path, rider, positions, drops):
    # Fresh store from disk each session: data only survives via the file.
    store = ArtifactStore(store_path)
    existing = store.artifacts_for(ROUTE_ID)
    discoverer = ArtifactDiscoverer(existing)

    print(f"\n=== Session: {rider} ===")
    print(f"  {len(existing)} artifact(s) already on the route at start.")

    found = 0
    for km in positions:
        for a in discoverer.advance(km):
            found += 1
            print(f"  [{km:5.2f} km]  FOUND {a.author}'s {a.kind}: \"{a.payload}\"")
    if found == 0:
        print("  (found nothing new this ride)")

    for pos_km, text in drops:
        a = store.drop(ROUTE_ID, pos_km, text, author=rider)
        print(f"  ~drop~       LEFT at {a.position_km:5.2f} km: \"{text}\"")
    store.save()


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stream", default=os.path.join(_PROJ, "run.jsonl"),
                    help="stream_hud JSONL used for rider position (default: <project>/run.jsonl)")
    ap.add_argument("--store", default=os.path.join(_PROJ, "output", "route_artifacts_store.json"),
                    help="persistent artifact store file (default: <project>/output/, gitignored)")
    ap.add_argument("--reset", action="store_true",
                    help="delete the store first, for a clean demo run")
    args = ap.parse_args()

    if not os.path.exists(args.stream):
        raise SystemExit(
            f"No position stream at {args.stream!r}. Generate one first, e.g.:\n"
            f"  python stream_hud.py --video data/training/trimmed-video.mp4 "
            f"--end-time 59 --fps 1 --out run.jsonl")

    if args.reset and os.path.exists(args.store):
        os.remove(args.store)

    positions = load_positions(args.stream)
    if not positions:
        raise SystemExit(f"No readable current_distance values in {args.stream}.")
    print(f"Loaded {len(positions)} route positions from {args.stream} "
          f"({positions[0]:.2f} -> {positions[-1]:.2f} km on route '{ROUTE_ID}')")

    # Drops are placed within the ride's range (5.64 -> 5.93 km) so they fire
    # mid-ride. In the real app a rider drops at their CURRENT position; here
    # we pin fixed spots so the walkthrough is reproducible.
    run_session(args.store, "Alice", positions,
                drops=[(5.72, "Nice tree on your left here!"),
                       (5.88, "Halfway up the hill -- keep going")])
    run_session(args.store, "Bob", positions,
                drops=[(5.80, "Bob was here")])
    run_session(args.store, "Carol", positions, drops=[])

    print(f"\nStore persisted at {args.store} "
          f"(re-run without --reset: Carol still finds all 3).")


if __name__ == "__main__":
    main()
