# Install on Debian / Proxmox

RadioTAK is a **Debian + systemd** appliance. The Raspberry Pi is a packaging choice, not a requirement. Any 64-bit Debian 12/13 (or Raspberry Pi OS) host with USB can run the same installer — including a Proxmox **KVM VM** with the SDR passed through.

This is the path to use when a Pi is CPU-saturated (especially Pi 3/4). SDRTrunk is the hot path; more x86 cores and RAM help more than any RadioTAK setting.

Prefer a **QEMU/KVM virtual machine**, not an LXC container. The SDR module blacklists kernel DVB drivers and opens the dongle with libusb. In a VM that happens in the **guest** kernel. In LXC it hits the **Proxmox host** kernel and USB passthrough is easy to get wrong.

## Requirements

| Item | Recommendation |
|------|----------------|
| Guest OS | Debian 12 (Bookworm) or 13 (Trixie), **amd64** |
| vCPU | 4 or more (`cpu: host`) |
| RAM | 4 GB minimum for a test VM; **8 GB** if SDRTrunk will run here |
| Disk | 32 GB or more |
| Network | Bridged LAN (same VLAN as your TAK Server if you have one) |
| SDR | USB RTL-SDR, Airspy Mini, or HackRF on the **Proxmox host**, passed into the VM |

Architecture must be `x86_64` (or `aarch64` on ARM hosts). `install.sh` rejects 32-bit.

## Create the VM

Example on node `pve` as VMID **700** named **RadioTAK**. Adjust storage, bridge, and IP to match the cluster.

```bash
qm create 700 \
  --name RadioTAK \
  --ostype l26 \
  --machine q35 \
  --cpu host \
  --cores 4 \
  --memory 4096 \
  --scsihw virtio-scsi-pci \
  --net0 virtio,bridge=vmbr0 \
  --agent enabled=1 \
  --onboot 0 \
  --boot order=scsi0
```

Install Debian 12/13 from an ISO, **or** import a cloud image (faster):

```bash
# download once to a storage that allows 'import' or 'iso'
# https://cloud.debian.org/images/cloud/bookworm/latest/debian-12-genericcloud-amd64.qcow2

qm set 700 --scsi0 local-lvm:0,import-from=local:import/debian-12-genericcloud-amd64.qcow2
qm set 700 --ide2 local-lvm:cloudinit
qm set 700 --serial0 socket --vga serial0
qm set 700 --ciuser debian --cipassword --sshkeys /root/radiotak.pub
qm set 700 --ipconfig0 ip=dhcp
qm start 700
```

Give the guest **qemu-guest-agent** (`apt install qemu-guest-agent && systemctl enable --now qemu-guest-agent`) so Proxmox can show the IP.

Debian **genericcloud** images ship `linux-image-cloud-amd64`, which has **no USB host controller**. After first boot:

```bash
sudo apt-get install -y linux-image-amd64 usbutils
sudo apt-get remove -y linux-image-cloud-amd64 linux-image-*-cloud-amd64
sudo reboot
lsusb   # should show the RTL/Airspy after passthrough
```

Debian **genericcloud** images on Q35 name the NIC `ens18` / `enp*`, not `eth0`. Proxmox’s default cloud-init network file still says `eth0`, so the VM can boot with no IP. Match by MAC in a `cicustom` network snippet, or add `net.ifnames=0` on the kernel cmdline, or configure `systemd-networkd` with `[Match] MACAddress=…`.

Use a static address on the TAK VLAN when you already run a TAK Server there (example: ExplorerTAK on `192.168.30.0/24`):

```bash
qm set 700 --net0 virtio,bridge=vmbr30
qm set 700 --ipconfig0 ip=192.168.30.70/24,gw=192.168.30.1
qm set 700 --nameserver 1.1.1.1
```

## USB SDR passthrough

Plug the dongle into the Proxmox host. Confirm it on the host:

```bash
lsusb
# RTL-SDR:  0bda:2838  or  0bda:2832
# Airspy:   1d50:60a1
# HackRF:   1d50:6089
```

Stop the host from claiming RTL sticks as TV tuners **before** passthrough. On the **Proxmox host**:

```bash
cat >/etc/modprobe.d/radiotak-rtl-blacklist.conf <<'EOF'
blacklist dvb_usb_rtl28xxu
blacklist rtl2832_sdr
blacklist rtl2832
blacklist dvb_usb_v2
EOF
for m in dvb_usb_rtl28xxu rtl2832_sdr rtl2832 dvb_usb_v2; do
  rmmod "$m" 2>/dev/null || true
done
update-initramfs -u
```

Pass the device into the VM by **vendor/product ID** (survives unplug/reboot better than a bus port):

```bash
qm set 700 --usb0 host=0bda:2838,usb3=1
# Airspy Mini instead:
# qm set 700 --usb0 host=1d50:60a1,usb3=1
qm reboot 700   # or hot-plug: no reboot required on recent PVE
```

In the Proxmox UI: **VM 700 → Hardware → Add → USB Device → Use USB Vendor/Device ID**.

Inside the guest, `lsusb` must show the stick **before** you install the SDR module. Do not also run SDRTrunk on a Pi against the same dongle.

If the antenna used to sit next to the Pi, keep it there with a short USB extension. Passing the stick into a racked server without moving the antenna will improve CPU and can still make RF worse.

### Why not LXC

An unprivileged Debian CT can run the HTTPS console, but live RF needs:

- Privileged CT or manual `lxc.cgroup2.devices.allow` + `/dev/bus/usb` bind mounts
- DVB blacklist and `rmmod` on the **host**
- libusb seeing `/dev/bus/usb/…` (not a random symlink)

Use LXC only if you know you will never pass a tuner in. For decode tests, use the KVM VM.

## Install RadioTAK in the guest

Same command as the Pi. Debian 12/13 amd64 is enough.

```bash
curl -fsSL https://raw.githubusercontent.com/CopIXus/RadioTAK/main/install.sh | sudo bash
```

Unattended (no TTY):

```bash
sudo RADIOTAK_ADMIN_USER=admin RADIOTAK_ADMIN_PASSWORD='choose-a-long-password' \
  bash -c 'curl -fsSL https://raw.githubusercontent.com/CopIXus/RadioTAK/main/install.sh | bash'
```

The installer:

1. Accepts `x86_64` and installs the Python venv + systemd unit
2. Serves the console on **https://\<guest-ip\>:5001**
3. Does **not** download SDRTrunk until you install **SDR Location Gateway** from Marketplace

The SDR module installer selects `sdr-trunk-linux-x86_64-*.zip` on Intel/AMD (CopIXus fork tag in `modules/sdr_location_gateway/install.sh`).

## After install

1. Open `https://<guest-ip>:5001` (accept the self-signed cert)
2. Log in (or complete first-run setup)
3. Marketplace → install **SDR Location Gateway** (needs the USB stick visible in the guest)
4. **SDR** → Discover, add control-channel MHz, start the decoder
5. Configure TAK Server(s) and the radio allowlist (**Units**)

If the decoder is not installed yet, the console and TAK client still run. JSONL replay works without RF:

```bash
radiotak replay tests/fixtures/p25_motorola_gps.jsonl
```

## Paths and CLI

Same as the Pi appliance:

| Path | Purpose |
|------|---------|
| `/opt/radiotak` | Application (git) |
| `/var/lib/radiotak` | Persistent state |
| `/etc/systemd/system/radiotak.service` | Console service |
| `/etc/systemd/system/sdrtrunk.service` | Decoder (after SDR module) |

```bash
sudo radiotak status
sudo radiotak logs
sudo radiotak update
sudo radiotak reset-password
sudo radiotak diagnostics
```

## Sizing notes

- A Pi 3 (1 GB, Cortex-A53) will peg at 100% on SDRTrunk; that is expected.
- 4 vCPU / 4 GB on x86 is already a large upgrade for **testing**.
- Raise the VM to 8 GB before leaving SDRTrunk on 24/7.
- Host RAM is shared. Do not give the guest 8 GB if the node would swap.

See [HARDWARE.md](HARDWARE.md) for tuner/antenna notes and [INSTALL-RPI.md](INSTALL-RPI.md) for the Pi-shaped install.
