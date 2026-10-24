#!/usr/bin/env python3
"""Which GPUs have stock where.

    gpus.py                         >= 24GB, secure cloud, US/CA datacenters with network volumes,
                                    ranked by price per GB of VRAM
    gpus.py --vram 48 --all-regions
    gpus.py --no-volumes            also datacenters without network volumes (for --pod-volume-gb)
    gpus.py --cheapest              the cheapest in-stock GPUs anywhere: secure, community and spot prices
    gpus.py --cheapest --top 10 --vram 16 --spot

Datacenters holding one of your network volumes always count as having volumes:
RunPod has reported storageSupport=false for some where existing volumes work.

Stock levels are RunPod's estimate; a create can still fail. Neither view applies
a CUDA filter: a cu130 image needs CUDA 13.0 hosts, which are scarcer than this
shows. Only creating the pod (tools/pod.py) proves it. Prices are pod prices per
hour; serverless bills per second at its own (higher) rates, from the same stock.
"""

import argparse
from datetime import datetime

import rp

STOCK_ORDER = {"High": 0, "Medium": 1, "Low": 2, None: 3}

QUERY = """{
  gpuTypes { id displayName memoryInGb secureCloud communityCloud securePrice communityPrice
             lowestPrice(input: { gpuCount: 1 }) { minimumBidPrice uninterruptablePrice } }
  dataCenters { id location storageSupport gpuAvailability { gpuTypeId stockStatus } }
  myself { networkVolumes { dataCenterId } }
}"""


def price(p):
    return f"{p:6.2f}" if p else "   -  "


def stock_map(data, us_only, volumes_only):
    """gpu id -> [(datacenter, stock, has volumes)] for datacenters reporting stock."""
    mine = {v["dataCenterId"] for v in (data.get("myself") or {}).get("networkVolumes") or []}
    where = {}
    for dc in data["dataCenters"]:
        has_vol = bool(dc.get("storageSupport")) or dc["id"] in mine
        if volumes_only and not has_vol:
            continue
        if us_only and not dc["id"].startswith(("US-", "CA-")):
            continue
        for ga in dc.get("gpuAvailability") or []:
            if ga.get("stockStatus"):
                where.setdefault(ga["gpuTypeId"], []).append((dc["id"], ga["stockStatus"], has_vol))
    for dcs in where.values():
        dcs.sort(key=lambda d: (STOCK_ORDER.get(d[1], 3), d[0]))
    return where, mine


def dc_list(dcs, mine, limit=None, mark_no_vol=False):
    shown = dcs[:limit] if limit else dcs
    s = "  ".join(f"{d}[{st}]{'+vol' if d in mine else ''}{'*' if mark_no_vol and not v else ''}"
                  for d, st, v in shown)
    return s + (f"  +{len(dcs) - limit} more" if limit and len(dcs) > limit else "")


def by_value(data, args):
    where, mine = stock_map(data, not args.all_regions, not args.no_volumes)
    vram = 24 if args.vram is None else args.vram
    rows = sorted(((g["securePrice"] / g["memoryInGb"], g) for g in data["gpuTypes"]
                   if g.get("secureCloud") and g.get("securePrice") and g.get("memoryInGb", 0) >= vram
                   and g["id"] in where), key=lambda r: (r[0], r[1]["securePrice"]))
    print(f"GPUs >= {vram}GB, secure cloud, {'all regions' if args.all_regions else 'US/CA'}"
          f"{'' if args.no_volumes else ', datacenters with network volumes'}  ({datetime.now():%Y-%m-%d %H:%M})\n")
    print(f"  {'GPU type id':<52} {'VRAM':>5} {'$/hr':>6} {'$/GB':>6}  datacenters (stock)")
    for value, g in rows:
        print(f"  {g['id']:<52} {g['memoryInGb']:>3}GB {g['securePrice']:>6.2f} {value:>6.3f}  "
              f"{dc_list(where[g['id']], mine, mark_no_vol=args.no_volumes)}")
    print("\n  +vol = you have a network volume there"
          + ("; * = no network volumes: pod.py create --pod-volume-gb N" if args.no_volumes else ""))
    print("  Use the GPU type id (first column) in GPU_TYPES / --gpu.")


def cheapest(data, args):
    """The cheapest in-stock GPUs, any cloud, all regions unless --us."""
    where, mine = stock_map(data, args.us, False)
    vram = args.vram or 0
    rows = []
    for g in data["gpuTypes"]:
        if g["id"] not in where or g.get("memoryInGb", 0) < vram:
            continue
        lp = g.get("lowestPrice") or {}
        secure = g.get("securePrice") if g.get("secureCloud") else None
        community = g.get("communityPrice") if g.get("communityCloud") else None
        spot = lp.get("minimumBidPrice")
        ondemand = min([p for p in (secure, community, lp.get("uninterruptablePrice")) if p], default=None)
        rank = (spot or ondemand) if args.spot else (ondemand or spot)
        if rank:
            rows.append((rank, g, secure, community, spot))
    rows.sort(key=lambda r: (r[0], r[1]["id"]))
    print(f"The {args.top} cheapest in-stock GPUs{f' >= {vram}GB' if vram else ''}, "
          f"{'US/CA' if args.us else 'all regions'}, by {'spot' if args.spot else 'on-demand'} price"
          f"  ({datetime.now():%Y-%m-%d %H:%M}, {len(where)} GPU types in stock)\n")
    print(f"  {'#':>2}  {'GPU type id':<44} {'VRAM':>5} {'Secure':>6} {'Commty':>6} {'Spot':>6}  datacenters (stock)")
    for i, (_, g, secure, community, spot) in enumerate(rows[:args.top], 1):
        print(f"  {i:>2}  {g['id']:<44} {g['memoryInGb']:>3}GB {price(secure)} {price(community)} {price(spot)}  "
              f"{dc_list(where[g['id']], mine, limit=4)}")
    print("\n  Secure = secure cloud (network volumes possible). Commty = community cloud (cheaper, no network"
          "\n  volumes). Spot = interruptible: the pod can be stopped at any time. $ per hour, pod prices."
          "\n  +vol = you have a network volume there.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--vram", type=int, help="minimum VRAM in GB (default 24; --cheapest: any)")
    ap.add_argument("--all-regions", action="store_true", help="not only US-/CA- datacenters")
    ap.add_argument("--no-volumes", action="store_true", help="include datacenters without network volumes")
    ap.add_argument("--cheapest", action="store_true", help="the cheapest in-stock GPUs anywhere, any cloud")
    ap.add_argument("--top", type=int, default=10, metavar="N", help="--cheapest: rows to show (default 10)")
    ap.add_argument("--spot", action="store_true", help="--cheapest: rank by spot price")
    ap.add_argument("--us", action="store_true", help="--cheapest: US/CA datacenters only")
    args = ap.parse_args()

    data = rp.graphql(QUERY)
    (cheapest if args.cheapest else by_value)(data, args)


if __name__ == "__main__":
    try:
        main()
    except rp.ApiError as e:
        raise SystemExit(f"ERROR: {e}")
