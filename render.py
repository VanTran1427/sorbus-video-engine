import os, json, asyncio, requests, subprocess, base64, wave, re, urllib.parse
import edge_tts

# SUBAGENT 1: Đạo diễn Phân cảnh (Chia kịch bản thành 5 cặp [Lời thoại - Cảnh quay] khớp 1:1)
def subagent_storyboard_director(raw_voice, raw_prompts, api_key):
    fallback_scenes = [
        {"voice": "Có bao giờ bạn thắc mắc, vì sao mình uống vitamin đều đặn mỗi ngày mà cơ thể vẫn uể oải không?", "queries": ["tired woman morning", "woman waking up", "drinking water"]},
        {"voice": "Thực ra, nhiều loại dưỡng chất quan trọng lại không thể tự hòa tan nếu chỉ uống cùng nước lọc thông thường.", "queries": ["pouring water glass", "glass of water", "clear water"]},
        {"voice": "Bí quyết nằm ở việc kết hợp chúng ngay trong bữa ăn có chất béo lành mạnh như quả bơ, các loại hạt hay dầu ô liu.", "queries": ["avocado toast", "olive oil salad", "healthy breakfast"]},
        {"voice": "Chính lớp chất béo tự nhiên này sẽ mở khóa, giúp cơ thể hấp thu trọn vẹn dưỡng chất vào sâu bên trong.", "queries": ["fresh salad bowl", "cooking healthy food", "cutting vegetables"]},
        {"voice": "Chỉ một thay đổi nhỏ vào buổi sáng thôi, bạn sẽ thấy nguồn năng lượng khác biệt rõ rệt suốt cả ngày dài đấy nhé.", "queries": ["happy woman sunlight", "woman stretching morning", "woman smiling outdoor"]}
    ]

    if not api_key or "DAN_MA" in api_key:
        return fallback_scenes

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    prompt = f"""
Bạn là Đạo diễn Storyboard cho kênh TikTok/Reels sức khỏe cao cấp.
Dựa trên nội dung gốc dưới đây, hãy chia kịch bản thành ĐÚNG 5 PHÂN CẢNH liên kết chặt chẽ để tổng thời lượng đọc khoảng 28-32 giây.

Nội dung gốc: "{raw_voice}"
Gợi ý bối cảnh gốc: {json.dumps(raw_prompts, ensure_ascii=False)}

YÊU CẦU BẮT BUỘC ĐỂ HÌNH VÀ TIẾNG KHỚP 100%:
1. Mỗi phân cảnh gồm 1 câu thoại văn nói tự nhiên (12-17 chữ/câu) VÀ danh sách 3 cụm từ khóa tiếng Anh (từ cụ thể nhất đến dễ tìm nhất trên kho stock video thực tế) mô tả ĐÚNG hành động/sự vật vừa nhắc tới trong câu thoại đó.
   - Ví dụ câu thoại nhắc "mệt mỏi, uể oải" -> queries: ["tired woman desk", "woman rubbing eyes", "yawning morning"]
   - Ví dụ câu thoại nhắc "uống nước lọc" -> queries: ["drinking glass water", "pouring water", "water glass"]
   - Ví dụ câu thoại nhắc "quả bơ, dầu ô liu, bữa ăn" -> queries: ["slicing avocado", "pouring olive oil", "healthy salad"]
   - Ví dụ câu thoại nhắc "vitamin D, ánh nắng" -> queries: ["woman morning sunlight", "sunlight window", "walking sunny park"]
2. TUYỆT ĐỐI KHÔNG dùng từ khóa trừu tượng (như "absorption", "health", "nutrients", "4k", "9:16") vì kho video sẽ trả về hình linh tinh. Chỉ dùng danh từ + động từ quay thật nhìn thấy bằng mắt thường!

Trả về ĐÚNG JSON nguyên bản:
{{
  "scenes": [
    {{"voice": "Câu 1...", "queries": ["specific query 1", "broader query 2", "safe visual query 3"]}},
    {{"voice": "Câu 2...", "queries": ["...", "...", "..."]}},
    {{"voice": "Câu 3...", "queries": ["...", "...", "..."]}},
    {{"voice": "Câu 4...", "queries": ["...", "...", "..."]}},
    {{"voice": "Câu 5...", "queries": ["...", "...", "..."]}}
  ]
}}
"""
    try:
        r = requests.post(url, json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json"}
        }, timeout=30)
        if r.status_code == 200:
            data = json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])
            scenes = data.get("scenes", [])
            if len(scenes) == 5:
                return scenes
    except Exception as e:
        print("Storyboard fallback:", e)

    return fallback_scenes

# SUBAGENT 2: Thu âm từng phân cảnh để lấy độ dài giây chuẩn xác 100%
async def generate_scene_audio(text, idx, api_key):
    out_wav = f"voice_{idx}.wav"
    success = False

    if api_key and "DAN_MA" not in api_key:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-tts:generateContent?key={api_key}"
        payload = {
            "contents": [{
                "parts": [{
                    "text": f"Đọc câu chia sẻ sau bằng giọng nữ tiếng Việt trẻ trung, ấm áp, tự nhiên như đang trò chuyện gần gũi, nhịp điệu vừa phải mượt mà: {text}"
                }]
            }],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Aoede"}}}
            }
        }
        try:
            r = requests.post(url, json=payload, timeout=35)
            if r.status_code == 200:
                b64_audio = r.json()["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]
                pcm_bytes = base64.b64decode(b64_audio)
                with wave.open(out_wav, "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(24000)
                    wf.writeframes(pcm_bytes)
                success = True
        except Exception as e:
            print(f"Gemini TTS scene {idx} fallback:", e)

    if not success:
        comm = edge_tts.Communicate(text, "vi-VN-HoaiMyNeural", rate="+4%", pitch="+2Hz")
        await comm.save(out_wav)

    # Chuẩn hóa âm lượng & thêm 0.25s nghỉ tự nhiên cuối câu
    norm_wav = f"voice_norm_{idx}.wav"
    subprocess.run([
        "ffmpeg", "-y", "-i", out_wav,
        "-af", "apad=pad_dur=0.25,loudnorm=I=-16:TP=-1.5:LRA=11",
        "-ar", "44100", "-ac", "2", norm_wav
    ], check=True)

    # Đo chính xác thời lượng câu nói (tính bằng giây)
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", norm_wav],
        capture_output=True, text=True
    )
    dur = float(probe.stdout.strip() or 6.0)
    return norm_wav, max(dur, 2.5)

def is_valid_video(filepath):
    if not os.path.exists(filepath) or os.path.getsize(filepath) < 120000:
        return False
    res = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_name,width", "-of", "csv=p=0", filepath],
        capture_output=True, text=True
    )
    return res.returncode == 0 and len(res.stdout.strip()) > 0

# SUBAGENT 3: Săn Video B-Roll đúng ngữ cảnh từ Coverr (Stock Video chuyên nghiệp, không cần Key)
def hunt_matching_broll(queries, idx, out_path, used_urls):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    # Tầng 1: Quét kho B-roll điện ảnh Coverr.co theo đúng 3 cấp từ khóa của câu thoại
    for q in queries:
        try:
            enc_q = urllib.parse.quote(q)
            api_url = f"https://coverr.co/api/videos?query={enc_q}&page=0&page_size=10"
            r = requests.get(api_url, headers=headers, timeout=15)
            if r.status_code == 200:
                hits = r.json().get("hits", [])
                for h in hits:
                    # Kiểm tra từ khóa có thực sự liên quan đến tiêu đề/tags của video không
                    title_tags = (h.get("title", "") + " " + " ".join(h.get("tags", []))).lower()
                    q_words = [w.lower() for w in re.findall(r'[a-zA-Z]+', q) if len(w) > 3]
                    if q_words and not any(w in title_tags for w in q_words):
                        continue

                    urls_obj = h.get("urls", {})
                    mp4_url = urls_obj.get("mp4_download") or urls_obj.get("mp4") or h.get("mp4_url")
                    if mp4_url and mp4_url not in used_urls:
                        dl = requests.get(mp4_url, headers=headers, timeout=35)
                        if dl.status_code == 200:
                            with open(out_path, "wb") as f:
                                f.write(dl.content)
                            if is_valid_video(out_path):
                                used_urls.add(mp4_url)
                                print(f"Scene {idx} matched Coverr [{q}]: {h.get('title')}")
                                return True
        except Exception as e:
            print(f"Coverr query '{q}' skip:", e)

    # Tầng 2: Nếu trang API JSON đổi cấu trúc, quét thẳng trang tìm kiếm HTML của Coverr
    for q in queries:
        try:
            slug = re.sub(r'[^a-z0-9]+', '-', q.lower()).strip('-')
            r = requests.get(f"https://coverr.co/s?q={urllib.parse.quote(q)}", headers=headers, timeout=15)
            if r.status_code == 200:
                mp4s = re.findall(r'https://cdn\.coverr\.co/videos/[^\s"\'<>]+?\.mp4', r.text)
                for link in mp4s:
                    if link not in used_urls:
                        dl = requests.get(link, headers=headers, timeout=35)
                        if dl.status_code == 200:
                            with open(out_path, "wb") as f:
                                f.write(dl.content)
                            if is_valid_video(out_path):
                                used_urls.add(link)
                                print(f"Scene {idx} matched Coverr CDN [{q}]: {link}")
                                return True
        except Exception:
            pass

    # Tầng 3: Dự phòng ảnh minh họa sát nghĩa 100% tạo trực tiếp theo đúng câu thoại + chuyển động Ken Burns mượt
    try:
        img_prompt = urllib.parse.quote(f"cinematic vertical photography of {queries[0]}, warm natural morning light, shallow depth of field, lifestyle wellness, high resolution, no text")
        img_url = f"https://image.pollinations.ai/prompt/{img_prompt}?width=720&height=1280&nologo=true&seed={idx+101}"
        ri = requests.get(img_url, headers=headers, timeout=30)
        if ri.status_code == 200 and len(ri.content) > 30000:
            img_path = f"fallback_img_{idx}.jpg"
            with open(img_path, "wb") as f:
                f.write(ri.content)
            subprocess.run([
                "ffmpeg", "-y", "-loop", "1", "-i", img_path,
                "-vf", "scale=800:1422,zoompan=z='min(zoom+0.0008,1.12)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=240:s=720x1280:fps=30,format=yuv420p",
                "-t", "8", "-c:v", "libx264", "-preset", "fast", out_path
            ], check=True)
            if is_valid_video(out_path):
                print(f"Scene {idx} matched exact AI visual fallback: {queries[0]}")
                return True
    except Exception as e:
        print("Visual fallback skip:", e)

    return False

async def main():
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    raw_prompts = [os.environ.get(f"P{i}", "") for i in range(1, 6)]
    raw_voice = os.environ.get("VOICE_TEXT", "").strip()

    # Bước 1: Lên Storyboard đồng bộ từng câu thoại với đúng từ khóa hình ảnh của câu đó
    scenes = subagent_storyboard_director(raw_voice, raw_prompts, gemini_key)

    used_urls = set()
    scene_videos = []
    scene_audios = []
    total_duration = 0.0

    # Bước 2: Xử lý từng phân cảnh (Đo giây giọng nói câu nào -> Cắt đúng cảnh quay dài bấy nhiêu giây)
    for idx, sc in enumerate(scenes):
        voice_line = sc.get("voice", "")
        queries = sc.get("queries", ["healthy morning sunlight"])

        wav_file, dur = await generate_scene_audio(voice_line, idx, gemini_key)
        scene_audios.append(wav_file)
        total_duration += dur

        raw_vid = f"raw_{idx}.mp4"
        clip_name = f"clip_{idx}.mp4"
        fade_out_st = max(0.1, round(dur - 0.3, 2))

        if hunt_matching_broll(queries, idx, raw_vid, used_urls):
            subprocess.run([
                "ffmpeg", "-y", "-stream_loop", "-1", "-i", raw_vid,
                "-vf", f"scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,setsar=1,fps=30,format=yuv420p,eq=brightness=0.02:saturation=1.1,fade=t=in:st=0:d=0.25,fade=t=out:st={fade_out_st}:d=0.3",
                "-t", f"{dur:.2f}", "-an", "-c:v", "libx264", "-preset", "fast", "-crf", "23", clip_name
            ], check=True)
        else:
            subprocess.run([
                "ffmpeg", "-y", "-f", "lavfi",
                "-i", f"gradients=s=720x1280:c0=#1e130c:c1=#c5a059:duration={dur:.2f}:speed=0.05:r=30",
                "-vf", "setsar=1,format=yuv420p", "-t", f"{dur:.2f}", "-c:v", "libx264", clip_name
            ], check=True)

        scene_videos.append(clip_name)
        await asyncio.sleep(1)

    # Bước 3: Nối 5 câu thoại thành 1 luồng Audio hoàn chỉnh + Trộn nhạc nền dịu nhẹ
    audio_inputs = []
    for af in scene_audios:
        audio_inputs.extend(["-i", af])
    a_concat = "".join([f"[{i}:a:0]" for i in range(len(scene_audios))]) + f"concat=n={len(scene_audios)}:v=0:a=1[voice_full]"

    subprocess.run([
        "ffmpeg", "-y", *audio_inputs,
        "-filter_complex", a_concat,
        "-map", "[voice_full]", "voice_master.wav"
    ], check=True)

    bgm_dur = round(total_duration + 2, 2)
    fade_bgm_out = max(1.0, round(total_duration - 1.5, 2))
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"aevalsrc='0.018*sin(2*PI*220*t)+0.015*sin(2*PI*277.18*t)+0.015*sin(2*PI*329.63*t)+0.01*sin(2*PI*415.3*t)':s=44100:d={bgm_dur}",
        "-af", f"lowpass=f=700,afade=t=in:st=0:d=1.5,afade=t=out:st={fade_bgm_out}:d=1.5",
        "bgm.wav"
    ], check=True)

    subprocess.run([
        "ffmpeg", "-y", "-i", "voice_master.wav", "-i", "bgm.wav",
        "-filter_complex", "[0:a]volume=1.35[v];[1:a]volume=0.28[b];[v][b]amix=inputs=2:duration=first:dropout_transition=2[aout]",
        "-map", "[aout]", "-c:a", "aac", "-b:a", "192k", "final_audio.m4a"
    ], check=True)

    # Bước 4: Nối 5 cảnh Video khớp chính xác từng phần mười giây với 5 câu thoại
    vid_inputs = []
    for vf in scene_videos:
        vid_inputs.extend(["-i", vf])
    v_concat = "".join([f"[{i}:v:0]" for i in range(len(scene_videos))]) + f"concat=n={len(scene_videos)}:v=1:a=0[outv]"

    subprocess.run([
        "ffmpeg", "-y", *vid_inputs, "-i", "final_audio.m4a",
        "-filter_complex", v_concat,
        "-map", "[outv]", "-map", f"{len(scene_videos)}:a:0",
        "-c:v", "libx264", "-profile:v", "main", "-pix_fmt", "yuv420p", "-crf", "24",
        "-c:a", "copy", "-movflags", "+faststart", "-shortest", "final_30s.mp4"
    ], check=True)

if __name__ == "__main__":
    asyncio.run(main())
