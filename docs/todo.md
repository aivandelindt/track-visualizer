# Waveform Comparison Research and Build Tasks

## Goal

Add track-to-track comparison features to the current analyzer and dashboard so users can:

- Compare mastering characteristics.
- Find compatible DJ transitions.
- Rank tracks by spectral/timbral similarity.
- View visual + numeric evidence for each comparison.

## Research Summary (Applied to This Repo)

Current implementation already has:

- `librosa` loading and tempo extraction.
- Key detection and Camelot mapping.
- Energy curve and structure marker detection.
- TinyDB-backed storage/query via `GET /api/tracks`.

Missing for requested comparison scope:

- LUFS and loudness range metrics.
- Multi-band spectral balance metrics (bass/mids/highs).
- MFCC-based similarity pipeline.
- Pairwise comparison endpoint and UI.
- Mastering-oriented warning checks (clipping/compression cues).

Recommended libraries and methods:

- `librosa` for MFCC, spectral centroid, spectral rolloff, beat/tempo, chroma.
- `pyloudnorm` (+ `soundfile`) for integrated LUFS and loudness range (LRA).
- `numpy` + cosine similarity for spectral/timbral comparison.
- Keep TinyDB as primary cached feature store.

## Proposed Feature Tasks (Small and Buildable)

### Phase 0: Data Contract and Safety

- [x] T0.1 Define `comparison_features` JSON schema in `analyze.py` output.
  - Include: `rms_db`, `lufs`, `lra_lu`, `crest_factor_db`, `spectral_centroid_hz`, `bass_ratio`, `mid_ratio`, `high_ratio`, `stereo_width`, `clipping_ratio`, `mfcc_mean`, `mfcc_std`.
  - Acceptance: one analyzed track contains all fields with numeric values or explicit `null`.

- [x] T0.2 Add schema versioning (`analysis_version`) to every track record.
  - Acceptance: dashboard can read records with and without new fields.

- [x] T0.3 Add graceful fallback when optional audio metrics fail per file.
  - Acceptance: analysis continues; track gets `comparison_errors` array instead of hard failure.

### Phase 1: Core Feature Extraction

- [x] T1.1 Add LUFS + LRA extraction function using `pyloudnorm`.
  - Acceptance: returns stable LUFS for test audio and handles silence safely.

- [x] T1.2 Add crest factor metric from peak and RMS.
  - Acceptance: synthetic transient test produces higher crest factor than compressed test signal.

- [x] T1.3 Add spectral balance ratios:
  - Bass: `<100 Hz`
  - Mid: `100 Hz - 8 kHz`
  - High: `>8 kHz`
  - Acceptance: ratios sum close to `1.0` with tolerance.

- [x] T1.4 Add timbre fingerprint fields from MFCC statistics (`mean/std` of first 13 coefficients).
  - Acceptance: fingerprints differ between two clearly different tracks.

- [x] T1.5 Add clipping proxy (`samples near digital full scale`) and transient sharpness proxy.
  - Acceptance: hard-limited sample reports higher clipping ratio than clean sample.

### Phase 2: Similarity Engine

- [x] T2.1 Create server-side feature vector builder and normalization rules.
  - Acceptance: all vectors have fixed length and no NaN values.

- [x] T2.2 Implement weighted similarity score (0-100):
  - Timbre (MFCC cosine)
  - Spectral balance distance
  - Tempo distance
  - Key compatibility bonus
  - Loudness/dynamics distance
  - Acceptance: same-track comparison > 95, unrelated tracks lower.

- [x] T2.3 Add `GET /api/compare?left=<file>&right=<file>` endpoint.
  - Acceptance: response returns per-metric deltas + total score + compatibility tags.

- [x] T2.4 Add `GET /api/similar?file=<file>&limit=10` endpoint.
  - Acceptance: returns top N ranked tracks excluding source track.

### Phase 3: Mastering Review Features

- [x] T3.1 Add mastering thresholds config (`docs` + server constants):
  - Target LUFS around `-14` for streaming.
  - Crest factor warning threshold.
  - Clipping ratio warning threshold.
  - Acceptance: thresholds configurable without changing extraction code.

- [x] T3.2 Implement reference-track comparison mode.
  - Acceptance: response includes pass/warn/fail flags for loudness, dynamic range, and brightness delta.

- [x] T3.3 Add mix/mastering recommendation text generator (short deterministic rules).
  - Acceptance: deterministic output for same metrics input.

### Phase 4: Dashboard UI Tasks

- [x] T4.1 Add compare panel (select track A/B from current library).
  - Acceptance: compare action calls `/api/compare` and renders score.

- [x] T4.2 Add metrics delta table (LUFS, crest, centroid, bass/mid/high, BPM, key).
  - Acceptance: all deltas display with clear units and sign.

- [x] T4.3 Add visual comparison charts:
  - Overlay waveform envelope.
  - Side-by-side spectrum bars (bass/mid/high).
  - Optional MFCC similarity gauge.
  - Acceptance: charts render for any two valid tracks without console errors.

- [x] T4.4 Add “Find similar tracks” action in selected-track deck.
  - Acceptance: top matches list updates and links to track selection.

### Phase 5: DJ Workflow Features

- [ ] T5.1 Add harmonic mixing compatibility classifier from Camelot neighbors.
  - Acceptance: tags include `harmonic`, `energy-shift`, `tempo-risk`.

- [ ] T5.2 Add BPM transition recommendation (`straight mix`, `small nudge`, `risky`).
  - Acceptance: thresholds documented and visible in API output.

- [ ] T5.3 Add playlist seed mode (pick one track, return a progression of compatible tracks).
  - Acceptance: ordered list avoids sharp consecutive energy and BPM jumps.

### Phase 6: Optional ML Extension

- [ ] T6.1 Add offline baseline classifier experiment (not in hot path).
  - Input: extracted features.
  - Output: predicted style/genre confidence.
  - Acceptance: script runs from CLI and writes evaluation summary.

- [ ] T6.2 Gate ML output behind feature flag in API/UI.
  - Acceptance: default behavior unchanged when flag is off.

### Phase 7: Quality, Performance, and Docs

- [ ] T7.1 Add unit tests for new metric functions (synthetic fixtures).
  - Acceptance: deterministic assertions for LUFS, crest, spectrum ratios, clipping proxy.

- [ ] T7.2 Add API tests for `/api/compare` and `/api/similar`.
  - Acceptance: expected shape and sort order verified.

- [ ] T7.3 Add per-file feature cache key (file hash + analysis version).
  - Acceptance: unchanged files skip recomputation.

- [ ] T7.4 Update README with new endpoints, metric meanings, and caveats.
  - Acceptance: user can run compare workflow end-to-end from docs.

## Suggested Build Order (Fastest Value)

1. `T0.x` + `T1.x` (data and extraction)
2. `T2.1` + `T2.2` + `T2.3` (first compare API)
3. `T4.1` + `T4.2` (first UI compare)
4. `T3.x` (mastering feedback)
5. `T2.4` + `T4.4` + `T5.x` (DJ recommendation layer)
6. `T6.x` (optional ML)
7. `T7.x` (hardening)

## Notes and Guardrails

- Keep analysis orchestration in `server.py`; browser should not execute Python.
- Persist new features in TinyDB so query and compare are fast.
- Treat copyright infringement detection as a high-risk legal domain; keep similarity outputs as technical indicators only.
