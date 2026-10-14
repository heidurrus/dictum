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


def release_device_memory(device):
    """Give the GPU's cached blocks back. PyTorch's Apple-GPU allocator keeps every block it ever
    handed out; over a thousand batches of different lengths that cache outgrew a 16 GB Mac."""
    import torch
    kind = getattr(device, "type", str(device))
    if kind == "mps" and hasattr(torch, "mps"):
        torch.mps.empty_cache()
    elif kind == "cuda":
        torch.cuda.empty_cache()


def batches_by_length(chunks, batch_size):
    """Indices of the chunks grouped into batches of similar length, longest first: less padding,
    fewer distinct buffer sizes for the allocator. The caller restores the original order."""
    order = sorted(range(len(chunks)), key=lambda i: len(chunks[i]), reverse=True)
    return [order[i:i + batch_size] for i in range(0, len(order), batch_size)]


def transcribe_chunks(model, chunks, batch_size=16, progress=None, word_timestamps=False):
    """Run the model over waveform chunks and return [(text, words)] in the chunks' order."""
    import torch
    from gigaam.utils import AudioDataset
    results = [None] * len(chunks)
    done = 0
    with torch.inference_mode():
        for batch in batches_by_length(chunks, batch_size):
            wav_pad, wav_lens = AudioDataset.collate([chunks[i] for i in batch])
            wav_pad = wav_pad.to(model._device).to(model._dtype)
            wav_lens = wav_lens.to(model._device)
            encoded, encoded_len = model.forward(wav_pad, wav_lens)
            for i, decoded in zip(batch, model._decode(encoded, encoded_len, wav_lens, word_timestamps)):
                results[i] = decoded
            del wav_pad, wav_lens, encoded, encoded_len
            release_device_memory(model._device)
            done += len(batch)
            if progress:
                progress(done, len(chunks))
    from core import usage
    usage.record("asr", seconds=usage.audio_seconds(chunks))   # every pass: files, channels, live windows, whispers
    return results


def transcribe_longform(model, wav_file, progress=None, word_timestamps=False):
    """GigaAM's transcribe_longform with the VAD fed a waveform and the device cache released
    after every batch. Returns [{start, end, text, words}]."""
    from gigaam.preprocess import SAMPLE_RATE
    chunks, bounds = segment_audio_file(wav_file, SAMPLE_RATE, device=model._device)
    if not chunks:
        return []
    out = []
    for (start, end), (text, words) in zip(bounds, transcribe_chunks(model, chunks, progress=progress, word_timestamps=word_timestamps)):
        out.append({"start": round(start, 3), "end": round(end, 3), "text": text,
                    "words": [{"text": w.text, "start": round(w.start + start, 3), "end": round(w.end + start, 3)} for w in (words or [])]})
    return out
