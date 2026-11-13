# Chrome Web Store submission materials

Status as of 2026-11-13 (Asia/Shanghai): these are prepared submission materials. No verified public Chrome Web Store listing URL, submission confirmation, or approval is recorded. The website displays the store option as pending; do not substitute the store homepage for a product listing.

The direct website distribution is live at `https://www.instap.net/bili-ninja/`. The main agent's online check on 2026-11-13 passed five pages, 14 resources, and the v1.2.1 ZIP (22,283 bytes; SHA-256 `f35dd3c1542a266057ac3b24e46b4207059c84c10b0dbb8d08f235c9daf5a3ea`). This validates website delivery and package contents, not store submission or all installation/export workflows. Current browser evidence and remaining acceptance work are tracked in [the QA follow-up plan](../docs/qa-followup-plan.md) and [deployment record](../docs/website-deployment.md).

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

The public privacy page is available at `https://www.instap.net/bili-ninja/privacy/` and mirrors `PRIVACY.md`. Recheck it against the submitted build and use the reviewed public URL in the privacy-policy field. Do not put developer account IDs, verification documents, account cookies, or credentials into this directory. Google sign-in, publisher registration, legal agreements, and payments must be handled through the publisher's own account.

Before an authorized store submission:

- Complete the main agent's review of clean-profile installation and real single-part audio, multi-part audio, and MP4 export evidence; distinguish macOS results from pending Windows checks.
- Rebuild the extension-only ZIP, confirm its version and contents, and keep the existing versioned website download byte-for-byte unchanged unless the extension version changes.
- Review listing text, permissions, privacy disclosures, support contact, reviewer instructions, and demonstration screenshot labels against that exact package.
- Have the publisher complete the account-specific submission steps, then record the actual submission/review outcome and public listing URL when available.

No store account operation or channel publication is part of this documentation update.
