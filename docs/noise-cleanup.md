# Noise cleanup before transcription

Setting "Noise cleanup" (Off / Automatic / Always), default **Automatic** (which asks the user, see below). Everything runs on this PC: the
GTCRN speech denoiser of sherpa-onnx (`models/gtcrn_simple.onnx`, 0.5 MB, downloaded once by
`fetch_models.py` and bundled with the app like the speaker models). Only the transcription hears
the cleaned audio. Speaker separation, voice matching and the playback mp3 use the original.

## Measurements

Two synthetic Turkish recordings (39 s one speaker, 94 s three voices) were mixed with generated
noise, transcribed with faster-whisper large-v3-turbo with and without cleaning, and the text was
compared with the transcript of the clean recording (word error rate, lower is better). Noise
levels are the signal-to-noise ratio in dB. Babble is the same voices overlapped from other parts
of the recording.

Short recording (95 words): WER raw -> cleaned

| noise | 20 dB | 10 dB | 5 dB | 0 dB |
|---|---|---|---|---|
| white | 0.00 -> 0.00 | 0.13 -> 0.13 | 0.14 -> 0.14 | 0.15 -> 0.17 |
| pink | 0.00 -> 0.13 | 0.01 -> 0.13 | 0.13 -> 0.63 | 0.14 -> 0.15 |
| babble | 0.13 -> 0.13 | 0.13 -> 0.13 | 0.28 -> 0.15 | 0.61 -> 0.47 |
| 50 Hz hum | 0.00 -> 0.00 | 0.00 -> 0.13 | 0.00 -> 0.00 | 0.00 -> 0.00 |

Long recording (209 words): WER raw -> cleaned

| noise | 20 dB | 10 dB | 5 dB | 0 dB |
|---|---|---|---|---|
| white | 0.00 -> 0.005 | 0.00 -> 0.005 | 0.024 -> 0.048 | 0.110 -> 0.177 |
| pink | 0.005 -> 0.00 | 0.010 -> 0.005 | 0.014 -> 0.005 | 0.033 -> 0.038 |
| babble | 0.00 -> 0.00 | 0.019 -> 0.033 | 0.081 -> 0.081 | 0.703 -> 0.732 |
| 50 Hz hum | 0.005 -> 0.00 | 0.00 -> 0.00 | 0.00 -> 0.00 | 0.005 -> 0.00 |

Clean recordings cleaned: WER 0.00 (unchanged) on both.

Over all 32 noisy conditions the mean WER was 0.089 without and 0.112 with cleaning (7 better,
13 worse, 12 equal). By noise type (raw -> cleaned): white 0.068 -> 0.083, pink 0.042 -> 0.135,
babble 0.244 -> 0.215, hum 0.001 -> 0.016. The speech model is already robust to stationary noise
and hum; cleaning mostly adds artefacts there. It helped only on the short recording with babble
at 5 and 0 dB and not on the long one. Whole 12-word drops (one sentence) explain the 0.13 steps in
the short recording, so single cells are noisy; the overall picture is what counts.

Speaker separation (3-voice recording, agreement with the separation of the clean recording):
raw noisy audio 0.99-1.00 at white 10/0 dB, pink 5, babble 10, hum 10/0 and 0.53 at babble 5 dB;
cleaned audio 0.97-1.00 and 0.48. Cleaning never helped, so speakers are always found on the original.

## Policy

- Off: nothing changes, no extra time.
- Automatic (default): estimates the speech-to-noise ratio from the energy of 25 ms frames (loud frames vs
  the quietest 10 %; about 0.1 s per minute of audio) and cleans when it is below the threshold (8 dB
  until the user's answers move it). Because cleaning helps some recordings and hurts others, the
  decision is not silent, see "Asking the user".
- Always: cleans every recording.
- A missing model file or an error in the cleaner falls back to the original audio.

## Asking the user (Automatic mode)

Right after conversion, when the estimated SNR is near or below the threshold, a ~12 s excerpt with
speech (the noisiest window that is at least 40 % speech) is cut out, only the excerpt is cleaned
(loudness matched) and both versions are written to the job folder (`ab_original.wav`,
`ab_cleaned.wav`, served by the media virtual host). The app shows a popup with two play buttons
(same excerpt) and "use cleaned" / "use original". Until an answer arrives the job shows "Waiting for
your choice" (pause and cancel work). After 2 minutes without an answer the automatic decision is
used and noted in the job (`noise.choice = "timeout"`) so the queue never stalls. Each file asks.
The excerpt files are deleted after the choice. "Do not ask again" (also a setting) makes the mode
fully automatic with the learned threshold.

Who is asked: recordings within +-3 dB of the threshold (both sides, so answers arrive from both
directions) and noisier ones, except when the last three answers far below the threshold (more than
3 dB) were all "cleaned". Clearly clean recordings are never asked about.

## Learning the threshold

Each answer is stored as (SNR, chose cleaned) in the settings (latest 40). The threshold is the
midpoint between the highest SNR where the user chose cleaned and the lowest SNR where the user chose
original. With answers on one side only it is pushed 1.5 dB past the extreme answer (never back
toward the other side of 8 dB). Few answers move it only partly: weight n/6, full after 6 answers.
Clamped to 0-20 dB. A timeout teaches nothing. Settings show the learned value (read-only) and a
Reset button.

## Speed

About 13 s per minute of audio with 6 threads (real-time factor 0.22; 15 s per minute with 4
threads) on the development PC. The estimate for a Ryzen 5 5625U is the same order or somewhat
slower. The progress box shows "Cleaning background noise" during this step.

## Limits of the test

Synthetic text-to-speech voices and generated noise, two recordings, one speech model. Real
rooms (reverb, cheap microphones, compression, clipping) were not tested.
