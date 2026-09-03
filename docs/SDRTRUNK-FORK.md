# SDRTrunk fork for RadioTAK

Upstream: https://github.com/DSheirer/sdrtrunk

Create / update the CopIXus fork:

```bash
gh repo fork DSheirer/sdrtrunk --org CopIXus --clone=false
```

Then add `GeoEventJsonExporter` + optional `DftFrameExporter` as described in
[integrations/sdrtrunk/README.md](../integrations/sdrtrunk/README.md).

GitHub Actions should build `sdr-trunk-linux-aarch64-*.zip` on tag push so the
SDR Location Gateway installer can prefer the patched release.
