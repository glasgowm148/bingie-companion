# Changes

## 0.1.3 beta candidate — 2026-10-23

- Continue Watching rejects empty source routes and malformed directory responses without losing a healthy source. Invalid episode identifiers no longer crash row deduplication.
- Document offline tests and deterministic package verification.

## 0.1.2 beta candidate — 2026-10-17

Kodi companion `script.bingie.companion` 0.1.2:

- Require Kodi 20 (`xbmc.python` 3.0.1): Continue Watching uses `InfoTagVideo` setters that Kodi 19
  does not have.
- Continue Watching always ends its directory exactly once, reporting failure if a listing error
  occurs part-way through instead of leaving Kodi waiting.
- Day picker offers only today plus Kodi's **Future days to display** guide setting (default 3,
  at most 7), restores the "Today • " / "Tomorrow • " labels and moves to the same local time on
  the chosen day across daylight-saving changes (23 or 25 hours, not always 24).
- Clarify that the 100-entry `limits` on each source caps only the reply size: Kodi applies it after
  the source add-on has built its whole listing. No behaviour change.
- README: the native profile-screen fallback applies to every Kodi below 22, not just Kodi 21.

Advanced coordinator `script.kodi.live.tv` 1.3.1:

- Only add-ons that opt in by shipping `profile_transition.py` are awaited during the shutdown drain
  and restarted during recovery. Stock add-ons no longer make every switch wait 20 seconds and fail,
  and are no longer disabled and re-enabled.
- The Kodi 21 direct switch pauses whichever PVR clients are enabled (any `kodi.pvrclient`) instead
  of requiring IPTV Simple; without one it skips the Live TV barrier. Older journals still restore
  IPTV Simple.
- Check the destination profile, profile lock, launcher token and relaunch helper files before
  returning Home, starting the transition or asking any service to stop (switch and restart-current).
- Direct-switch recovery logs a failed remote-control restore and restarts each drained service
  independently.
- Guarded relaunch: with helper 1.3 (nvidia-MCP `contrib/profile-relaunch`), arm a late reopen
  (`ARMWATCH`) with the readiness lease. If Android kills Kodi during shutdown (low memory), Kodi
  comes back about 75 seconds later instead of leaving the launcher on screen; if the relaunch
  script outlives Kodi it reopens it at once instead of cancelling. Older helpers are unaffected.
- Remove the `browse-bbc-show` and `mark-bbc-watched` modes, which need a privately patched iPlayer
  add-on.

Android voice app `io.github.glasgowm148.kodivoice` 0.1.1:

- Verify Kodi Manager's identity before sending the token; Kodi Manager 0.7.43+ is required.
- Harden the assistant entry point.
- Document that voice search needs Kodi Manager's **Enable writes** and works in the one Kodi profile
  whose token was entered.

## 0.1.1 beta candidate — 2026-10-17

- Read actual PVR group directories through local VFS. Kodi's JSON-RPC directory endpoint refuses
  the `pvr://` scheme, even when called by an add-on.
- Open Android setup through Kodi's resolved launcher component; implicit MAIN intents can fail
  because launcher filters do not include CATEGORY_DEFAULT.
- Android voice app remains 0.1.0; advanced coordinator remains 1.3.0.

## 0.1.0 beta candidate — 2026-10-16

- Extract Android voice input into a separate app ID, with private on-TV configuration.
- Add optional voice/setup actions, guide navigation and a channel-group picker using Kodi paths.
- Add provider-neutral, profile-local Continue Watching sources with resume-preserving deduplication.
- Extract the advanced navigation/profile coordinator without household transport configuration;
  refuse unreviewed Kodi 22 switching and locked-profile relaunches.
- Preserve existing helper precedence; do not replace a working TV installation automatically.
- Add fake-Kodi tests, deterministic Kodi packages and an Android compile check.
