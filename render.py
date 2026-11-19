import os, json, asyncio, requests, subprocess, base64, wave, re, urllib.parse
import edge_tts

DEFAULT_SCENES = [
    "pouring olive oil",
    "fresh avocado",
    "drinking water sunlight",
    "morning sunlight nature",
    "healthy breakfast fruit"
]

# Kho video quay thật HD dự phòng trực tiếp từ CDN Mixkit (Không cần API Key, tải siêu tốc từ máy chủ Mỹ)
CURATED_WELLNESS_VIDEOS = [
    "https://assets.mixkit.co/videos/preview/mixkit-pouring-olive-oil-into-a-small-bowl-42929-large.mp4",
    "https://assets.mixkit.co/videos/preview/mixkit-woman-drinking-water-in-the-morning-42615-large.mp4",
    "https://assets.mixkit.co/videos/preview/mixkit-fresh-sliced-avocado-on-a-wooden-board-42923-large.mp4",
    "https://assets.mixkit.co/videos/preview/mixkit-sunlight-filtering-through-green-leaves-4046-large.mp4",
    "https://assets.mixkit.co/videos/preview/mixkit-pouring-clean-water-into-a-glass-42608-large.mp4",
    "https://assets.mixkit.co/videos/preview/mixkit-hands-holding-fresh-organic-vegetables-42915-large.mp4",
    "https://assets.mixkit.co/videos/preview/mixkit-slow-motion-of-water-drops-falling-4053-large.mp4"
]

# SUBAGENT 1 & 2: Chuyển kịch bản sang văn nói tự nhiên + Lọc từ khóa tìm Video quay thật
def subagent_creative_director(raw_voice, raw_prompts, api_key):
    if not api_key or "DAN_MA" in api_key:
        return raw_voice, DEFAULT_SCENES

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    prompt = f"""
Bạn là Giám đốc Sáng tạo Video ngắn (TikTok/Reels) cho thương hiệu chăm sóc sức khỏe cao cấp.
Nhiệm vụ 1 (Voice Coach): Viết lại lời bình dưới đây sang VĂN NÓI ĐỜI THƯỜNG của creator chia sẻ mẹo sức khỏe. Câu ngắn gọn, mềm mại, gần gũi, dùng dấu phẩy và dấu ba chấm (...) ở chỗ cần nghỉ lấy hơi tự nhiên. Độ dài 65-75 chữ (đọc vừa khít 28-30 giây). Tuyệt đối không dùng văn viết cứng nhắc, không kèm ghi chú.
Lời bình gốc: "{raw_voice}"

Nhiệm vụ 2 (Visual Director): Xuất ra đúng 5 cụm từ khóa tiếng Anh ngắn gọn (2-3 từ/cụm, chỉ tả cảnh vật/thực phẩm/ánh sáng thực tế như 'olive oil', 'avocado', 'morning sunlight', 'water droplets', 'healthy breakfast') để tìm video quay thật. Không dùng từ 9:16, 4k, bottle, supplement.
5 cảnh gốc: {json.dumps(raw_prompts, ensure_ascii=False)}

Trả về ĐÚNG JSON nguyên bản:
{{
  "natural_voice": "...",
  "video_queries": ["query 1", "query 2", "query 3", "query 4", "query 5"]
}}
"""
    try:
        r = requests.post(url, json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json"}
        }, timeout=30)
        if r.status_code == 200:
            res_text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            data = json.loads(res_text)
            queries = data.get("video_queries", DEFAULT_SCENES)
            if len(queries) < 5:
                queries = (queries + DEFAULT_SCENES)[:5]
            return data.get("natural_voice", raw_voice), queries
    except Exception as e:
        print("Subagent Director fallback:", e)

    return raw_voice, DEFAULT_SCENES

# SUBAGENT 3: Thu âm giọng đọc AI truyền cảm bằng Gemini Native Audio
def subagent_voice_actor(spoken_text, api_key, out_wav="voice.wav"):
    if not api_key or "DAN_MA" in api_key:
        return False
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-tts:generateContent?key={api_key}"
    payload = {
        "contents": [{
            "parts": [{
                "text": f"Hãy đọc lời tâm sự sau bằng giọng nữ tiếng Việt trẻ trung, ấm áp, truyền cảm, nhịp điệu trò chuyện gần gũi tự nhiên như người thật thu âm podcast, ngắt nghỉ nhẹ nhàng ở dấu phẩy: {spoken_text}"
            }]
        }],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {
                    "prebuiltVoiceConfig": {"voiceName": "Aoede"}
                }
            }
        }
    }
    try:
        r = requests.post(url, json=payload, timeout=45)
        if r.status_code == 200:
            b64_audio = r.json()["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]
            pcm_bytes = base64.b64decode(b64_audio)
            with wave.open(out_wav, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(24000)
                wf.writeframes(pcm_bytes)
            return True
    except Exception as e:
        print("Gemini TTS fallback:", e)
    return False

# SUBAGENT 4: Săn Video quay thật không cần API Key (Mixkit Search + Wikimedia Commons API + Kho CDN dự phòng)
def subagent_keyless_footage_hunter(query, index, out_path, used_urls):
    headers = {
        "User-Agent": "SorbusVideoBot/1.0 (https://healthstore.vn; support@healthstore.vn) Mozilla/5.0"
    }

    # Tầng 1: Quét trực tiếp CDN video quay thật từ Mixkit theo từ khóa (từ máy chủ GitHub Mỹ)
    slug = re.sub(r'[^a-z0-9]+', '-', query.lower()).strip('-')
    try:
        r = requests.get(f"https://mixkit.co/free-stock-video/{slug}/", headers=headers, timeout=15)
        if r.status_code == 200:
            mp4_links = re.findall(r'https://assets\.mixkit\.co/videos/[^\s"\'<>]+?-large\.mp4', r.text)
            for link in mp4_links:
                if link not in used_urls:
                    dl = requests.get(link, headers=headers, timeout=30)
                    if dl.status_code == 200 and len(dl.content) > 80000:
                        used_urls.add(link)
                        with open(out_path, "wb") as f:
                            f.write(dl.content)
                        return True
    except Exception as e:
        print("Mixkit search skip:", e)

    # Tầng 2: Gọi API mở của Wikimedia Commons (Tài nguyên mở 100%, không cần API Key)
    try:
        enc_q = urllib.parse.quote(f"{query} filetype:video")
        wiki_url = f"https://commons.wikimedia.org/w/api.php?action=query&generator=search&gsrsearch={enc_q}&gsrnamespace=6&gsrlimit=8&prop=imageinfo&iiprop=url|size&format=json"
        rw = requests.get(wiki_url, headers=headers, timeout=20)
        if rw.status_code == 200:
            pages = rw.json().get("query", {}).get("pages", {})
            for _, pinfo in pages.items():
                ii = (pinfo.get("imageinfo") or [{}])[0]
                vurl = ii.get("url", "")
                vsize = ii.get("size", 0)
                if vurl and vurl not in used_urls and vurl.lower().endswith((".webm", ".mp4")) and 100000 < vsize < 35000000:
                    dl = requests.get(vurl, headers=headers, timeout=40)
                    if dl.status_code == 200 and len(dl.content) > 100000:
                        used_urls.add(vurl)
                        with open(out_path, "wb") as f:
                            f.write(dl.content)
                        return True
    except Exception as e:
        print("Wikimedia search skip:", e)

    # Tầng 3: Lấy từ danh sách CDN Wellness quay thật cố định
    for fallback_url in CURATED_WELLNESS_VIDEOS[index:] + CURATED_WELLNESS_VIDEOS[:index]:
        if fallback_url not in used_urls:
            try:
                dl = requests.get(fallback_url, headers=headers, timeout=30)
                if dl.status_code == 200 and len(dl.content) > 80000:
                    used_urls.add(fallback_url)
                    with open(out_path, "wb") as f:
                        f.write(dl.content)
                    return True
            except Exception:
                pass

    return False

async def main():
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    raw_prompts = [os.environ.get(f"P{i}", "") for i in range(1, 6)]
    raw_voice = os.environ.get("VOICE_TEXT", "").strip()
    if len(raw_voice) < 10:
        raw_voice = "Có bao giờ bạn thắc mắc vì sao mình uống vitamin đều đặn mỗi ngày... mà cơ thể vẫn uể oải không? Bí quyết thực sự nằm ở việc dùng ngay trong bữa sáng có chất béo tốt như quả bơ hay dầu ô liu, giúp dưỡng chất thấm sâu gấp nhiều lần đấy nhé."

    # Bước 1: Subagent biên tập văn nói tự nhiên & từ khóa cảnh quay
    spoken_voice, scene_queries = subagent_creative_director(raw_voice, raw_prompts, gemini_key)

    # Bước 2: Subagent thu âm giọng đọc tự nhiên bằng Gemini TTS
    if not subagent_voice_actor(spoken_voice, gemini_key, "voice.wav"):
        comm = edge_tts.Communicate(spoken_voice, "vi-VN-HoaiMyNeural", rate="+5%", pitch="+2Hz")
        await comm.save("voice.wav")

    # Bước 3: Tạo nhạc nền Ambient ấm dịu & Mix dưới giọng đọc
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", "aevalsrc='0.02*sin(2*PI*220*t)+0.018*sin(2*PI*277.18*t)+0.018*sin(2*PI*329.63*t)+0.012*sin(2*PI*415.3*t)':s=44100:d=34",
        "-af", "lowpass=f=750,afade=t=in:st=0:d=1.5,afade=t=out:st=28:d=2",
        "bgm.wav"
    ], check=True)

    subprocess.run([
        "ffmpeg", "-y", "-i", "voice.wav", "-i", "bgm.wav",
        "-filter_complex", "[0:a]volume=1.4[v];[1:a]volume=0.3[b];[v][b]amix=inputs=2:duration=first:dropout_transition=2[aout]",
        "-map", "[aout]", "-c:a", "aac", "-b:a", "192k", "final_audio.m4a"
    ], check=True)

    # Bước 4: Tải 5 cảnh Video quay thật & hậu kỳ màu ấm + chuyển cảnh mượt
    used_urls = set()
    clips = []
    for i, q in enumerate(scene_queries):
        raw_vid = f"raw_{i}.mp4"
        clip_name = f"clip_{i}.mp4"
        if subagent_keyless_footage_hunter(q, i, raw_vid, used_urls):
            subprocess.run([
                "ffmpeg", "-y", "-stream_loop", "-1", "-i", raw_vid,
                "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30,eq=brightness=0.02:saturation=1.1,fade=t=in:st=0:d=0.35,fade=t=out:st=5.65:d=0.35",
                "-t", "6", "-an", "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p", clip_name
            ], check=True)
        else:
            subprocess.run([
                "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=#C5A059:s=1080x1920:d=6:r=30",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", clip_name
            ], check=True)
        clips.append(f"file '{clip_name}'\n")

    with open("list.txt", "w") as f:
        f.writelines(clips)

    # Bước 5: Ghép xuất MP4 hoàn chỉnh
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "list.txt",
        "-i", "final_audio.m4a", "-c:v", "copy", "-c:a", "copy", "-shortest", "final_30s.mp4"
    ], check=True)

if __name__ == "__main__":
    asyncio.run(main())
