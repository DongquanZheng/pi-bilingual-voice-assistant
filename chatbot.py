#!/usr/bin/env python3
"""
Voice Chatbot (USB Mic + Bluetooth/Analog Speaker) — TTS Tensor-safe + PipeWire

Fixes:
- TTS: handle PyTorch Tensors from Kokoro by converting to NumPy before int16.
- Use tts_pipeline.sample_rate if available (fallback 24000).
- pw-cat uses format "s16" (correct token).
- VAD uses float RMS (no int16 overflow).
- Auto-fallback capture configs if mic rejects 16k/mono.

Run:
  python3 chatbot.py
  python3 chatbot.py --mic-target <source-id-or-name>
  MIC_TARGET=<source-id-or-name> python3 chatbot.py
  python3 chatbot.py --test
"""

import sys
import os
os.environ["HF_HUB_DISABLE_XET"] = "1"
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
import signal
import time
import subprocess
import wave
import numpy as np
from pathlib import Path
import re
import ollama
from kokoro import KPipeline
from faster_whisper import WhisperModel

# Optional GPIO stop button
try:
    from gpiozero import Button
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False
    print("📝 GPIO not available - running without button support")

# ===== Configuration =====
STOP_BUTTON_PIN = 22

# Preferred capture settings (we’ll auto-fallback if device refuses)
PREF_SAMPLE_RATE = 16000
PREF_CHANNELS = 1

# VAD settings
FRAME_MS = 30
SILENCE_THRESHOLD = 120   # Base RMS
END_SILENCE_MS = 800
MIN_SPEECH_MS = 300
MAX_RECORDING_MS = 15000

# Models
WHISPER_MODEL = "tiny"
COMPUTE_TYPE = "int8"
WHISPER_CPU_THREADS = 4
LLM_MODEL = "gemma3:270m"
TTS_VOICE = "af_heart"
TTS_VOICE_ZH = "zf_xiaoxiao"
CHINESE_VOICES = ["zf_xiaobei", "zf_xiaoxiao", "zf_xiaoyi", "zf_xiaoni"]
TTS_SPEED = 1.1

# Conversation
AUTO_RESTART_DELAY = 1.5
WAKE_WORDS = ["hey computer", "okay computer", "hey assistant"]

# Temp file
TEMP_WAV = Path("/tmp/recording.wav")

# Optional: force a specific PipeWire source (id or name)
MIC_TARGET = os.environ.get("MIC_TARGET")

# ===== Init =====
def init_models():
    # ① Forbid XET
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
    os.environ["HF_HUB_DISABLE_XET"] = "1"

    print("🚀 Starting Voice Chatbot...")
    print("📦 Loading models (this may take a moment the first time)...")

    print("  Loading Whisper...")
    whisper = WhisperModel(
        WHISPER_MODEL,
        device="cpu",
        compute_type=COMPUTE_TYPE,
        cpu_threads=4,
        download_root=str(Path.home() / ".cache" / "whisper")
    )

    print("  Loading Kokoro TTS (en/zh)...")
    tts_en = KPipeline(lang_code='e')
    tts_zh = KPipeline(lang_code='z')
    tts = {"en": tts_en, "zh": tts_zh}

    print("  Checking Ollama...")
    try:
        ollama.list()
    except Exception:
        print("❌ Ollama not running! Start it with: sudo systemctl enable --now ollama")
        sys.exit(1)

    print("✅ All models loaded successfully!\n")
    # Preheat Whisper: avoid the first sentence lag
    _ = list(whisper.transcribe(np.zeros(16000, dtype=np.float32), beam_size=1))
    print("  Whisper warm-up done")
    return whisper, tts

def init_button():
    if not GPIO_AVAILABLE:
        return None
    try:
        btn = Button(STOP_BUTTON_PIN, pull_up=True, bounce_time=0.1)
        print("🔘 Stop button ready on GPIO 22")
        return btn
    except Exception:
        print("⚠️  GPIO pins not accessible")
        return None

# ===== Helpers =====
def check_stop(stop_button):
    return bool(stop_button and stop_button.is_pressed)

def _spawn_pw_cat_record(rate, channels, target):
    cmd = [
        "pw-cat", "--record", "-",
        "--format", "s16",
        "--rate", str(rate),
        "--channels", str(channels)
    ]
    if target:
        cmd += ["--target", str(target)]
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

def _select_record_pipeline(target):
    """
    Try a few (rate,channels) combos so we don't crash if the device
    refuses 16k mono. Returns (proc, rate, channels, first_chunk or None, err_text).
    """
    attempts = [
        (PREF_SAMPLE_RATE, PREF_CHANNELS),  # 16k / mono
        (PREF_SAMPLE_RATE, 2),              # 16k / stereo
        (48000, PREF_CHANNELS),             # 48k / mono
        (48000, 2),                         # 48k / stereo
    ]
    for rate, ch in attempts:
        proc = _spawn_pw_cat_record(rate, ch, target)
        bytes_per_sample = 2
        frame_bytes = int(rate * FRAME_MS / 1000) * bytes_per_sample * ch
        chunk = proc.stdout.read(frame_bytes)
        if chunk:
            return proc, rate, ch, chunk, ""
        err = (proc.stderr.read() or b"").decode("utf-8", errors="ignore")
        try:
            proc.terminate(); proc.wait(timeout=0.5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        if err.strip():
            print(f"   ⚠️  pw-cat refused {rate}Hz/{ch}ch: {err.strip()}")
        else:
            print(f"   ⚠️  pw-cat produced no data at {rate}Hz/{ch}ch, retrying...")
    return None, None, None, None, "No working pw-cat configuration found"

def record_with_vad(timeout_seconds=30, stop_button=None):
    """Record audio until silence is detected (VAD). Returns (bytes, rate, channels) or (None, None, None)."""
    print("🎤 Listening... (speak now)")
    if MIC_TARGET:
        print(f"   🎯 Using source target: {MIC_TARGET}")

    proc, rate, ch, first_chunk, err = _select_record_pipeline(MIC_TARGET)
    if not proc:
        print(f"❌ {err}")
        return None, None, None

    bytes_per_sample = 2
    frame_bytes = int(rate * FRAME_MS / 1000) * bytes_per_sample * ch
    audio_buffer = bytearray()

    try:
        # Quick calibration (~300ms)
        noise_samples = []
        if first_chunk:
            s = np.frombuffer(first_chunk, dtype=np.int16).astype(np.float32)
            noise_samples.append(float(np.sqrt(np.mean(s * s))))
        for _ in range(9):
            chunk = proc.stdout.read(frame_bytes)
            if chunk:
                s = np.frombuffer(chunk, dtype=np.int16).astype(np.float32)
                noise_samples.append(float(np.sqrt(np.mean(s * s))))
        noise_floor = float(np.median(noise_samples)) if noise_samples else 50.0
        threshold = max(SILENCE_THRESHOLD, noise_floor * 1.8)
        print(f"   📏 Noise floor: {noise_floor:.1f}  |  Threshold: {threshold:.1f}")

        is_speaking = False
        silence_ms = 0
        speech_ms = 0
        total_ms = 0
        start = time.time()

        if first_chunk is not None:
            samples = np.frombuffer(first_chunk, dtype=np.int16).astype(np.float32)
            rms = float(np.sqrt(np.mean(samples * samples)))
            level = int(rms / 100)
            print(f"\r  Level: {'▁'*min(level,20):<20} ", end="", flush=True)
            if rms > threshold:
                is_speaking = True
                speech_ms = FRAME_MS
                audio_buffer.extend(first_chunk)

        while True:
            if check_stop(stop_button):
                raise KeyboardInterrupt

            if (time.time() - start) > timeout_seconds:
                if not is_speaking:
                    return None, None, None
                break

            chunk = proc.stdout.read(frame_bytes)
            if not chunk:
                err = (proc.stderr.read() or b"").decode("utf-8", errors="ignore").strip()
                if err:
                    print(f"\n❗ pw-cat: {err}")
                break

            samples = np.frombuffer(chunk, dtype=np.int16).astype(np.float32)
            rms = float(np.sqrt(np.mean(samples * samples)))
            level = int(rms / 100)
            print(f"\r  Level: {'▁'*min(level,20):<20} ", end="", flush=True)

            if is_speaking:
                audio_buffer.extend(chunk)
                if rms < threshold:
                    silence_ms += FRAME_MS
                else:
                    silence_ms = 0
                    speech_ms += FRAME_MS

                if silence_ms >= END_SILENCE_MS and speech_ms >= MIN_SPEECH_MS:
                    dur_s = len(audio_buffer) / (rate * bytes_per_sample * ch)
                    print(f"\n  ✓ Recorded {dur_s:.1f}s")
                    break
                elif total_ms >= MAX_RECORDING_MS:
                    print("\n  ✓ Max recording length")
                    break
            else:
                if rms > threshold:
                    is_speaking = True
                    speech_ms = FRAME_MS
                    silence_ms = 0
                    audio_buffer.extend(chunk)
                    print("\n  💬 Speech detected!")

            total_ms += FRAME_MS

    except KeyboardInterrupt:
        print("\n  ⏹️  Recording stopped")
        audio_buffer = None
    finally:
        try:
            proc.terminate(); proc.wait(timeout=0.8)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    if audio_buffer and len(audio_buffer) > 1000:
        return bytes(audio_buffer), rate, ch
    return None, None, None

def save_wav(audio_data, filepath, sample_rate, channels):
    with wave.open(str(filepath), 'wb') as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(audio_data)

def transcribe_audio(whisper_model, audio_path):
    print("🧠 Transcribing...")
    try:
        segments, info = whisper_model.transcribe(
            str(audio_path),
            language=None,
            beam_size=1,
            best_of=1,
            temperature=0.0,
            vad_filter=True,
            vad_parameters=dict(
                min_silence_duration_ms=500,
                speech_pad_ms=200
            )
        )
        text = " ".join(seg.text.strip() for seg in segments)
        return text.strip() if text else None
    except Exception as e:
        print(f"❌ Transcription error: {e}")
        return None

def generate_response(user_text: str) -> str:
    print("💭 Thinking...")

    # Minimalist language determination: More stable judgment of the 'primary language'
    zh_count = len(re.findall(r'[\u4e00-\u9fff]', user_text or ""))
    en_count = len(re.findall(r'[A-Za-z]', user_text or ""))
    target_lang = "zh" if zh_count >= max(3, en_count) else "en"

    if target_lang == "zh":
        sys_prompt = (
            "你是一个语音助手。务必用中文回答，直接给结论，"
            "不要重复或改写用户的问题；若信息不足，只问一个最关键的澄清问题。"
            "每次回答不超过两句。"
        )
    else:
        sys_prompt = (
            "You are a voice assistant. Reply strictly in English. "
            "Do not repeat the user's question; answer directly. "
            "If info is missing, ask ONE short clarifying question. Max 2 sentences."
        )

    try:
        resp = ollama.chat(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_text}
            ],
            options={
                "temperature": 0.6,
                "top_p": 0.9,
                "num_predict": 80,
                "stop": ["\n\n", "User:", "Assistant:"]
            }
        )
        text = (resp["message"]["content"] or "").strip()

        if target_lang == "zh" and not re.search(r'[\u4e00-\u9fff]', text):
            resp2 = ollama.chat(
                model=LLM_MODEL,
                messages=[
                    {"role": "system", "content": "把下面内容翻译成自然、地道的中文，不要添加其他说明。"},
                    {"role": "user", "content": text or "N/A"}
                ],
                options={"temperature": 0.3, "num_predict": 80}
            )
            text = (resp2["message"]["content"] or "").strip()

        return text or "好的。"
    except Exception as e:
        print(f"❌ LLM Error: {e}")
        return "抱歉，我这边处理出了点问题。"

# ---- TTS utils (Tensor-safe) ----
def _to_numpy_audio(audio):
    """Convert various audio containers (torch.Tensor, list, np.ndarray) to 1-D float32 NumPy array."""
    try:
        import torch  # only for isinstance check; safe if not installed
        if isinstance(audio, torch.Tensor):
            audio = audio.detach().cpu().float().numpy()
    except Exception:
        # torch not present or conversion failed; fall through
        pass
    audio = np.asarray(audio, dtype=np.float32)
    if audio.ndim > 1:
        audio = np.squeeze(audio)
    return audio

def _lang_is_zh(text: str) -> bool:
    """比“是否包含中文”更稳：看中英字符占比，避免因为一个中文标点就触发中文语音。"""
    if not text:
        return False
    zh = len(re.findall(r'[\u4e00-\u9fff]', text))
    en = len(re.findall(r'[A-Za-z]', text))
    return zh >= 3 and zh * 1.2 >= en  # 至少3个汉字，且不明显少于英文字母

def _clean_for_tts(text: str) -> str:
    if not text:
        return text
    s = text

    # 1) Continuous punctuation → Single
    s = re.sub(r'([。！？?!])\1+', r'\1', s)

    # 2) Remove the extra spaces between Chinese characters
    s = re.sub(r'([\u4e00-\u9fff])\s+([\u4e00-\u9fff])', r'\1\2', s)

    # 3) English repeated words (stutter)
    s = re.sub(r'\b(\w{1,10})\s+\1\b', r'\1', s, flags=re.I)

    # 4) Chinese double characters (>=3) reduced to 2, allowing for natural '看看' or '试试'
    s = re.sub(r'([\u4e00-\u9fff])\1{2,}', r'\1\1', s)

    return s.strip()


def _contains_cjk(text: str) -> bool:
    return bool(re.search(r'[\u4e00-\u9fff]', text or ""))

def speak_text(tts, text):
    print("🔊 Speaking...")
    try:
        # cleaning
        text = _clean_for_tts(text)

        # Use a more stable ratio to determine Chinese/English: avoiding reading English with a Chinese tone
        is_zh = _lang_is_zh(text)
        pipe = tts["zh"] if is_zh else tts["en"]

        # Sampling rate
        sr = int(getattr(pipe, "sample_rate", 24000) or 24000)

        # Generate voice: Chinese with candidate fallback; English fixed
        if is_zh:
            gen = None
            candidates = [TTS_VOICE_ZH] + [v for v in CHINESE_VOICES if v != TTS_VOICE_ZH]
            for v in candidates:
                try:
                    gen = pipe(text, voice=v, speed=TTS_SPEED)
                    print(f"🗣️ Using Chinese voice: {v}")
                    break
                except Exception as e:
                    if "404" in str(e) or "Entry Not Found" in str(e):
                        print(f"⚠️ Voice '{v}' not available, trying next...")
                        continue
                    raise
            if gen is None:
                raise RuntimeError(f"No usable Chinese voice. Tried: {', '.join(candidates)}")
        else:
            gen = pipe(text, voice=TTS_VOICE, speed=TTS_SPEED)

        # ✅ A phrase opens only once pw-cat, cyclically writing: avoid the sensation of 'repetition/jitter'
        play_cmd = ["pw-cat", "--playback", "-", "--format", "s16", "--rate", str(sr), "--channels", "1"]
        proc = subprocess.Popen(play_cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)

        for _, _, audio in gen:
            audio_np = _to_numpy_audio(audio)
            pcm16 = (np.clip(audio_np, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes()
            try:
                proc.stdin.write(pcm16)
            except Exception:
                break

        try:
            proc.stdin.close()
        except Exception:
            pass
        _, stderr = proc.communicate()
        if proc.returncode != 0:
            err = (stderr or b"").decode("utf-8", errors="ignore").strip()
            if err:
                print(f"❗ pw-cat playback: {err}")

    except Exception as e:
        print(f"❌ TTS Error: {e}")

def record_fixed_seconds(seconds=3, stop_button=None):
    print(f"🎙️  Recording ~{seconds}s for test...")
    if MIC_TARGET:
        print(f"   🎯 Using source target: {MIC_TARGET}")

    proc, rate, ch, first_chunk, err = _select_record_pipeline(MIC_TARGET)
    if not proc:
        print(f"❌ {err}")
        return None, None, None

    bytes_per_sample = 2
    frame_bytes = int(rate * FRAME_MS / 1000) * bytes_per_sample * ch
    total_frames = int((seconds * 1000) / FRAME_MS)
    buf = bytearray()
    if first_chunk:
        buf.extend(first_chunk)

    try:
        for _ in range(total_frames - (1 if first_chunk else 0)):
            if check_stop(stop_button):
                break
            chunk = proc.stdout.read(frame_bytes)
            if not chunk:
                err = (proc.stderr.read() or b"").decode("utf-8", errors="ignore").strip()
                if err:
                    print(f"❗ pw-cat: {err}")
                break
            buf.extend(chunk)
    finally:
        try:
            proc.terminate(); proc.wait(timeout=0.8)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    return (bytes(buf), rate, ch) if buf else (None, None, None)

# ===== Main =====
def main():
    global MIC_TARGET
    args = sys.argv[1:]
    if "--mic-target" in args:
        try:
            MIC_TARGET = args[args.index("--mic-target") + 1]
        except Exception:
            print("⚠️  Usage: --mic-target <source-id-or-name>")

    def shutdown_handler(sig, frame):
        print("\n\n👋 Shutting down...")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    if len(args) > 0:
        if args[0] == "--help":
            print("Voice Chatbot - USB Mic + Bluetooth/Analog Speaker")
            print("\nUsage: python3 chatbot.py [--mic-target <id-or-name>] [--test]")
            print("  --mic-target   Force a specific PipeWire source (from `wpctl status`)")
            print("  --test         Record ~3s and play back (quick audio sanity check)")
            sys.exit(0)
        elif args[0] == "--test" or "--test" in args:
            stop_button = init_button()
            data, rate, ch = record_fixed_seconds(seconds=3, stop_button=stop_button)
            if not data:
                print("❌ No audio captured during test.")
                sys.exit(1)
            out = Path("/tmp/test.wav")
            save_wav(data, out, sample_rate=rate, channels=ch)
            print("▶️  Playing back test recording...")
            subprocess.run(["aplay", str(out)], check=False)
            print("✅ Audio test complete!")
            sys.exit(0)

    whisper_model, tts = init_models()
    stop_button = init_button()

    print("\n" + "="*50)
    print("🤖 VOICE CHATBOT READY!")
    print("="*50)
    print("Setup:")
    print("  • Microphone: USB (PipeWire default source)")
    print("  • Speaker: Bluetooth or 3.5mm (PipeWire default sink)")
    print(f"  • Stop: {'GPIO 22 button or Ctrl+C' if stop_button else 'Press Ctrl+C'}")
    if MIC_TARGET:
        print(f"  • Mic target override: {MIC_TARGET}")
    print("\nListening for speech...\n")

    while True:
        try:
            if check_stop(stop_button):
                print("\n⏹️  Stop button pressed")
                break

            audio_data, rate, ch = record_with_vad(timeout_seconds=30, stop_button=stop_button)

            if audio_data:
                save_wav(audio_data, TEMP_WAV, sample_rate=rate, channels=ch)
                user_text = transcribe_audio(whisper_model, TEMP_WAV)

                if user_text:
                    print(f"📝 You said: \"{user_text}\"")
                    if any(w in user_text.lower() for w in ["goodbye", "bye", "stop", "exit", "quit", "shut down", "turn off"]):
                        speak_text(tts, "Goodbye!")
                        break

                    reply = generate_response(user_text)
                    print(f"🤖 Assistant: \"{reply}\"\n")
                    speak_text(tts, reply)

                    print(f"⏳ Ready again in {AUTO_RESTART_DELAY}s...")
                    time.sleep(AUTO_RESTART_DELAY)
                    print("🎤 Listening...\n")
                else:
                    print("❓ No speech detected in the captured audio\n")
            else:
                print("💤 No speech detected, still listening...\n")
                time.sleep(0.5)

        except KeyboardInterrupt:
            print("\n\n⌨️  Interrupted by user")
            break
        except Exception as e:
            print(f"\n❌ Error: {e}")
            print("Restarting in 3 seconds...\n")
            time.sleep(3)

    print("\n👋 Goodbye!")
    print("="*50)

if __name__ == "__main__":
    main()
