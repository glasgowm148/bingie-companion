# Bingie Companion

Optional, reusable companions for [Bingie Experience](https://github.com/glasgowm148/skin.bingie).
The skin owns its controls; these packages provide Android voice input, guide navigation and
profile-local widgets. No accounts, channel lists, personal profiles or content providers are bundled.

**0.1.2 beta candidate.** The Kodi companion is separate from the Android app and advanced
coordinator; their versions are listed below. Manual speech-recognition acceptance is still required.

| Package | Use |
| --- | --- |
| `script.bingie.companion` 0.1.2 | On-screen voice action/setup, guide day picker, configurable PVR rows, native profile-screen fallback below Kodi 22, and optional Continue Watching widgets; Kodi 20+ |
| `io.github.glasgowm148.kodivoice` 0.1.1 | Android voice app with private on-TV configuration, Kodi Manager identity check and speech-provider feedback |
| `script.kodi.live.tv` 1.3.1 | Advanced two-profile coordinator extracted from existing code; Android Kodi 22 relaunch requires the reviewed setup described below |

## Install the Kodi companion

1. Install the `script.bingie.companion-0.1.2.zip` release asset (Kodi 20 or later) through Kodi's **Install from zip file**.
2. Install Bingie Experience 2.0.2.16 or later. Existing navigation-helper installations retain priority.
3. Enable only the features you want in **Configure Skin → Experience options** or **Search**.
   Without the companion, normal typed search, Kodi's guide and the skin's standard controls remain.
   Enable the Kodi companion separately in each profile where you want it; other profiles keep
   their existing fallback and voice choices.

See [reference Shield validation](docs/runtime-validation.md) for the tested behavior and the
remaining spoken-recognition acceptance checks.

For channel rows, choose **Choose channel rows** in Experience options. The picker uses the paths
returned by Kodi's local VFS, including the actual group identifier. Cancelling leaves all rows unchanged.
Settings are per Kodi profile. **Family mode** displays only the explicitly chosen rows and hides
unrestricted channel/history rows; missing configuration leaves those rows empty. It is a UI filter,
not a substitute for Kodi profile locks or your PVR client's access controls.

## Voice search

Requirements: Android API 26+, a microphone and installed speech-recognition service, and
[Kodi Manager](https://github.com/glasgowm148/kodi-manager) **0.7.43+** on the same TV, with Kodi
Manager's **Enable writes** turned on (voice search is a write route; with writes off it is refused).
The app verifies Kodi Manager's identity before it sends the token, so older Kodi Manager versions
are refused. A speech provider may need an internet connection. Other platforms keep typed search.

The app stores one token, so voice search works only in the Kodi profile whose Kodi Manager token
was entered; other profiles keep typed search. Entering another profile's token replaces the stored one.

1. Install `kodivoice-0.1.1.apk` on the TV. The public app has its own package ID; it does not replace
   an existing custom voice app or change the system assistant.
2. Open **Kodi voice search setup** on the TV. Enter Kodi Manager's port and token privately there,
   then save. The token stays in the app's private storage; it is not included in backups or logs.
3. In the Kodi companion settings, enable the Android voice helper. In Bingie's Search settings,
   enable **Show voice search button**. Choose **Search by voice** above the search keyboard.
4. Allow the microphone when Android asks. Listening, partial recognition and errors appear in the
   voice overlay; the final words populate Bingie's existing search results through Kodi Manager.
   Cancelling or a recognition failure leaves typed search intact. Starting from the on-screen mic
   never changes your assistant role.

The remote's physical mic button is a separate opt-in: select this app as Android's assistant if
your TV supports that choice. On Shield firmware that only exposes this through ADB, an experienced
owner can use `adb shell cmd role add-role-holder android.app.role.ASSISTANT
io.github.glasgowm148.kodivoice 0`. Record your previous assistant before changing it and restore that
choice to undo. No installer or skin code grants permissions or takes this role automatically.

**Speech privacy:** audio is handled by the selected Android speech provider, commonly Google's
service, and may be transmitted to that provider. Recognized text goes to Kodi Manager on
`127.0.0.1` with bearer authentication. This project does not operate a speech or telemetry service.
Do not put tokens in issue reports, screenshots or chat. The setup screen blocks screenshots.

Existing custom helper packages can be selected in Companion settings. They retain their own setup
procedure. Do not uninstall or replace a working helper during a skin-only upgrade.

## Continue Watching

Add the widget folder:

```text
plugin://script.bingie.companion/?mode=continue
```

In this add-on's settings, configure up to three video-folder URLs from add-ons you already use
(`plugin://` or `videodb://`). Each source must already provide the appropriate Continue Watching
listing. No source is selected automatically. Requests run those add-ons' directory handlers.
Original playback URLs and resume points are retained. Duplicates prefer a resumable item; completed
items without a resume point are omitted. A failed source does not erase another source's results.
If every configured source fails, the directory reports failure rather than caching a false empty list.
Each source's reply is capped at 100 entries. Kodi applies that cap after the source add-on has built
its whole listing, so it limits the reply size, not the source's work or response time.
The add-on never imports another profile's settings or watch history.

## Advanced profile coordinator

`script.kodi.live.tv` is optional and retains the existing helper ID for compatible integrations.
Do not install it over an existing customized helper merely to get voice search; the main companion
does not need it. Back up the existing helper and its add-on data before any deliberate replacement.

Its cooperative profile-switch protocol is reused from the maintained navigation code. Only add-ons
that opt in by shipping `profile_transition.py` in their installed folder are asked to drain and
awaited; a participant's missing acknowledgement cancels the switch. Stock add-ons are neither awaited
nor disabled/re-enabled during recovery; Kodi stops them normally. Before stopping anything, the
relaunch path checks the destination profile, its lock, the launcher token and the helper files.
On the direct path (Kodi 21 and earlier) every enabled PVR client is paused and restored; no
particular PVR add-on is required.
On Android Kodi 22.0-BETA2/RC1 it also requires the separately built, privately configured
[profile-relaunch kit](https://github.com/glasgowm148/nvidia-MCP/tree/main/contrib/profile-relaunch).
No launcher token or helper signing key is shipped here. Locked profiles are refused by the relaunch
path. Other Kodi 22 builds are refused until reviewed; native profile loading is never attempted there.
Playback must be stopped first. The ordinary companion preserves an existing coordinator and otherwise
uses Kodi's native login screen on every Kodi below 22; on Kodi 22 and unrecognised builds it explains
the limitation and cancels.

Provider/account patches, IPTV relay startup checks and reliability diagnostics remain outside these
packages. The guide and day picker work with the PVR client configured by the owner.

## Build and validate

Python 3.9+; no third-party Python packages are needed for unit tests or Kodi ZIP builds:

```sh
python -m unittest discover -s tests -q
python scripts/build.py
```

The Android build also needs a JDK 11+ and Android SDK build-tools 34.0.0 / platform android-30:

```sh
python android/voice-search/build.py --sdk /path/to/android-sdk --java-home /path/to/jdk
```

The day picker offers today plus the number of future days set in Kodi's guide settings
(**Future days to display**, at most seven) and keeps the same local time across daylight-saving changes.

Kodi ZIPs and checksums go into `dist/`; the APK and checksum go into `output/voice-search/`.
The voice app's signing key is generated outside the repository in
`~/.local/share/bingie-companion/signing/`. Keep it privately for future signed updates.
CI-generated APKs use disposable keys and are compile checks, not release updates.
The advanced coordinator's client DEX and Java/shell sources are included; its matching Android
server and build procedure live in the linked relaunch kit.

MIT license. Extracted and generalized from locally maintained Kodi navigation/voice code by
glasgowm148. The Bingie skin remains separately GPL v2 licensed with its upstream attribution.
