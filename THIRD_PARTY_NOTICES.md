# Third-party licenses and model terms

This inventory covers the direct dependencies pinned for AudioRegistry 0.1.0.
It is an engineering review, not legal advice. Transitive packages and system
components remain governed by their own distributions.

| Component | Pinned version | License / terms |
| --- | ---: | --- |
| Python | 3.12.10 | PSF License |
| PyTorch | 2.8.0 | BSD-3-Clause |
| TorchAudio | 2.8.0 | BSD |
| TorchCodec | 0.7.0 | BSD-3-Clause |
| pyannote.audio | 4.0.7 | MIT |
| faster-whisper | 1.2.1 | MIT |
| CTranslate2 | 4.7.1 | MIT |
| PyYAML | 6.0.2 | MIT |
| tqdm | 4.70.0 | MPL-2.0 AND MIT |
| Rich | 15.0.0 | MIT |
| OpenCC Python reimplementation | 0.1.7 | Apache-2.0 |
| NumPy | 2.5.2 | BSD-3-Clause |

Model weights are not part of this repository:

- `Systran/faster-whisper-large-v3` is marked MIT on its model card and is a
  CTranslate2 conversion of OpenAI Whisper large-v3.
- `pyannote/speaker-diarization-community-1` is CC-BY-4.0, requires accepting
  gated access terms, and requires attribution when redistributed or used as
  required by that license.

`setup.ps1` downloads the official signed Python 3.12.10 Windows installer and the
pinned BtbN FFmpeg 7.1 Windows x64 LGPL shared build
from its original GitHub release into the ignored `.runtime/` directory and verifies
SHA-256. The binary is not stored or redistributed in this repository. NVIDIA CUDA
is installed separately. Before distributing a bundled application, audit the exact
FFmpeg build configuration and NVIDIA terms again.

Sources checked on 2026-09-22:

- https://www.python.org/downloads/release/python-31210/
- https://huggingface.co/Systran/faster-whisper-large-v3
- https://huggingface.co/pyannote/speaker-diarization-community-1
- https://github.com/pyannote/pyannote-audio/blob/develop/LICENSE
- https://github.com/meta-pytorch/torchcodec/blob/main/LICENSE
- https://github.com/pytorch/audio
- https://github.com/BtbN/FFmpeg-Builds/releases/tag/autobuild-2026-07-31-14-10
- Installed Python package metadata for every pinned direct dependency
