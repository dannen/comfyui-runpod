#!/usr/bin/env python3
"""Which GPUs have stock where: secure cloud, datacenters with network volumes,
ranked by price per GB of VRAM.

    gpus.py                     >= 24GB, North America
    gpus.py --vram 48 --all-regions
    gpus.py --no-volumes        include datacenters without network volumes (for --pod-volume-gb)

Stock levels are RunPod's estimate; a "create" can still fail. The listing does
not apply a CUDA filter: a cu130 image needs hosts with CUDA 13.0, which are
scarcer than this shows. Only creating the pod (tools/pod.py) proves it.
"""

import argparse
from datetime import datetime

import rp

STOCK_ORDER = {"High": 0, "Medium": 1, "Low": 2, None: 3}

QUERY = """{
  gpuTypes { id displayName memoryInGb secureCloud securePrice }
  dataCenters { id location storageSupport gpuAvailability { gpuTypeId stockStatus } }
}"""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--vram", type=int, default=24, help="minimum VRAM in GB (default 24)")
    ap.add_argument("--all-regions", action="store_true", help="not only US-/CA- datacenters")
    ap.add_argument("--no-volumes", action="store_true", help="include datacenters without network volumes")
    args = ap.parse_args()

    data = rp.graphql(QUERY)
    where = {}
    for dc in data["dataCenters"]:
        if not args.no_volumes and not dc.get("storageSupport"):
            continue
        if not args.all_regions and not dc["id"].startswith(("US-", "CA-")):
            continue
        for ga in dc.get("gpuAvailability") or []:
            if ga.get("stockStatus"):
                where.setdefault(ga["gpuTypeId"], []).append((dc["id"], ga["stockStatus"], dc.get("storageSupport")))

    rows = []
    for g in data["gpuTypes"]:
        if g.get("secureCloud") and g.get("securePrice") and g.get("memoryInGb", 0) >= args.vram and g["id"] in where:
            rows.append((g["securePrice"] / g["memoryInGb"], g))
    rows.sort(key=lambda r: (r[0], r[1]["securePrice"]))

    print(f"GPUs >= {args.vram}GB, secure cloud, {'all regions' if args.all_regions else 'US/CA'}"
          f"{'' if args.no_volumes else ', network-volume datacenters'}  ({datetime.now():%Y-%m-%d %H:%M})\n")
    print(f"  {'GPU type id':<52} {'VRAM':>5} {'$/hr':>6} {'$/GB':>6}  datacenters (stock)")
    for value, g in rows:
        dcs = sorted(where[g["id"]], key=lambda d: (STOCK_ORDER.get(d[1], 3), d[0]))
        dc_s = "  ".join(f"{d}[{s}]{'' if vol else '*'}" for d, s, vol in dcs)
        print(f"  {g['id']:<52} {g['memoryInGb']:>3}GB {g['securePrice']:>6.2f} {value:>6.3f}  {dc_s}")
    if args.no_volumes:
        print("\n  * = no network volumes there: use pod.py create --pod-volume-gb N")
    print("\n  Use the GPU type id (first column) in GPU_TYPES / --gpu.")


if __name__ == "__main__":
    main()
