# Vendored streaming server

`scrcpy-server-v5.0.1` is the unmodified Android server from
[Genymobile/scrcpy](https://github.com/Genymobile/scrcpy) release 5.0.1.

- Source: https://github.com/Genymobile/scrcpy/releases/tag/v5.0.1
- SHA-256: `764EB6F79811D5211FE9DF341120882BA9994C7A61B897D7BF3FB662E53BC536`
- License: Apache License 2.0, see `LICENSE-scrcpy.txt`

The desktop application pushes this file to the connected device temporarily and
launches it to encode the screen as H.264. The stream is decoded locally and
served to the browser as a low-latency, length-prefixed JPEG stream.
