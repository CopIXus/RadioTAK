# Hardware

## Preferred build

| Item | Recommendation |
|------|----------------|
| Computer | Raspberry Pi 5, 8 GB |
| Cooling | Active Cooler |
| Power | Official 27W USB-C |
| Storage | 256–512 GB NVMe + M.2 HAT (or high-endurance microSD) |
| Network | Gigabit Ethernet |
| SDR | Airspy Mini (preferred) or RTL2832/R820T2 |
| Antenna | Band-specific for the monitored system |

## Notes

- SDRTrunk prefers 8 GB RAM on ARM64.
- Trunked systems spanning >~2–3 MHz may need multiple RTL-SDRs or a wider-band receiver.
- Continuous decode is CPU-bound — cooling matters.
- A Pi 3/4 will saturate on decode. For more CPU, run the same stack on Debian amd64 (mini PC or [Proxmox KVM + USB passthrough](INSTALL-DEBIAN-PROXMOX.md)). The installer already selects the x86_64 SDRTrunk build.
