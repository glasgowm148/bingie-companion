# Changes

## 0.1.0 beta candidate — 2026-10-16

- Extract Android voice input into a separate app ID, with private on-TV configuration.
- Add optional voice/setup actions, guide navigation and a channel-group picker using Kodi paths.
- Add provider-neutral, profile-local Continue Watching sources with resume-preserving deduplication.
- Extract the advanced navigation/profile coordinator without household transport configuration;
  refuse unreviewed Kodi 22 switching and locked-profile relaunches.
- Preserve existing helper precedence; do not replace a working TV installation automatically.
- Add fake-Kodi tests, deterministic Kodi packages and an Android compile check.
