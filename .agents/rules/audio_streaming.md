# Audio Streaming & FFmpeg Rules

## CRITICAL RULE: NO FFMPEG AUDIO FILTERS
- NEVER add `-filter:a`, `silenceremove`, or any dynamic FFmpeg audio filter to `FFMPEG_OPTIONS`.
- Discord Voice Gateway requires raw, untouched 48,000Hz 16-bit stereo PCM audio packets arriving at exact 20ms intervals.
- Adding FFmpeg audio filters (like `silenceremove`) alters Presentation Time Stamps (PTS), causes packet skips, buffer underruns, and makes audio sound rushed/accelerated or robotic.
- Always keep `FFMPEG_OPTIONS` strictly as:
  ```python
  FFMPEG_OPTIONS = {
      'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
      'options': '-vn',
  }
  ```

## YouTube and SoundCloud Source Handling
- Always prioritize extracting clean audio streams directly using updated `yt-dlp` `player_client` definitions (`['android_vr', 'android', 'web', 'tvhtml5', 'mweb', 'ios']`).
- Docker container MUST have `nodejs` installed so `yt-dlp` can solve YouTube JavaScript challenges without triggering `Sign in to confirm you're not a bot`.
- Never alter the original track speed or tempo.
