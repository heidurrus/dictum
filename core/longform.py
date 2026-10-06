"""Long recordings (over ~25 s) are cut into chunks by pyannote's voice activity detection before GigaAM
transcribes them. GigaAM hands pyannote the file *path*, and pyannote then decodes it with torchcodec,
which torchaudio 2.9+ requires and which fails without FFmpeg's shared libraries. We already decode
audio through our own ffmpeg (gigaam.preprocess.load_audio), so hand pyannote the waveform instead."""
from typing import List, Tuple


def segment_waveform(audio, sad_segments, sr, max_duration=22.0, min_duration=15.0,
                     strict_limit_duration=30.0, new_chunk_threshold=0.2) -> Tuple[list, List[Tuple[float, float]]]:
    """GigaAM's chunking rules, given the speech segments: chunks of 15–22 s, hard-split over 30 s."""
    segments = []
    boundaries: List[Tuple[float, float]] = []
    curr_duration = curr_start = curr_end = 0.0

    def flush(curr_start, curr_end, curr_duration):
        if curr_duration > strict_limit_duration:
            max_segments = int(curr_duration / strict_limit_duration) + 1
            segment_duration = curr_duration / max_segments
            curr_end = curr_start + segment_duration
            for _ in range(max_segments - 1):
                segments.append(audio[int(curr_start * sr):int(curr_end * sr)])
                boundaries.append((curr_start, curr_end))
                curr_start = curr_end
                curr_end += segment_duration
        segments.append(audio[int(curr_start * sr):int(curr_end * sr)])
        boundaries.append((curr_start, curr_end))

    for segment in sad_segments.get_timeline().support():
        start = max(0, segment.start)
        end = min(len(audio) / sr, segment.end)
        if curr_duration == 0.0:
            curr_start = start
        elif curr_duration > new_chunk_threshold and (
                curr_duration + (end - curr_end) > max_duration or curr_duration > min_duration):
            flush(curr_start, curr_end, curr_duration)
            curr_start = start
        curr_end = end
        curr_duration = curr_end - curr_start
    if curr_duration > new_chunk_threshold:
        flush(curr_start, curr_end, curr_duration)
    return segments, boundaries


def segment_audio_file(wav_file, sr, device="cpu", **kwargs):
    """Drop-in for gigaam.vad_utils.segment_audio_file that never asks pyannote to open the file."""
    import gigaam.vad_utils as vu
    if isinstance(device, str):
        import torch
        device = torch.device(device)
    audio = vu.load_audio(wav_file)
    pipeline = vu.get_pipeline(device)
    speech = pipeline({"waveform": audio.unsqueeze(0).float().cpu(), "sample_rate": sr})
    return segment_waveform(audio, speech, sr, **kwargs)


def install():
    """Replace GigaAM's version; transcribe_longform looks the function up at call time."""
    try:
        import gigaam.vad_utils as vu
    except Exception:          # pyannote missing: longform is unavailable anyway
        return False
    vu.segment_audio_file = segment_audio_file
    return True
