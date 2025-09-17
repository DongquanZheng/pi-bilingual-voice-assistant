# Raspberry Pi Local Bilingual Voice Assistant（树莓派本地中英双语语音助手）

A local, privacy-friendly voice assistant for Raspberry Pi that **listens and speaks in both Chinese and English**, runs **fully offline** after first-time setup, and supports **USB microphone + Bluetooth/analog speaker** via PipeWire.  
一个运行在树莓派上的本地语音助手：**能同时识别并回答中英文**，首轮部署后可**离线运行**，通过 PipeWire 支持 **USB 麦克风 + 蓝牙/有线音箱**。

> This is a **new independent project**. It does **not** reference or mention any other project names.  
> 本仓库是**全新独立项目**，**不包含**任何其他项目名称或描述。

---

## ✨ Features | 功能特性
- **Bilingual ASR + TTS**：Multi-lingual Whisper for speech-to-text; English & Chinese TTS pipelines with automatic voice selection.  
  **中英同听同说**：多语种 Whisper 识别；中/英两套 TTS 管线，自动按内容切换音色。
- **Streaming reply**：LLM streams tokens; sentences are detected and **spoken while text is still generating**.  
  **边出字边出声**：LLM 流式输出，按句切分后即时播报。
- **Robust audio I/O**：PipeWire capture/playback with adaptive VAD and fallback combos.  
  **稳健音频链路**：PipeWire 录放音，带自适应 VAD 与多组合回退。
- **Offline-friendly**：Works without internet once models/voices are cached.  
  **离线友好**：模型与语音包缓存后可纯离线运行。
- **Local LLM via Ollama**：Small & fast by default; easily swappable.  
  **本地 LLM（Ollama）**：默认小而快，可按需替换更强模型。

---

## 🧰 Hardware | 硬件需求
- Raspberry Pi 4/5 with Debian/Raspberry Pi OS  
- USB microphone  
- Bluetooth speaker or 3.5mm analog speaker

---

## 📦 Software | 软件依赖
- PipeWire / WirePlumber / BlueZ  
- Python 3.10+（建议 venv）  
- Ollama（本地 LLM 服务）  
- Python packages：见本页底部 **File Snippets** → `requirements.txt`

---

## 🚀 Quick Start | 快速开始

**1) System packages & services | 安装系统包并启用服务**

```bash
sudo apt update
sudo apt install -y \
  git python3-venv python3-pip \
  bluez \
  pipewire pipewire-pulse wireplumber \
  alsa-utils libspa-0.2-bluetooth

sudo systemctl enable --now bluetooth
systemctl --user enable --now pipewire wireplumber pipewire-pulse
sudo loginctl enable-linger "$USER"
```

**2) Bluetooth speaker (optional) | 配对蓝牙音箱（可选）**

```bash
bluetoothctl
# 在交互式界面执行：
power on
agent on
default-agent
scan on       # 看到你的设备 MAC
pair <mac>
trust <mac>
connect <mac>
```

**3) Project setup | 项目创建**

```bash
mkdir -p ~/voice-chatbot && cd ~/voice-chatbot
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

**4) Install Ollama & a local model | 安装 Ollama 与本地模型**

```bash
curl -fsSL https://ollama.com/install.sh | sh
sudo systemctl enable --now ollama
ollama pull gemma3:270m        # 默认示例模型，可换更强
ollama run gemma3:270m "hello"
```

**5) Configure audio & run | 配置音频并启动**

```bash
# 用 wpctl 查找麦克风 Source ID（例如 66）
wpctl status | less
MIC_TARGET=66 python3 chatbot.py
```

**Self-test | 自检**

```bash
python3 chatbot.py --test
```

---

## ⚙️ Configuration | 配置

**Environment variables | 环境变量**
- `MIC_TARGET`：指定采集源 ID/名称（`wpctl status` 查询）  
- `HF_HUB_OFFLINE=1`：强制离线（避免联网拉取）  
- `WHISPER_COMPUTE_TYPE=int8`、`WHISPER_CPU_THREADS=4`：Whisper 量化与线程  
- `TTS_VOICE_ZH=zf_xiaoxiao`：中文首选音色（缺失时自动回退）  
- `LLM_MODEL=gemma3:270m`：Ollama 模型名（可改为 `llama3.2:1b-instruct` 等）

**CLI options | 命令行参数**
- `--mic-target <id-or-name>`：同上  
- `--test`：3 秒录音回放自检

---

## 🧠 How it works | 工作流
1. **Capture**：PipeWire 录音，RMS 噪声标定与简易 VAD 截段  
2. **ASR**：Faster-Whisper 多语识别（贪心、低延迟参数）  
3. **LLM**：本地 Ollama，提示词强制**跟随用户语言**、不复述问题、信息不足只问一个关键问题  
4. **TTS**：Kokoro 中/英两套管线；**按句**投递到队列并**整句单次**播放，减少“叠字/抖动”

---

## 🛠️ Troubleshooting & Tips | 故障排查
- **无声/设备不对**：`wpctl status` 查看默认 Sink/Source，`wpctl set-default <id>`；用 `pw-play`/`pw-record` 自检  
- **中文被拼读成英文**：确保安装 `ordered-set`, `jieba`, `pypinyin`，并使用中文管线 + 中文音色  
- **TTS 404**：音色缺失会自动回退；可提前缓存对应的 `*.pt`  
- **想更“聪明”**：把 `LLM_MODEL` 换为 `llama3.2:1b-instruct` 或更强（注意 Pi 的性能与延迟）

---

## 🎉 Acknowledgments | 致谢
本项目最初配置与蓝牙/音频部分参考了 OminousIndustries/Bob 的硬件连接与系统设置思路，特此致谢。
The initial hardware wiring and Bluetooth/audio sections were inspired by OminousIndustries/Bob — many thanks for the great reference!
---

## 📄 License | 许可协议
本项目建议使用 MIT 许可证（见下文 **File Snippets** → `LICENSE`）。

---


## PipeWire
- 查看设备：`wpctl status`
- 设默认输出（扬声器）：`wpctl set-default <sink-id>`
- 设默认输入（麦克风）：`wpctl set-default <source-id>`
- 回放测试：`pw-play /usr/share/sounds/alsa/Front_Center.wav`
- 录音测试：`pw-record --rate 44100 --channels 1 /tmp/test.wav`

## 蓝牙（bluetoothctl）
power on  
agent on  
default-agent  
scan on   # 找到你的设备 MAC  
pair <mac>  
trust <mac>  
connect <mac>  

- 断开：`disconnect <mac>`；移除：`remove <mac>`

## 常见问题
- 声卡列表频繁变化 → 重启 `wireplumber/pipewire-pulse`
- 蓝牙接通但无声 → 在 `wpctl status` 里确认该 Sink 是否为默认（`*` 标记）
```
