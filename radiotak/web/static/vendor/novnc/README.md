# noVNC (optional zero-patch SDRTrunk GUI)

When the CopIXus SDRTrunk fork is not providing FFT frames, RadioTAK can embed
the native SDRTrunk JavaFX UI that already runs under Xvfb.

## Setup (on the Pi)

```bash
sudo apt-get install -y x11vnc
# Display number must match the sdrtrunk.service Xvfb display (often :99)
x11vnc -display :99 -localhost -forever -shared -rfbport 5901 &
```

Point Settings / SDR noVNC URL at a same-origin path (e.g. `/novnc/`) after
installing noVNC static assets here, or reverse-proxy websockify behind the
RadioTAK HTTPS console so the iframe stays authenticated.

Never expose VNC/websockify without the RadioTAK login session.

Vendored noVNC files (optional) go in this directory when operators enable the fallback.
