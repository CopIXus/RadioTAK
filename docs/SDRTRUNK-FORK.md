# SDRTrunk fork for RadioTAK

Upstream: https://github.com/DSheirer/sdrtrunk

The CopIXus fork lives at https://github.com/CopIXus/sdrtrunk and adds two isolated exporters:

- `GeoEventJsonExporter` — `PlottableDecodeEvent` GPS as NDJSON to `127.0.0.1:29500`
- `DftFrameExporter` — downsampled DFT bins as NDJSON to `127.0.0.1:29501`

Source for those classes (GPLv3) is kept in [integrations/sdrtrunk/patch/](../integrations/sdrtrunk/patch/) and applied on the `radiotak-exporters` branch of the fork.

## Release

GitHub Actions on the fork (`.github/workflows/radiotak-release.yml`) builds `sdr-trunk-linux-aarch64-*.zip` on tag push. RadioTAK's SDR installer prefers:

```
https://github.com/CopIXus/sdrtrunk/releases/download/v0.6.2-radiotak.2/sdr-trunk-linux-aarch64-v0.6.2-radiotak.2.zip
```

and falls back to upstream `v0.6.1` if that asset is not published yet.

`TAG=` in `modules/sdr_location_gateway/install.sh` is the single source of truth. `modules/sdr_location_gateway/sdrtrunk/build.py` reads it to decide whether an installed decoder is behind; RadioTAK then upgrades automatically on startup / System → Update, or from the **Upgrade decoder** button on the SDR page. Bumping the tag in `install.sh` is therefore all that is needed to roll a new fork build out to every RadioTAK install.

To publish a new patched build:

```bash
git clone https://github.com/CopIXus/sdrtrunk.git
git checkout radiotak-exporters
git tag v0.6.2-radiotak.2
git push origin radiotak-exporters
git push origin v0.6.2-radiotak.2
```
