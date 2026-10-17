# Changes

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
