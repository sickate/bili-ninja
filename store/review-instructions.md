# Reviewer testing instructions

1. Use Chrome 116 or newer and open a normal `https://www.bilibili.com/video/BV...` page. A public example is https://www.bilibili.com/video/BV1RANn6bEAW . If that item is unavailable, another playable public BV video can be used.
2. Confirm that the video plays normally in the current browser session, then click the Bili Ninja toolbar icon. The extension uses that existing Bilibili session; there is no Bili Ninja account or developer service to sign into.
3. In the side panel, keep **仅音频** selected and click **导出音频** or **合并并导出音频**. Chrome asks where to save the locally generated M4A. It can also be played in the side panel.
4. Switch to **完整视频**. Select one part and an available resolution. For a small test download, choose 360P if offered. Click **导出完整视频**. The resulting MP4 includes the original H.264 video and AAC audio. No extra program or FFmpeg installation is needed.
5. On a multi-part BV item, audio mode can select multiple parts and joins them in their original order. Video mode exports one selected part per file.
6. The progress view supports cancellation. Keep the original video tab and side panel open during processing. Navigating to another video reloads the relevant panel; unrelated websites have a gray, disabled toolbar icon.

Resolution availability depends on the user's existing Bilibili playback rights. The extension does not bypass preview, paywall, DRM, or geographic restrictions. Website requests retrieve JSON and media bytes only. All executable extension code is included in the submitted package.

The project does not provide or request a reviewer's Bilibili credentials. Normal public-video functionality can be tested with whatever playback access Bilibili makes available to the reviewer's browser. Policy: https://github.com/sickate/bili-ninja/blob/main/PRIVACY.md . Source: https://github.com/sickate/bili-ninja .
