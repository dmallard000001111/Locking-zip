"""Build identity, stamped by CI at package time.

For source runs this stays "dev", which the updater treats as "never
self-update" (source users update via git / the LockZip.command launcher). The
CI build job overwrites BUILD_SHA with the real commit SHA right before
PyInstaller freezes the app, so a packaged build knows exactly which commit it
is and can compare against the latest published build.
"""
BUILD_SHA = "dev"
