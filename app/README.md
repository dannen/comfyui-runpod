# Optional app

A second web app that runs next to ComfyUI on the pod (a viewer, an editor, a
small API), behind the same password. Leave this folder with only this README
for none.

- `install.sh` (optional) runs at image build time. Install into **its own venv**
  (`python3 -m venv /opt/app/venv`) so the app's numpy/OpenCV/etc. pins can't
  change ComfyUI's.
- `run.sh` (executable) is started by `start.sh` in a restart loop, with:
  - `APP_HOST`, `APP_LISTEN_PORT`: where to listen. With a password set, that is
    `127.0.0.1:<APP_PORT + 10000>` and nginx serves `APP_PORT` with basic auth;
    without one, `0.0.0.0:APP_PORT`.
  - `VOLUME_ROOT` (`/workspace`): read ComfyUI's results from `output/`, keep
    the app's own state in its own folder on the volume.
  - Its log goes to `/tmp/app.log`.
- Set `APP_PORT` in `project.conf`: `build.sh` bakes it in, `tools/pod.py` opens
  it on the pod and `run-local.sh` maps it.
- Treat everything under `/workspace` as untrusted input: ComfyUI's uploads and
  any workflow's saves land there. Check sizes and types before decoding, and
  never unpickle.
