#!/usr/bin/env python3
"""The project's persistent RunPod Pod and its network volumes.

    pod.py status                       the pod (by POD_NAME), its URLs and image
    pod.py create [--image TAG]         create it: DATACENTERS x GPU_TYPES in order until one has stock
    pod.py update --image TAG           roll a running pod onto a new image tag (PATCH)
    pod.py recreate [--image TAG]       delete + create (to change GPU, datacenter or volume)
    pod.py stop | start                 stop keeps the pod (and its pod volume); you pay for disk only
    pod.py delete --yes                 delete the pod (network volumes stay)
    pod.py volumes                      list network volumes
    pod.py create-volume DC [--suffix S]   create VOLUME_NAME-<suffix> (default: dc suffix) of VOLUME_GB

Defaults come from project.conf. Every create/update sends the whole env list
(RunPod replaces it on update), always including POD_AUTH from AUTH_FILE, so a
rollout can't bring ComfyUI back up without its password; --no-auth to skip.

REST (rest.runpod.io/v1) first; where REST's schema rejects a datacenter or GPU
type (it has lagged behind), GraphQL podFindAndDeployOnDemand.
"""

import argparse
import sys

import rp


def find_pod(name):
    for p in rp.rest("GET", "/pods", params={"name": name}) or []:
        if p.get("name") == name:
            return p
    return None


def find_volume(dc, prefix):
    """The volume in dc whose name is prefix or starts with it (exact name first)."""
    vols = [v for v in rp.rest("GET", "/networkvolumes") if v.get("dataCenterId") == dc
            and v.get("name", "").startswith(prefix)]
    vols.sort(key=lambda v: v["name"] != prefix)
    return vols[0] if vols else None


def default_tag():
    import subprocess
    try:
        sha = subprocess.run(["git", "-C", str(rp.ROOT), "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        sys.exit("ERROR: no --image and no git sha to derive it from")
    return f"{rp.conf('IMAGE')}:{sha}"


def ports():
    out = ["8188/http", "22/tcp"]
    if rp.conf("APP_PORT"):
        out.insert(1, f"{rp.conf('APP_PORT')}/http")
    return out


def pod_env(args):
    env = {"PROJECT": rp.conf("PROJECT")}
    if not args.no_auth:
        auth = rp.pod_auth()
        if not auth:
            sys.exit(f"ERROR: no password: put user:password in {rp.conf('AUTH_FILE')} (mode 600) or set POD_AUTH. "
                     "RunPod's proxy URLs are public; --no-auth to run without one anyway.")
        env["POD_AUTH"] = auth
    for item in args.env:
        if "=" not in item:
            sys.exit(f"ERROR: --env {item!r} is not KEY=VALUE")
        k, v = item.split("=", 1)
        env[k] = v
    return env


def cuda_filter(args, image):
    """cu130 images need driver >= 580 (CUDA 13.0 hosts). cu128 images run on older drivers
    too, and cheap hosts often report no CUDA version at all, so they get no filter."""
    if args.allowed_cuda_versions is not None:
        return [v.strip() for v in args.allowed_cuda_versions.split(",") if v.strip()]
    return [] if image.endswith("-cu128") else ["13.0"]


def body_for(args, image, gpu, dc, volume_id):
    body = {
        "name": rp.conf("POD_NAME"), "imageName": image, "cloudType": "SECURE",
        "gpuTypeIds": [gpu], "gpuCount": 1, "dataCenterIds": [dc], "dataCenterPriority": "custom",
        "volumeInGb": 0 if volume_id else args.pod_volume_gb, "volumeMountPath": "/workspace",
        "containerDiskInGb": int(rp.conf("CONTAINER_DISK_GB", "40")), "ports": ports(), "env": pod_env(args),
    }
    if volume_id:
        body["networkVolumeId"] = volume_id
    cuda = cuda_filter(args, image)
    if cuda:
        body["allowedCudaVersions"] = cuda
    return body


def create_graphql(body):
    inp = {"cloudType": "SECURE", "gpuCount": 1, "gpuTypeId": body["gpuTypeIds"][0],
           "dataCenterId": body["dataCenterIds"][0], "volumeInGb": body["volumeInGb"],
           "volumeMountPath": body["volumeMountPath"], "containerDiskInGb": body["containerDiskInGb"],
           "imageName": body["imageName"], "name": body["name"], "ports": ",".join(body["ports"]),
           "env": [{"key": k, "value": v} for k, v in body["env"].items()]}
    for k in ("networkVolumeId", "allowedCudaVersions"):
        if k in body:
            inp[k] = body[k]
    data = rp.graphql("mutation($input: PodFindAndDeployOnDemandInput) "
                      "{ podFindAndDeployOnDemand(input: $input) { id name } }", {"input": inp})
    pod = data.get("podFindAndDeployOnDemand")
    if not pod or not pod.get("id"):
        raise rp.ApiError("GraphQL: no pod returned")
    return pod


def create(args):
    image = args.image or default_tag()
    dcs = args.datacenter.split(",") if args.datacenter else rp.conf_list("DATACENTERS")
    gpus = args.gpu.split(",") if args.gpu else rp.conf_list("GPU_TYPES")
    if not dcs or not gpus:
        sys.exit("ERROR: no DATACENTERS / GPU_TYPES (project.conf, or --datacenter / --gpu)")
    for dc in (d.strip() for d in dcs):
        if args.pod_volume_gb:
            vol = None
        else:
            vol = find_volume(dc, rp.conf("VOLUME_NAME"))
            if not vol:
                print(f"  {dc}: no volume named {rp.conf('VOLUME_NAME')}*, skipping")
                continue
        for gpu in (g.strip() for g in gpus):
            body = body_for(args, image, gpu, dc, vol and vol["id"])
            try:
                pod = rp.rest("POST", "/pods", body=body)
            except rp.ApiError as e:
                pod, msg = None, str(e)
                if e.status == 400 and "enum" in msg:   # REST's schema doesn't know this DC/GPU yet
                    try:
                        pod = create_graphql(body)
                    except rp.ApiError as e2:
                        msg = str(e2)
                if not pod:
                    print(f"  {dc} / {gpu}: {msg.strip()[:200]}")
                    continue
            where = f"volume {vol['name']} ({vol['id']})" if vol else f"pod volume {args.pod_volume_gb}GB"
            print(f"Created {pod.get('name', body['name'])} ({pod['id']}): {gpu} in {dc}, {where}, {image}")
            print_urls(pod["id"])
            print("First boot pulls the image and fetches missing models; watch the pod's logs in the console.")
            return
    sys.exit("ERROR: no pod could be created with those datacenters and GPUs (tools/gpus.py shows stock)")


def print_urls(pod_id):
    print(f"  ComfyUI: {rp.proxy_url(pod_id)}")
    if rp.conf("APP_PORT"):
        print(f"  App:     {rp.proxy_url(pod_id, int(rp.conf('APP_PORT')))}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["status", "create", "update", "recreate", "stop", "start", "delete",
                                        "volumes", "create-volume"])
    ap.add_argument("dc", nargs="?", help="datacenter (create-volume)")
    ap.add_argument("--image", help="image:tag (default: IMAGE:<git short sha>)")
    ap.add_argument("--datacenter", help="comma list, overrides DATACENTERS")
    ap.add_argument("--gpu", help="comma list, overrides GPU_TYPES")
    ap.add_argument("--pod-volume-gb", type=int, default=0,
                    help="no network volume: a pod volume of this size (any datacenter; lost when the pod is deleted)")
    ap.add_argument("--allowed-cuda-versions", help="comma list; '' for any (default: 13.0, or any for *-cu128)")
    ap.add_argument("--env", action="append", default=[], metavar="KEY=VALUE", help="extra pod env (repeatable)")
    ap.add_argument("--no-auth", action="store_true", help="no POD_AUTH (ComfyUI open on a public URL)")
    ap.add_argument("--suffix", help="create-volume: name suffix (default: the datacenter's, e.g. ks for US-KS-2)")
    ap.add_argument("--yes", action="store_true", help="confirm delete")
    args = ap.parse_args()

    if args.command == "volumes":
        for v in rp.rest("GET", "/networkvolumes"):
            print(f"  {v['id']}  {v['dataCenterId']:<10} {v['size']:>5}GB  {v['name']}")
        return
    if args.command == "create-volume":
        if not args.dc:
            sys.exit("usage: pod.py create-volume DC [--suffix S]")
        name = f"{rp.conf('VOLUME_NAME')}-{args.suffix or args.dc.split('-')[1].lower()}"
        v = rp.rest("POST", "/networkvolumes", body={"name": name, "size": int(rp.conf("VOLUME_GB", "30")),
                                                      "dataCenterId": args.dc})
        print(f"Created volume {v['name']} ({v['id']}), {v['size']}GB in {v['dataCenterId']}. "
              "Encryption can only be chosen in the console.")
        return

    name = rp.conf("POD_NAME")
    pod = find_pod(name)
    if args.command == "status":
        if not pod:
            print(f"No pod named {name}.")
            return
        print(f"{name} ({pod['id']}): {pod.get('desiredStatus')}, {pod.get('imageName')}, "
              f"${pod.get('costPerHr', '?')}/hr")
        print_urls(pod["id"])
    elif args.command == "create":
        if pod:
            sys.exit(f"{name} exists ({pod['id']}, {pod.get('desiredStatus')}): use update or recreate")
        create(args)
    elif args.command == "recreate":
        if pod:
            print(f"Deleting {name} ({pod['id']})")
            rp.rest("DELETE", f"/pods/{pod['id']}")
        create(args)
    elif not pod:
        sys.exit(f"No pod named {name}.")
    elif args.command == "update":
        if not args.image:
            sys.exit("update needs --image (a tag, never :latest: RunPod may keep running the old image)")
        body = {"imageName": args.image, "env": pod_env(args), "ports": ports(),
                "containerDiskInGb": int(rp.conf("CONTAINER_DISK_GB", "40"))}
        rp.rest("PATCH", f"/pods/{pod['id']}", body=body)
        print(f"Updated {name} ({pod['id']}) to {args.image}; it restarts on the new image."
              + (" It is stopped: start it." if pod.get("desiredStatus") != "RUNNING" else ""))
    elif args.command in ("stop", "start"):
        rp.rest("POST", f"/pods/{pod['id']}/{args.command}")
        print(f"{args.command}: {name} ({pod['id']})")
    elif args.command == "delete":
        if not args.yes:
            sys.exit(f"This deletes {name} ({pod['id']}) and its pod volume, if any; pass --yes.")
        rp.rest("DELETE", f"/pods/{pod['id']}")
        print(f"Deleted {name} ({pod['id']}).")


if __name__ == "__main__":
    try:
        main()
    except rp.ApiError as e:
        sys.exit(f"ERROR: {e}")
