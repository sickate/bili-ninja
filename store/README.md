# Chrome Web Store submission materials

- `listing-zh-CN.md`: store text, single-purpose statement, permissions explanations, and data-handling notes.
- `review-instructions.md`: review steps that require no developer credentials.
- `assets/icon-128.png`: 128 × 128 store icon.
- `assets/promo-440x280.png`: original small promotional tile.
- `assets/screenshot-audio-1280x800.png`: audio workflow with the actual extension UI and generated demonstration media.
- `assets/screenshot-video-1280x800.png`: video workflow with the actual extension UI and generated demonstration media.
- `../PRIVACY.md`: public privacy policy; no account information or authentication values are included.

Create the upload ZIP with `npm run package`. Only `extension/` is packaged; store materials, test harnesses, recordings, downloaded media, credentials, and local account settings are excluded.

The screenshots are explicitly labeled as demonstrations using generated test media. They do not contain a personal Bilibili account, real browsing history, signed download URLs, or Google developer-account details.

`python3 store/generate-promo.py` recreates the promotional image with `rsvg-convert`. Run `node tests/preview-server.mjs` and visit `/store.html?mode=audio` or `/store.html?mode=video` to display the screenshot composition. The `/capture.html` form writes JPEG captures only into the ignored `artifacts/chrome-web-store/` directory on localhost. Its code is not part of the extension.

Publish or update `PRIVACY.md` before submitting for review, and use its public GitHub URL in the privacy-policy field. Do not put developer account IDs, verification documents, account cookies, or credentials into this directory. Google sign-in, publisher registration, legal agreements, and payments must be handled through the publisher's own account.
