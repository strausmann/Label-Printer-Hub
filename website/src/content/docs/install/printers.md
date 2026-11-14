---
title: Connecting printers
description: Which printers Labelyard drives, what the network has to allow, and how to add a printer in the web UI.
sidebar:
  label: Printers and hardware
---

Labelyard reaches every printer over the network. USB-only printers are not supported. You add printers in the web UI under **Settings > Printers**, at runtime and without a restart; there are no printer variables.

## Tape printers

Brother PT-Series and QL-Series printers on the network, for example the PT-P750W and the QL-820NWB. The hub prints on TCP port 9100 and reads the printer's status, including the loaded tape or label roll, over SNMP (UDP port 161).

You find a printer's address in your router's DHCP leases, on the printer's own display or web page, or with a scan of your network for the two ports:

```bash
nmap -p 9100,161 192.0.2.0/24 --open
```

Check from the host that runs the hub before you add the printer:

```bash
# printing
nc -zv <printer-address> 9100
# status; the answer names the maker and the model
snmpwalk -v 2c -c public <printer-address> 1.3.6.1.4.1.2435.2.3.9.1.1.7.0
```

If SNMP does not answer, open the printer's own web page and enable SNMPv1/v2c with the community `public` (on many models under **Network > Protocols > SNMP**).

## Page printers

Office printers that speak IPP print label sheets. Add them as **Page printer (IPP)** with their IPP address, for example `ipp://printer.example.invalid:631/ipp/print`. Read the printer once before saving, so the hub knows its trays; then enable the trays you use and choose a default. See [sheets and layouts](/using/sheets/) for what happens next.

## After adding a printer

- **Test print.** Each printer has a test print, so you see at once that the address and the protocol work.
- **Calibrate page printers.** A page printer rarely prints exactly where the page says. Print the calibration page, measure how far it is off, and the hub moves every print on that tray by the opposite.
- **Watch the status.** The printer's page shows its state live: ready, printing, cover open, out of material.

The container needs to reach the printer's network. With the default bridge network that works as long as the host can reach it; if not, check routing and firewalls between the Docker host and the printers.
