# Why Windows warns when I install Sea Lyon Media Manager

When you double-click `SeaLyonMediaManager-1.0.0-Setup.exe`, Windows
SmartScreen probably stopped you with a blue **"Windows protected your
PC"** dialog:

> Microsoft Defender SmartScreen prevented an unrecognised app from
> starting. Running this app might put your PC at risk.

**This is expected for Sea Lyon Media Manager 1.0** and does **not**
mean the installer is malicious.

## TL;DR — how to install

1. Click **More info** in the SmartScreen dialog.
2. Click **Run anyway**.
3. Accept the standard User Account Control (UAC) prompt.
4. Proceed through the installer normally.

If you want to verify the download before proceeding, compute the
SHA-256 hash and compare against the `SHA256SUMS.txt` file shipped
alongside the installer:

```pwsh
Get-FileHash -Algorithm SHA256 SeaLyonMediaManager-1.0.0-Setup.exe
```

The hash must match the entry in
`SeaLyonMediaManager-1.0.0-SHA256SUMS.txt` exactly. If it does not,
**do not run the installer** — re-download from the
[official GitHub Releases page](https://github.com/DrShoctopus/Sea-Lyon-Media-Manager/releases)
and try again.

## Why does this happen?

Windows shows the "protected your PC" warning when an executable is
**unsigned** — i.e. it has no Authenticode certificate from a trusted
vendor identifying who built it. SmartScreen also factors in the
file's **reputation**: how many people have already downloaded and
run that exact binary without flagging it as harmful.

Sea Lyon Media Manager 1.0 is unsigned because Authenticode code-signing
certificates cost between roughly $200 and $700 per year, plus
hardware-token shipping for EV certificates. For an indie project at
v1.0 we deliberately chose to ship the first public release without a
certificate and ask users to verify the SHA-256 hash instead. **A
signed build is planned for v1.1**.

## Is the installer safe?

Yes — to the same extent any open-source project can claim that:

1. **The source is public.** Every line of code that ships in the
   installer is in this repository on `LMM-MASTER`. You can read or
   build it yourself.
2. **The installer is built by GitHub Actions**, not by a developer's
   workstation. See `.github/workflows/windows-build.yml` — the same
   public workflow file every user can audit produces the binary.
3. **Bundled binaries are SHA-256-pinned** against upstream checksums
   (ffmpeg, VLC, libdiscid, fpcalc). The build aborts if any download
   doesn't match its expected hash.
4. **Tests must pass.** The build pipeline runs the full pytest suite
   and refuses to package if any test fails or the collected count
   drops.
5. **No telemetry.** The app does not phone home. See
   [`PRIVACY.md`](../PRIVACY.md) for the full outbound endpoint list.

## What does SmartScreen actually check?

SmartScreen evaluates downloaded executables against Microsoft's
reputation database. For a brand-new unsigned binary like our 1.0
installer:

- It has no signature, so no vendor trust score.
- It has zero reputation (no other Windows users have run this exact
  binary yet).
- That combination triggers the blue warning by default.

As more users run the same installer without issues, SmartScreen's
reputation score for the binary improves and the warning will appear
less often — but reputation does not transfer between releases.

## What about anti-virus software?

Some anti-virus products may flag the installer as "potentially
unwanted" purely because it is unsigned. If your AV blocks it, the
correct next step is:

1. Verify the SHA-256 hash, as above.
2. Submit a **false-positive sample** to your AV vendor via their
   normal channel.
3. Add an exception for the installer if you trust the source.

If you find a real virus, security issue, or evidence of tampering,
please report it through the GitHub issue tracker or contact channel
on the project page. We take it seriously.

## What's the long-term plan?

For v1.1 we plan to:

1. Purchase an **OV (Organization Validation) Authenticode certificate**
   (~$300–700/yr). OV is the budget option; SmartScreen reputation will
   still need to build up over a few weeks of installs.
2. Optionally upgrade to an **EV (Extended Validation) certificate** if
   the project grows. EV certificates carry instant SmartScreen
   reputation but require a hardware USB token, raising the cost and
   procurement friction.
3. Sign every installer + every binary inside the installer (`.exe`,
   `.dll`).
4. Continue publishing SHA-256 manifests so even after signing, users
   can independently verify what they downloaded.

## Frequently asked questions

**Q: I clicked "Don't run" by accident. Now there's no install.**
A: SmartScreen will warn again on the next double-click. There is no
"this build is permanently blocked" state on a per-user basis.

**Q: My corporate laptop is locked down and SmartScreen has no "Run
anyway" option.**
A: Your IT department has enabled SmartScreen in *enforce* mode and
you cannot bypass it. Either ask IT for an exception, or run Sea Lyon
from source (see [`docs/BUILD.md`](BUILD.md)).

**Q: The portable zip is also unsigned. Does it have the same problem?**
A: Yes, but Windows is less aggressive about unsigned executables that
were not installed via a SmartScreen-monitored installer download. The
portable zip is the recommended path for users who don't want to deal
with SmartScreen at all.

**Q: Will I get the same warning when the auto-updater downloads a
future release?**
A: The in-app updater does not download or run anything itself; it
only opens the installer URL in your default browser. You'll see the
same SmartScreen prompt for each new unsigned installer. Once we ship
a signed 1.1 build, the warning should stop.

## See also

- [`README.md`](../README.md) — main project README.
- [`PRIVACY.md`](../PRIVACY.md) — what the app does and does not send
  over the network.
- [`THIRD_PARTY_NOTICES.txt`](../THIRD_PARTY_NOTICES.txt) — bundled
  dependency licenses.
- [`docs/BUILD.md`](BUILD.md) — running from source on a developer
  machine.
