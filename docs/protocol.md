# HH_06.03 serial protocol

The application reads UART at 115200 baud, 8N1. Module RX is not needed for
receive-only use. Verify supply voltage and TX signal level against your board's
documentation; a 5 V TX output requires level reduction before reaching the Pi.

Each packet is six bytes:

| Byte | Meaning |
|---|---|
| 0–1 | Header `BB AA` |
| 2 | Command: `00` firmware version, `01` sound level |
| 3–4 | Payload, low byte first for sound level |
| 5 | Sum of bytes 0–4 modulo 256 |

`BB AA 01 7F 02 E7` decodes to `(0x02 * 256 + 0x7F) / 10 = 63.9 dB`.
A startup version record `BB AA 00 02 00 67` identifies firmware 2.0, not a
sound reading. Startup/reconnection may miss this once-only record; a null
firmware value is therefore not itself an error.

The decoder accepts split packets, searches for a new header after invalid
checksums, counts rejected/discarded data and retains at most five incomplete
bytes between calls. No calibration multiplier or peak correction is applied.
The module's additive checksum is a corruption check, not a cryptographic
integrity guarantee; checksum success does not imply acoustic accuracy.

The module specification used by this project claims 40–130 dB and A-weighting;
the protocol reports values in 0.1 dB steps. Internal time weighting and independent accuracy
have not been established for this unit. Below/above-range values remain in raw
telemetry but are not shown as valid current measurements.

The packet interpretation is covered by regression tests including captured
packet examples. Those tests establish decoding behaviour, not acoustic accuracy.
