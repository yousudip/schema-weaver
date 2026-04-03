Local Sandbox Container

Purpose:
- Minimal container image for running untrusted data-processing scripts locally.

Build:
- `docker build -t gdc-sandbox:local ./backend/sandbox`

Notes:
- The container runs as a non-root user.
- Network egress should be disabled at run time.
- Resource limits should be applied at run time.
- Example run (no network, limited CPU/RAM):
  - `docker run --rm --network none --cpus=1 --memory=512m -v "%CD%\\storage:/sandbox/data" gdc-sandbox:local`
