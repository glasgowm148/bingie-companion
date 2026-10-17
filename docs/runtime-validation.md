# Reference Shield beta validation

Date: 2026-10-17. Kodi 22.0-RC1, Bingie Experience 2.0.2.16, Kodi companion 0.1.1,
Android voice app 0.1.0. The pre-existing navigation coordinator and Android assistant were
retained. A verified stopped-Kodi backup preceded installation. Device settings, logs, screenshots,
credentials and profile data are private and are not included in this repository.

Observed on the reference TV:

- Stock search remains available with the companion disabled. The optional microphone appears
  when enabled, can be reached from the keyboard, and launches Android's microphone permission prompt.
- Cancelling that prompt preserves the search text and leaves the original assistant unchanged.
- A comma-containing query reaches Bingie's existing search view through Kodi Manager. This tests
  the search API and UI; it does not establish speech recognition.
- The skin's setup action opens the Android configuration activity through its resolved launcher.
- The channel-row picker reads actual local VFS groups. Cancelling after the first choice preserves
  all saved rows. The normal TV guide opens.
- The Continue Watching plugin returns an empty directory without configured sources, and runs
  with an explicitly configured library source. Provider resume/deduplication edge cases are covered
  by the unit tests; a third-party provider history merge was not exercised on the TV.
- Both existing profiles retain their channel configuration and family-mode choices through the
  existing coordinator's restart path. The extracted advanced coordinator 1.3.0 was not installed
  over that working helper; its validation remains source/fake-Kodi based.
- An adult-only source and voice opt-in were absent from the other profile. The newly installed
  companion was disabled there by default; it was temporarily enabled to verify its unconfigured
  Continue Watching directory was empty, then returned to its previous disabled state.
- A local video passed play, pause, resume, OSD opening, Back from the OSD retaining pause, and
  Back from fullscreen stopping playback. The test video and temporary source/search data were
  removed, and the starting profile was restored on Home.

Still requires a human with the remote: spoken recognition, partial/final words, recognition timeout,
physical microphone behavior and delivery from recognized speech. Microphone access was cancelled
in the permission-path test. The new app does not automatically take the assistant role or grant itself
permissions. Kodi 21 and other Kodi 22 builds were not validated on this device.

Automated validation remains separate: 47 Python tests, deterministic Kodi ZIPs, and an Android
SDK compile/signature check. See the workflow results for each exact revision.
