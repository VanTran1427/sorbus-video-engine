import os, json, asyncio, requests, subprocess, urllib.parse
import edge_tts

async def main():
    prompts = [
        os.environ.get("P1", "Golden vitamin capsule macro, warm sunlight"),
        os.environ.get("P2", "Healthy glowing skin wellness morning"),
        os.environ.get("P3", "Fresh avocado and olive oil nutrition"),
        os.environ.get("P4", "Scientific cellular absorption glowing gold"),
        os.environ.get("P5", "Minimalist luxury wellness table morning")
    ]
    voice_text = os.environ.get("VOICE_TEXT", "Bí quyết hấp thu tối đa dưỡng chất cho cơ thể khỏe mạnh mỗi ngày.")

    # 1. Tạo giọng đọc tiếng Việt tự nhiên (Hoài My)
    communicate = edge_tts.Communicate(voice_text, "vi-VN-HoaiMyNeural", rate="+0%")
    await communicate.save("voice.mp3")

    # 2. Tải 5 ảnh 9:16 và cắt bỏ 60px đáy (xóa sạch watermark nếu có) + tạo hiệu ứng chuyển động 6s/cảnh
    clips = []
    for i, p in enumerate(prompts):
        url = f"https://image.pollinations.ai/prompt/{urllib.parse.quote(p)}?width=1080&height=1980&nologo=true&model=flux&seed={100+i}"
        img_data = requests.get(url, timeout=60).content
        with open(f"img_{i}.jpg", "wb") as f:
            f.write(img_data)
        
        clip_name = f"clip_{i}.mp4"
        # FFmpeg: Cắt 1080x1920 từ đỉnh (bỏ 60px đáy) + hiệu ứng Ken Burns Zoom mượt 6 giây (150 frames @ 25fps)
        cmd = [
            "ffmpeg", "-y", "-loop", "1", "-i", f"img_{i}.jpg",
            "-vf", "crop=1080:1920:0:0,scale=2160:3840,zoompan=z='min(zoom+0.0008,1.25)':d=150:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps=25",
            "-t", "6", "-c:v", "libx264", "-pix_fmt", "yuv420p", clip_name
        ]
        subprocess.run(cmd, check=True)
        clips.append(f"file '{clip_name}'\n")

    with open("list.txt", "w") as f:
        f.writelines(clips)

    # 3. Ghép 5 cảnh (30s) + lồng tiếng đọc
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "list.txt",
        "-i", "voice.mp3", "-c:v", "copy", "-c:a", "aac", "-shortest", "final_30s.mp4"
    ], check=True)

if __name__ == "__main__":
    asyncio.run(main())
