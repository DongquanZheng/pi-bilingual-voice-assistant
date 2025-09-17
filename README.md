# Raspberry Pi Local Bilingual Voice Assistant （树莓派本地中英双语语音助手）

A local, privacy-friendly voice assistant for Raspberry Pi that **listens and speaks in both Chinese and English**, runs **fully offline** after first-time setup, and supports **USB microphone + Bluetooth/analog speaker** via PipeWire.  
一个运行在树莓派上的本地语音助手：**能同时识别并回答中英文**，首轮部署后可**离线运行**，通过 PipeWire 支持 **USB 麦克风 + 蓝牙/有线音箱**。

## ✨ Features | 功能特性
- **Bilingual ASR + TTS**: multi-lingual Whisper for speech-to-text; English + Chinese TTS pipelines with automatic voice selection.  
  **中英同听同说**：多语种 Whisper 识别；中/英双 TTS 管线，自动按内容切换音色。
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

1) System packages & services | 安装系统包并启用服务
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

2) Bluetooth speaker (optional) | 配对蓝牙音箱（可选）
在 bluetoothctl 完成 pair/trust/connect；用 wpctl status 查找 Sink ID 并设为默认；用 pw-play 测试输出。

3) Project setup | 项目创建
mkdir -p ~/voice-chatbot && cd ~/voice-chatbot
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

4) Install Ollama & a local model | 安装 Ollama 与本地模型
curl -fsSL https://ollama.com/install.sh | sh
sudo systemctl enable --now ollama
ollama pull gemma3:270m          # 默认演示模型；可换更强模型
ollama run gemma3:270m "hello"

5) Configure audio & run | 配置音频并启动
用 wpctl status 找到 USB 麦克风 Source ID（如 66）
启动：
MIC_TARGET=66 python3 chatbot.py

⚙️ Configuration | 配置

环境变量：

MIC_TARGET：指定采集源 ID/名称（wpctl status）

HF_HUB_OFFLINE=1：强制离线

WHISPER_COMPUTE_TYPE=int8，WHISPER_CPU_THREADS=4

TTS_VOICE_ZH=zf_xiaoxiao：中文首选音色（缺失将自动回退）

LLM_MODEL=gemma3:270m：Ollama 模型名

命令行参数：

--mic-target <id-or-name>，--test

🧠 How it works | 工作流

Capture：PipeWire 录音，VAD 截段

ASR：Faster-Whisper 多语识别，低延迟参数

LLM：本地 Ollama，提示词强制跟随用户语言、不复述问题

TTS：Kokoro 中/英两套管线；按句队列播报，整句单次播放以避免叠字

🛠️ Troubleshooting & Tips | 故障排查

无声/设备不对：wpctl status 查看默认 Sink/Source，wpctl set-default <id>；pw-play/pw-record 自检

中文读成英文拼：安装 ordered-set、jieba、pypinyin，并确保使用中文管线

TTS 404：音色缺失自动回退；可预缓存对应 *.pt

更智能：将 LLM_MODEL 换成 llama3.2:1b-instruct 或更强（注意树莓派性能）

🔒 Privacy | 隐私

默认本地运行；联网仅在首次下载模型/语音包。设置 HF_HUB_OFFLINE=1 可强制离线。

📄 License | 许可协议

MIT（见 LICENSE）。

🙌 Acknowledgements | 致谢

本项目初始硬件接线、蓝牙/音频配置以及整体架构思路均参考了 OminousIndustries/Bob — 特此致谢！
The initial hardware wiring, Bluetooth/audio setup, and overall architecture of this project were inspired by OminousIndustries/Bob — many thanks for the excellent reference!

---
