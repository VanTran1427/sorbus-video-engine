import os, json, asyncio, requests, subprocess, base64, wave, re, urllib.parse
import edge_tts

DEFAULT_SCENES = [
    "pouring olive oil",
    "fresh avocado healthy",
    "drinking water morning",
    "sunlight nature leaves",
    "healthy breakfast fruit"
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

Nhiệm vụ 2 (Visual Director): Xuất ra đúng 5 cụm từ khóa tiếng Anh cực ngắn (2 từ/cụm, chỉ tả cảnh vật/thực phẩm/ánh sáng thực tế như 'olive oil', 'avocado', 'morning sunlight', 'water drops', 'healthy food') để tìm video quay thật. Không dùng từ 9:16, 4k, bottle, supplement.
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

# Kiểm tra chắc chắn file tải về có luồng hình ảnh video thật sự (không phải file lỗi/rỗng)
def is_valid_video(filepath):
    if not os.path.exists(filepath) or os.path.getsize(filepath) < 100000:
        return False
    res = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_name,width", "-of", "csv=p=0", filepath],
        capture_output=True, text=True
    )
    return res.returncode == 0 and len(res.stdout.strip()) > 0

# SUBAGENT 4: Săn Video quay thật từ Wikimedia Commons + Internet Archive (Mở 100%, không chặn GitHub IP)
def subagent_keyless_footage_hunter(query, index, out_path, used_urls):
    headers = {
        "User-Agent": "SorbusWellnessBot/2.0 (https://healthstore.vn; van@sorbus.vn)"
    }
    backup_queries = [query, "sunlight nature", "water drops", "fresh fruit", "healthy food", "morning coffee"]

    # Tầng 1: Quét kho video mở Wikimedia Commons (kèm kiểm tra ffprobe thật)
    for q in backup_queries:
        try:
            enc_q = urllib.parse.quote(f"{q} filetype:video")
            wiki_url = f"https://commons.wikimedia.org/w/api.php?action=query&generator=search&gsrsearch={enc_q}&gsrnamespace=6&gsrlimit=12&prop=imageinfo&iiprop=url|size|mime&format=json"
            rw = requests.get(wiki_url, headers=headers, timeout=20)
            if rw.status_code == 200:
                pages = rw.json().get("query", {}).get("pages", {})
                for _, pinfo in pages.items():
                    ii = (pinfo.get("imageinfo") or [{}])[0]
                    vurl = ii.get("url", "")
                    vsize = ii.get("size", 0)
                    vmime = ii.get("mime", "")
                    if vurl and vurl not in used_urls and ("video" in vmime or vurl.lower().endswith((".webm", ".mp4", ".ogv"))) and 150000 < vsize < 40000000:
                        dl = requests.get(vurl, headers=headers, timeout=45)
                        if dl.status_code == 200:
                            with open(out_path, "wb") as f:
                                f.write(dl.content)
                            if is_valid_video(out_path):
                                used_urls.add(vurl)
                                print(f"Scene {index} OK (Wikimedia): {vurl}")
                                return True
        except Exception as e:
            print("Wikimedia search skip:", e)

    # Tầng 2: Quét kho MP4 mở của Internet Archive (archive.org) - Không bao giờ chặn máy chủ Mỹ
    for q in [query, "nature sunlight", "water slow motion"]:
        try:
            ia_q = urllib.parse.quote(f'({q}) AND mediatype:(movies) AND format:(MPEG4)')
            ia_url = f"https://archive.org/advancedsearch.php?q={ia_q}&fl[]=identifier&rows=8&page=1&output=json"
            ra = requests.get(ia_url, headers=headers, timeout=20)
            if ra.status_code == 200:
                docs = ra.json().get("response", {}).get("docs", [])
                for doc in docs:
                    ident = doc.get("identifier")
                    if not ident:
                        continue
                    meta = requests.get(f"https://archive.org/metadata/{ident}", headers=headers, timeout=15).json()
                    for fobj in meta.get("files", []):
                        fname = fobj.get("name", "")
                        fsize = int(fobj.get("size", 0) or 0)
                        if fname.lower().endswith(".mp4") and 200000 < fsize < 30000000:
                            dl_url = f"https://archive.org/download/{ident}/{urllib.parse.quote(fname)}"
                            if dl_url in used_urls:
                                continue
                            dl = requests.get(dl_url, headers=headers, timeout=45)
                            if dl.status_code == 200:
                                with open(out_path, "wb") as f:
                                    f.write(dl.content)
                                if is_valid_video(out_path):
                                    used_urls.add(dl_url)
                                    print(f"Scene {index} OK (Archive): {dl_url}")
                                    return True
        except Exception as e:
            print("Archive search skip:", e)

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

    # Bước 4: Tải 5 cảnh Video quay thật & chuẩn hóa cùng hệ màu/khung hình 720x1280 HD mượt mà
    used_urls = set()
    clip_files = []
    for i, q in enumerate(scene_queries):
        raw_vid = f"raw_{i}.video"
        clip_name = f"clip_{i}.mp4"
        if subagent_keyless_footage_hunter(q, i, raw_vid, used_urls):
            subprocess.run([
                "ffmpeg", "-y", "-stream_loop", "-1", "-i", raw_vid,
                "-vf", "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,setsar=1,fps=30,format=yuv420p,eq=brightness=0.02:saturation=1.12,fade=t=in:st=0:d=0.35,fade=t=out:st=5.65:d=0.35",
                "-t", "6", "-an", "-c:v", "libx264", "-preset", "fast", "-crf", "23", clip_name
            ], check=True)
        else:
            # Nếu vẫn thiếu 1 cảnh lẻ, tạo hiệu ứng ánh sáng chuyển động sóng nhẹ thay vì màu chết đứng im
            subprocess.run([
                "ffmpeg", "-y", "-f", "lavfi",
                "-i", "gradients=s=720x1280:c0=#1e130c:c1=#c5a059:duration=6:speed=0.05:r=30",
                "-vf", "setsar=1,format=yuv420p,fade=t=in:st=0:d=0.35,fade=t=out:st=5.65:d=0.35",
                "-t", "6", "-c:v", "libx264", "-preset", "fast", clip_name
            ], check=True)
        clip_files.append(clip_name)

    # Bước 5: Nối 5 luồng hình bằng filter_complex (KHÔNG dùng -c:v copy để tránh mất hình trên Windows/Drive)
    inputs_cmd = []
    for cf in clip_files:
        inputs_cmd.extend(["-i", cf])
    concat_filter = "".join([f"[{idx}:v:0]" for idx in range(len(clip_files))]) + f"concat=n={len(clip_files)}:v=1:a=0[outv]"

    subprocess.run([
        "ffmpeg", "-y",
        *inputs_cmd,
        "-i", "final_audio.m4a",
        "-filter_complex", concat_filter,
        "-map", "[outv]", "-map", f"{len(clip_files)}:a:0",
        "-c:v", "libx264", "-profile:v", "main", "-pix_fmt", "yuv420p", "-crf", "24",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart", "-shortest", "final_30s.mp4"
    ], check=True)

if __name__ == "__main__":
    asyncio.run(main())
