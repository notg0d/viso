# Third-party components

These notices apply to the identified upstream components. This repository does not currently declare a project-wide license; the upstream MIT text below is not a license grant for all Viso code.

## Recognition models

The model downloader uses OpenCV Zoo revision `48b10fa505aeb51fbd127fc60a5c660040e823b7`. Exact model sizes and SHA-256 hashes are in `models/manifest.json`.

| Component | Upstream license | Source |
|---|---|---|
| YuNet `face_detection_yunet_2023mar.onnx` | MIT | [OpenCV Zoo / YuNet](https://github.com/opencv/opencv_zoo/tree/48b10fa505aeb51fbd127fc60a5c660040e823b7/models/face_detection_yunet) |
| SFace `face_recognition_sface_2021dec.onnx` | Apache-2.0 | [OpenCV Zoo / SFace](https://github.com/opencv/opencv_zoo/tree/48b10fa505aeb51fbd127fc60a5c660040e823b7/models/face_recognition_sface) |

Setup downloads each upstream directory's full license into `models/licenses/` alongside the models. Preserve those notices when distributing the models.

MediaPipe Face Landmarker uses the versioned `face_landmarker/float16/1/face_landmarker.task` bundle from Google (Apache-2.0), SHA-256 `64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff`. It contains face detection, 478-point landmark, and blendshape prediction models. Its versioned download URL and license source are in `models/manifest.json`; [task documentation and model cards](https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker/index#models) describe its intended use and limitations.

## Libraries

- React / React DOM — MIT; historical `experiments/browser/` only.
- Vite / TypeScript and their build dependencies — historical browser package; see installed package license files.
- Lucide icons — ISC; historical browser package.
- OpenCV — Apache-2.0; Python wheel distributions include their license notices.
- NumPy — BSD-3-Clause.
- The desktop release and optional Windows sign-in runtime include the installed CPython interpreter and standard library — Python Software Foundation License; its `LICENSE` file is copied into the private runtime. Dependency `.dist-info` and model license files are retained in the payload. The exact Python/dependency versions are recorded in the packaged `runtime/packages.json` (and desktop `RELEASE.json`).
- MediaPipe — Apache-2.0; pinned Python package 0.10.32. Its transitive dependency notices are included in the installed packages. Later prebuilt SDK releases add usage telemetry ([upstream discussion](https://github.com/google-ai-edge/mediapipe/issues/6291)); reassess this before upgrading the pin.

## Glance enrollment animation

`desktop/Viso/EnrollmentRing.cs` and the earlier `experiments/browser/src/EnrollmentGuide.tsx` / `experiments/browser/src/styles.css` adapt the ring, turn-band, and directional-light behavior from [jonnyoo/glance](https://github.com/jonnyoo/glance), revision `b97f521397ec1197ba17768ba797cae1e628848d`:

- `glance/Onboarding/EnrollmentRingView.swift`
- `glance/Onboarding/EnrollmentDirectionSweep.swift`
- `glance/Onboarding/EnrollmentSweepWindowController.swift`

The native WPF theme also takes design inspiration from `GlanceTheme.swift` and `SettingsWindowView.swift`: dark surfaces, blue enrollment accents, focused prompts, and a floating bottom navigation bar. The current native adaptation uses two eight-direction circuits; the historical browser adaptation retains five-pose guidance. Progress is engine-driven in both designs. Glance branding assets and model weights are not bundled.

MIT License

Copyright (c) 2026 Jonathan Zhou

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
