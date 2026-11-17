import os, asyncio, requests, subprocess, urllib.parse
import edge_tts

DEFAULT_PROMPTS = [
    "Macro golden vitamin softgel capsule in warm morning sunlight, luxury wellness aesthetic",
    "Fresh avocado and pure olive oil droplets on marble table, natural morning light",
    "Golden liquid cellular absorption glowing particles, scientific wellness visualization",
    "Healthy glowing skin woman enjoying morning sunlight, minimalist luxury lifestyle",
    "Aesthetic glass of water and golden softgel on wooden tray, peaceful morning atmosphere"
]

async def main():
    raw_prompts = [
        os.environ.get("P1", ""),
        os.environ.get("P2", ""),
        os.environ.get("P3", ""),
        os.environ.get("P4", ""),
        os.environ.get("P5", "")
    ]
    prompts = [p.strip() if p and len(p.strip()) > 5 else DEFAULT_PROMPTS[i] for i, p in enumerate(raw_prompts)]

    voice_text = os.environ.get("VOICE_TEXT", "").strip()
    if len(voice_text) < 10:
        voice_text = "Bạn có biết các vitamin tan trong dầu như Vitamin D chỉ hấp thu tối đa khi dùng cùng bữa ăn có chất béo lành mạnh? Hãy bổ sung đúng cách mỗi sáng để cơ thể luôn tràn đầy năng lượng nhé."

    # 1. Tạo giọng đọc tiếng Việt Hoài My
    communicate = edge_tts.Communicate(voice_text, "vi-VN-HoaiMyNeural", rate="+0%")
    await communicate.save("voice.mp3")

    # 2. Tải 5 ảnh (Giả lập trình duyệt + Kiểm tra ảnh hợp lệ + Tự động dự phòng)
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    clips = []

    for i, p in enumerate(prompts):
        img_file = f"img_{i}.jpg"
        valid_img = False
        clean_p = urllib.parse.quote(p[:300])

        for attempt in range(3):
            try:
                url = f"https://image.pollinations.ai/prompt/{clean_p}?width=1080&height=1920&nologo=true&seed={200+i+attempt*10}"
                r = requests.get(url, headers=headers, timeout=45)
                # Kiểm tra đúng là file ảnh thật (>10KB)
                if r.status_code == 200 and len(r.content) > 10000 and r.content[:2] in [b'\xff\xd8', b'\x89P']:
                    with open(img_file, "wb") as f:
                        f.write(r.content)
                    valid_img = True
                    break
            except Exception as e:
                print(f"Retry {attempt} for scene {i}: {e}")

        # Nếu Pollinations chặn IP GitHub, tạo nền Gradient Vàng Kim chuẩn Luxury bằng FFmpeg
        if not valid_img:
            subprocess.run([
                "ffmpeg", "-y", "-f", "lavfi",
                "-i", "color=c=#D4AF37:s=1080x1920:d=1",
                "-frames:v", "1", img_file
            ], check=True)

        clip_name = f"clip_{i}.mp4"
        # FFmpeg: Scale chuẩn 1080x1920 trước rồi chạy hiệu ứng Zoom mượt 6 giây
        cmd = [
            "ffmpeg", "-y", "-loop", "1", "-i", img_file,
            "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,scale=2160:3840,zoompan=z='min(zoom+0.0008,1.25)':d=150:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps=25",
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
