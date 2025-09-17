# Raspberry Pi Local Bilingual Voice Assistant （树莓派本地中英双语语音助手）

A local, privacy-friendly voice assistant for Raspberry Pi that **listens and speaks in both Chinese and English**, runs **fully offline** after first-time setup, and supports **USB microphone + Bluetooth/analog speaker** via PipeWire.  
一个运行在树莓派上的本地语音助手：**能同时识别并回答中英文**，首轮部署后可**离线运行**，通过 PipeWire 支持 **USB 麦克风 + 蓝牙/有线音箱**。

## ✨ Features | 功能特性
- **Bilingual ASR + TTS**: multi-lingual Whisper for speech-to-text; English + Chinese TTS pipelines with automatic voice selection.  
  **中英同听同说**：多语种 Whisper 识别；中/英双 TTS 管线，自动按内容切换音色。
- **Streaming reply**: LLM streams tokens; sentences are detected and **spoken while text is still generating**.  
  **边出字边出声**：LLM 流式输出，按句切分后即时播报。
- **Robust audio I/O**: PipeWire capture/playback with adaptive VAD and fallback combos.  
  **稳健音频链路**：PipeWire 录放音，带自适应 VAD 与多组合回退。
- **Offline-friendly**: Works without internet once models/voices are cached.  
  **离线友好**：模型与语音包缓存后可纯离线。
- **Local LLM via Ollama**: small & fast by default; swappable with larger models.  
  **本地 LLM（Ollama）**：默认小而快，可按需更换更强模型。

## 🧰 Hardware | 硬件需求
- Raspberry Pi 4/5 with Debian/Raspberry Pi OS  
- USB microphone  
- Bluetooth speaker or 3.5mm analog speaker

## 📦 Software | 软件依赖
- PipeWire / WirePlumber / BlueZ  
- Python 3.10+ (venv recommended)  
- Ollama (local LLM service)  
- Python packages: `faster-whisper`, `kokoro`, `ollama`, `numpy`, `ordered-set`, `jieba`, `pypinyin`（详见 `requirements.txt`）

## 🚀 Quick Start | 快速开始

### 1) System packages & services | 安装系统包并启用服务
```bash
sudo apt update
sudo apt install -y \
  git python3-venv python3-pip \
  bluez \
  pipewire pipewire-pulse wireplumber \
  alsa-utils libspa-0.2-bluetooth

sudo systemctl enable --now bluetooth
systemctl --user enable --now pipewire wireplumber pipewire-pulse
sudo loginctl enable-linger $USER
