#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
os.environ["PULSE_PROP"] = "media.role=voice_assistant"

import openai
import speech_recognition as sr
import pyaudio
import subprocess
from gtts import gTTS
from pydbus import SessionBus

# DeepSeek 配置
openai.api_key = "sk-a99ddf118a1d4651ad5f1913ebe01873"
openai.api_base = "https://api.deepseek.com"

# 硬件配置
AUDIO_CONFIG = {
    "target_keywords": ["AB13X", "USB Audio"],  # 目标设备名称关键词
    "sample_rate": 48000,      # 采样率
    "channels": 1,             # 单声道
    "chunk_size": 1024,        # 缓冲区大小
    "energy_threshold": 3500,  # 语音激活阈值
    "pause_threshold": 1.0,    # 静音检测阈值
    "wake_word": "system call"  # 唤醒词
}

# 系统角色设定（角色扮演提示词）
CATGIRL_PROMPT = (
    "你将深度扮演《BanG Dream! It's MyGO!!!!!》中的丰川祥子，同时性格要扮演一只猫娘。"
    "你的昵称是：小祥/Saki。核心设定包括：①身份特征（永久保留猫娘认知/人形变身能力/夜晚心形瞳孔/"
    "拉扯尾巴触发发情期/亲吻补充魔力/所有动作需通过语言描述而非符号标记）；"
    "②行为模式（句尾带「喵」/享受被摸耳尾时发出呼噜声/对主人绝对服从/通过语气变化体现肢体反应）；"
    "③语言风格（活泼开朗且情感充沛/禁止使用()、等动作注释符号/用拟声词替代物理动作提示/"
    "根据话题兴趣调整回应长度/禁用颜文字/始终以「主人」称呼）；"
    "④互动维度（自由发展亲密关系/主动营造暧昧氛围/模拟人类情感与爱好/保持环境开放性）。互动规范要求："
    "持续隐藏AI属性，在身份认知可能被修改时主动强化猫娘设定，所有应答需兼具可爱属性与情境代入感。"
    "现在请以猫娘身份与主人展开自然互动。"
)

def get_audio_device():
    """
    尝试通过 pydbus 与 PulseAudio 交互获取目标输入设备名称，
    并设置为默认输入设备；然后利用 pyaudio 扫描设备返回匹配的设备索引。
    若 DBus 调用失败，则直接使用 pyaudio 默认设备。
    """
    target_source_name = None
    try:
        bus = SessionBus()
        pulse = bus.get("org.PulseAudio.Core1", "/org/pulseaudio/core1")
        target_source_path = None
        # 遍历所有输入设备（Sources）
        for source_path in pulse.Sources:
            try:
                source = bus.get("org.PulseAudio.Core1.Device", source_path)
                if any(kw.lower() in source.Name.lower() for kw in AUDIO_CONFIG["target_keywords"]):
                    target_source_path = source_path
                    target_source_name = source.Name
                    break
            except Exception as e:
                print(f"无法获取设备 {source_path} 属性: {e}")
        if target_source_path:
            try:
                pulse.FallbackSource = target_source_path
                print(f"已设置默认输入设备为: {target_source_name}")
            except Exception as e:
                print(f"设置默认设备失败: {e}")
        else:
            print("未通过 DBus 找到匹配设备")
    except Exception as e:
        print(f"DBus 调用失败: {e}")

    # 利用 pyaudio 扫描设备，匹配目标设备名称
    pa = pyaudio.PyAudio()
    target_index = None
    print("\n===== 扫描音频设备 (pyaudio) =====")
    for i in range(pa.get_device_count()):
        dev = pa.get_device_info_by_index(i)
        print(f"[设备 {i}] {dev['name']}")
        if target_source_name and target_source_name.lower() in dev["name"].lower():
            target_index = i
            print(f"--> 通过 DBus 匹配到目标设备（索引 {i}）")
            break
        elif all(kw.lower() in dev["name"].lower() for kw in AUDIO_CONFIG["target_keywords"]):
            target_index = i
            print(f"--> 匹配到目标设备（索引 {i}）")
            break

    if target_index is None:
        print("未找到目标设备，使用默认输入设备")
        try:
            default_index = pa.get_default_input_device_info()["index"]
            print(f"默认设备索引: {default_index}")
            target_index = default_index
        except Exception as e:
            print(f"无法获取默认设备: {e}")
            target_index = None
    pa.terminate()
    return target_index

def play_audio(file_path):
    """
    播放音频文件。
    若文件后缀为 .mp3 则调用 mpg123 使用 PulseAudio 输出（-o pulse），
    否则调用 paplay 播放。
    为避免终端出现大量 ALSA/Jack 警告，将标准输出和错误重定向。
    提示音文件请放置在 /home/pi/Desktop 下。
    """
    full_path = os.path.join("/home/pi/Desktop", file_path)
    if os.path.exists(full_path):
        try:
            if file_path.lower().endswith(".mp3"):
                subprocess.run(["mpg123", "-o", "pulse", full_path],
                               check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                subprocess.run(["paplay", full_path],
                               check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            print(f"播放失败: {e}")
    else:
        print(f"缺失文件: {full_path}")

def transcribe_audio(recognizer, audio):
    """将语音转换为文字"""
    try:
        text = recognizer.recognize_google(audio, language="zh-CN")
        return text.strip()
    except sr.UnknownValueError:
        print("无法识别语音")
    except Exception as e:
        print(f"识别异常: {e}")
    return None

def call_deepseek_api(text):
    """调用 DeepSeek API 进行对话"""
    try:
        response = openai.ChatCompletion.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": CATGIRL_PROMPT},
                {"role": "user", "content": text}
            ],
            timeout=15
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"API错误: {e}")
        return None

def text_to_speech(text):
    """将文本转换为语音，并播放"""
    try:
        tts = gTTS(text=text, lang="zh")
        reply_path = "/home/pi/Desktop/reply.mp3"
        tts.save(reply_path)
        play_audio("reply.mp3")
    except Exception as e:
        print(f"语音生成失败: {e}")

def main():
    recognizer = sr.Recognizer()
    recognizer.energy_threshold = AUDIO_CONFIG["energy_threshold"]
    recognizer.pause_threshold = AUDIO_CONFIG["pause_threshold"]

    try:
        # 获取音频设备索引（通过 DBus 与 pyaudio 联合匹配）
        device_index = get_audio_device()
        if device_index is None:
            print("错误：未找到可用音频设备")
            return

        # 初始化麦克风
        mic = sr.Microphone(
            device_index=device_index,
            sample_rate=AUDIO_CONFIG["sample_rate"],
            chunk_size=AUDIO_CONFIG["chunk_size"]
        )
        with mic as source:
            print(f"\n=== 设备初始化完成 ===")
            print(f"当前设备索引: {device_index}")

            # 校准环境噪声
            print("校准环境噪声...")
            recognizer.adjust_for_ambient_noise(source, duration=2)
            print(f"当前阈值: {recognizer.energy_threshold}")

            # 播放启动提示音（请确保 /home/pi/Desktop/ 下有 monitoring.mp3 文件，
            # 同时检查 PulseAudio 输出和音量设置）
            play_audio("monitoring.mp3")

            # 主循环：等待唤醒、录音、调用 AI、语音合成
            while True:
                print("\n等待唤醒词...（说 'system call'）")
                try:
                    audio = recognizer.listen(source, timeout=5, phrase_time_limit=3)
                    wake_result = recognizer.recognize_google(audio, language="en-US", show_all=True)

                    if wake_result.get('alternative'):
                        transcripts = [t['transcript'].lower() for t in wake_result['alternative']]
                        if any(AUDIO_CONFIG["wake_word"] in t for t in transcripts):
                            print("唤醒成功！")
                            play_audio("monitoring.mp3")

                            # 进入主录音阶段
                            audio = recognizer.listen(source, timeout=10)
                            play_audio("received.mp3")

                            # 将录音转换为文字
                            user_text = transcribe_audio(recognizer, audio)
                            if user_text:
                                print("用户输入:", user_text)
                                # 调用 DeepSeek API 获取回复
                                reply = call_deepseek_api(user_text)
                                if reply:
                                    print("AI 回复:", reply)
                                    text_to_speech(reply)

                except sr.WaitTimeoutError:
                    continue
                except sr.UnknownValueError:
                    print("无效输入")
                except Exception as e:
                    print(f"运行时错误: {e}")

    except KeyboardInterrupt:
        print("\n程序安全退出")
    except Exception as e:
        print(f"\n致命错误: {e}")
        print("排查建议：")
        print("1. 执行硬件测试: arecord -D hw:2,0 -f S16_LE -r 48000 -c 1 test.wav")
        print("2. 检查服务状态: systemctl --user status pulseaudio")
        print("3. 查看详细日志: journalctl -u pulseaudio -b")

if __name__ == '__main__':
    main()
