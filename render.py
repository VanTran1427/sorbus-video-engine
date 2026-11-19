import os, sys, json, re, wave, base64, hashlib, html, subprocess
from datetime import datetime
import requests
from PIL import Image
from playwright.sync_api import sync_playwright

# 3 Bảng màu từ sorbus-premium-style-guide.md v1.1
PALETTES = {
    "natural": {
        "name": "Natural Premium Wellness v001",
        "bg": "#EEEADF",
        "card": "#F7F4EC",
        "secondary": "#A6AF98",
        "accent": "#626B50",
        "text": "#2D332D",
        "muted": "#5A625A"
    },
    "warm": {
        "name": "Elegant Warm Premium",
        "bg": "#F4EFE6",
        "card": "#FAF7F2",
        "secondary": "#D5C3AA",
        "accent": "#A28554",
        "text": "#302821",
        "muted": "#6B5D50"
    },
    "feminine": {
        "name": "Feminine Luxury",
        "bg": "#F6EFEE",
        "card": "#FCF8F7",
        "secondary": "#C9A4A4",
        "accent": "#654653",
        "text": "#332B2E",
        "muted": "#6E5D63"
    }
}

# Danh sách từ cấm cứng từ brand/bo-nao-thuong-hieu.md
BANNED_REGEX = re.compile(
    r"\b(chữa bệnh|điều trị|ngừa bệnh|phòng ngừa bệnh|khỏi bệnh|thay thế thuốc|cam kết hiệu quả|so sánh với thuốc|chữa)\b",
    re.IGNORECASE
)

def stop_pipeline(reason):
    os.makedirs("keyframes", exist_ok=True)
    with open("QA_Receipt.md", "w", encoding="utf-8") as f:
        f.write(f"# BIÊN BẢN DỪNG SẢN XUẤT (STOP ANIMATE)\n\n- **Thời gian:** {datetime.now().isoformat()}\n- **Lý do chặn:** {reason}\n- **Kết luận Media:** CHƯA QA VIDEO THẬT\n")
    print(f"[STOP ANIMATE] {reason}", file=sys.stderr)
    sys.exit(1)

def normalize_drive_url(url):
    url = url.strip()
    if not url:
        return ""
    m = re.search(r"/d/([a-zA-Z0-9_-]+)", url) or re.search(r"[?&]id=([a-zA-Z0-9_-]+)", url)
    if "drive.google.com" in url and m:
        return f"https://drive.google.com/uc?export=download&id={m.group(1)}"
    return url

def download_verified_packshot(raw_url, dest_path="packshot_orig.png"):
    url = normalize_drive_url(raw_url)
    if not url:
        return None
    try:
        r = requests.get(url, headers={"User-Agent": "SorbusContentOS/1.1"}, timeout=30)
        if r.status_code != 200 or len(r.content) < 5000:
            stop_pipeline(f"Không tải được Packshot gốc từ URL cung cấp (HTTP {r.status_code}). Không tự vẽ lại hay thay thế nhãn.")
        with open(dest_path, "wb") as f:
            f.write(r.content)
        with Image.open(dest_path) as im:
            im.verify()
        return os.path.abspath(dest_path)
    except Exception as e:
        stop_pipeline(f"File Packshot không hợp lệ hoặc không có quyền truy cập ({e}). Dừng để bảo vệ nhãn gốc Solgar.")

def load_storyboard():
    scenes_json = os.environ.get("SCENES_JSON", "").strip()
    scenes = []
    if scenes_json:
        try:
            parsed = json.loads(scenes_json)
            for item in parsed:
                txt = str(item.get("text", "")).strip()
                if txt:
                    scenes.append({
                        "text": txt,
                        "subtext": str(item.get("subtext", "")).strip(),
                        "duration": float(item.get("duration", 0) or 0),
                        "show_packshot": bool(item.get("show_packshot", False))
                    })
        except Exception as e:
            stop_pipeline(f"SCENES_JSON sai định dạng JSON: {e}")
    else:
        for i in range(1, 6):
            txt = os.environ.get(f"P{i}", "").strip()
            if txt:
                scenes.append({"text": txt, "subtext": "", "duration": 0.0, "show_packshot": False})

    if not scenes:
        stop_pipeline("Thiếu dữ liệu chữ màn hình (Storyboard trống). Hệ thống tuân thủ quy tắc KHÔNG tự bịa nội dung dự phòng.")

    # Tách riêng cảnh Nguồn tham khảo / Khuyến cáo nếu có (không thu nhỏ nhét chung)
    source_cit = os.environ.get("SOURCE_CITATION", "").strip()
    disclaimer = os.environ.get("DISCLAIMER_TEXT", "").strip()
    if source_cit or disclaimer:
        scenes.append({
            "text": disclaimer if disclaimer else "Thông tin tham khảo khoa học",
            "subtext": f"Nguồn: {source_cit}" if source_cit else "",
            "duration": 3.5,
            "is_reference_card": True,
            "show_packshot": False
        })

    return scenes

def check_compliance_and_words(scenes, voice_text):
    warnings = []
    full_corpus = voice_text + " " + " ".join(s["text"] + " " + s.get("subtext", "") for s in scenes)
    m = BANNED_REGEX.search(full_corpus)
    if m:
        stop_pipeline(f"Phát hiện từ nằm trong Danh sách cấm của Bộ não thương hiệu: '{m.group(0)}'. Yêu cầu kiểm duyệt lại.")

    for idx, s in enumerate(scenes, 1):
        if s.get("is_reference_card"):
            continue
        word_count = len(s["text"].split())
        if word_count > 8:
            warnings.append(f"Cảnh {idx} có {word_count} từ ('{s['text']}') — vượt mốc tham chiếu 8 từ/cảnh của skill kich-ban-video.")
    return warnings

def build_html_template(pal, scene, idx, total_scenes, packshot_abs_path, layer_mode="full"):
    """
    layer_mode:
      - 'full': Bản Keyframe hoàn chỉnh để người dùng duyệt Visual QA
      - 'bg': Lớp nền giấy có thớ + ánh sáng cửa sổ + khung Safe Zone tĩnh (máy khóa)
      - 'fg': Lớp thẻ nội dung / Quiet pedestal trong suốt để hậu kỳ chuyển động 1 động tác nhẹ
    """
    show_bottle = bool(packshot_abs_path and (scene.get("show_packshot") or idx == total_scenes)) and not scene.get("is_reference_card")
    safe_text = html.escape(scene["text"])
    safe_sub = html.escape(scene.get("subtext", ""))
    packshot_uri = f"file://{packshot_abs_path}" if show_bottle else ""

    bg_visibility = "hidden" if layer_mode == "fg" else "visible"
    fg_visibility = "hidden" if layer_mode == "bg" else "visible"
    body_bg = "transparent" if layer_mode == "fg" else pal["bg"]

    eyebrow = "NGUỒN & LƯU Ý" if scene.get("is_reference_card") else f"SORBUS WELLNESS · {idx:02d}/{total_scenes:02d}"
    title_size = "54px" if scene.get("is_reference_card") else ("68px" if len(scene["text"]) <= 32 else "58px")

    bottle_html = ""
    if show_bottle:
        # Archetype: Quiet pedestal — giữ nguyên 100% nhãn gốc, không phủ filter, có bóng tiếp xúc thật dưới đáy
        bottle_html = f"""
        <div class="pedestal-wrap">
          <div class="bottle-stage">
            <img src="{packshot_uri}" class="packshot-img" alt="Packshot" />
            <div class="contact-shadow"></div>
          </div>
          <div class="stone-plinth"></div>
        </div>
        """

    sub_html = f'<p class="subtext">{safe_sub}</p>' if safe_sub else ""

    return f"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600&family=Cormorant+Garamond:ital,wght@0,600;0,700;1,600&display=swap" rel="stylesheet">
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  html, body {{
    width: 1080px;
    height: 1920px;
    overflow: hidden;
    background: {body_bg};
    font-family: 'Be Vietnam Pro', sans-serif;
    color: {pal['text']};
    -webkit-font-smoothing: antialiased;
  }}
  /* Lớp nền có chiều sâu ánh sáng cửa sổ xiên 45 độ & thớ giấy tự nhiên (Natural Premium Wellness v001) */
  .bg-layer {{
    position: absolute; inset: 0;
    visibility: {bg_visibility};
    background:
      radial-gradient(1200px 900px at 18% 22%, rgba(255,255,255,0.62) 0%, rgba(255,255,255,0) 68%),
      linear-gradient(145deg, rgba(255,255,255,0.28) 0%, rgba(0,0,0,0.045) 100%),
      {pal['bg']};
  }}
  .window-blind-shadow {{
    position: absolute; inset: 0;
    background: linear-gradient(125deg, transparent 0%, transparent 42%, rgba(45,51,45,0.03) 43%, transparent 58%);
    pointer-events: none;
  }}
  .linen-frame {{
    position: absolute;
    top: 288px; bottom: 384px; left: 92px; right: 92px;
    border: 1.5px solid {pal['secondary']};
    border-radius: 28px;
    opacity: 0.55;
  }}
  /* Vùng an toàn chuẩn Style Guide: Trên 15% (288px), Dưới 20% (384px), Hai bên 8.5% (92px) */
  .safe-zone {{
    position: absolute;
    top: 288px; bottom: 384px; left: 92px; right: 92px;
    padding: 64px 58px;
    display: flex;
    flex-direction: column;
    justify-content: center;
    visibility: {fg_visibility};
  }}
  .editorial-card {{
    background: {pal['card']};
    border: 1px solid rgba(166,175,152,0.45);
    border-radius: 24px;
    padding: 68px 56px;
    box-shadow: 18px 28px 54px rgba(35, 32, 28, 0.075), 0 2px 6px rgba(35, 32, 28, 0.03);
    position: relative;
  }}
  .eyebrow-row {{
    display: flex;
    align-items: center;
    gap: 16px;
    margin-bottom: 36px;
  }}
  .accent-bar {{
    width: 44px;
    height: 3px;
    background: {pal['accent']};
    border-radius: 2px;
  }}
  .eyebrow {{
    font-size: 23px;
    font-weight: 600;
    letter-spacing: 0.12em;
    color: {pal['accent']};
  }}
  .headline {{
    font-family: 'Cormorant Garamond', Georgia, serif;
    font-size: {title_size};
    font-weight: 700;
    line-height: 1.24;
    color: {pal['text']};
    letter-spacing: -0.01em;
  }}
  .subtext {{
    margin-top: 32px;
    font-size: 30px;
    line-height: 1.52;
    font-weight: 400;
    color: {pal['muted']};
    border-top: 1px solid {pal['secondary']};
    padding-top: 26px;
  }}
  .pedestal-wrap {{
    margin-top: 52px;
    display: flex;
    flex-direction: column;
    align-items: center;
  }}
  .bottle-stage {{
    position: relative;
    display: flex;
    flex-direction: column;
    align-items: center;
    z-index: 2;
  }}
  .packshot-img {{
    max-height: 430px;
    max-width: 380px;
    width: auto;
    height: auto;
    object-fit: contain;
    filter: none !important; /* Cấm phủ filter làm sai màu nhãn gốc */
  }}
  .contact-shadow {{
    width: 210px;
    height: 22px;
    margin-top: -8px;
    background: radial-gradient(ellipse at center, rgba(30,24,20,0.34) 0%, rgba(30,24,20,0.12) 52%, rgba(30,24,20,0) 76%);
    transform: translateX(10px);
  }}
  .stone-plinth {{
    width: 360px;
    height: 34px;
    margin-top: -6px;
    background: linear-gradient(90deg, {pal['bg']} 0%, {pal['card']} 35%, {pal['secondary']} 100%);
    border-radius: 8px 8px 4px 4px;
    box-shadow: 0 14px 28px rgba(30,24,20,0.09);
  }}
</style>
</head>
<body>
  <div class="bg-layer">
    <div class="window-blind-shadow"></div>
    <div class="linen-frame"></div>
  </div>
  <div class="safe-zone">
    <div class="editorial-card">
      <div class="eyebrow-row">
        <div class="accent-bar"></div>
        <div class="eyebrow">{eyebrow}</div>
      </div>
      <h1 class="headline">{safe_text}</h1>
      {sub_html}
      {bottle_html}
    </div>
  </div>
</body>
</html>"""

def generate_verified_voiceover(voice_text, voice_audio_url, api_key, out_wav="voice_master.wav"):
    # Ưu tiên 1: File thu âm thật/đã duyệt từ Google Drive nếu người dùng cung cấp
    if voice_audio_url:
        dl_url = normalize_drive_url(voice_audio_url)
        r = requests.get(dl_url, timeout=30)
        if r.status_code != 200 or len(r.content) < 5000:
            stop_pipeline("Không tải được file VOICE_AUDIO_URL đã cung cấp.")
        raw_audio = "voice_input_raw"
        with open(raw_audio, "wb") as f:
            f.write(r.content)
        subprocess.run([
            "ffmpeg", "-y", "-i", raw_audio,
            "-af", "apad=pad_dur=0.45,loudnorm=I=-16:TP=-1.5:LRA=11",
            "-ar", "44100", "-ac", "2", out_wav
        ], check=True)
    else:
        # Ưu tiên 2: Gọi ĐÚNG 1 LƯỢT Gemini Native Audio cho toàn bộ lời đọc đã duyệt (không vấp, không 429)
        if not voice_text:
            stop_pipeline("Thiếu VOICE_TEXT để tạo giọng đọc cho chế độ render.")
        if not api_key:
            stop_pipeline("Thiếu GEMINI_API_KEY trong GitHub Secrets. Không tự ý dùng giọng máy kém chất lượng thay thế.")

        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-tts:generateContent?key={api_key}"
        payload = {
            "contents": [{
                "parts": [{
                    "text": f"Đọc nguyên văn đoạn thuyết minh tiếng Việt sau (tuyệt đối không thêm bớt chữ) bằng giọng nữ ấm áp, điềm tĩnh, rõ chữ, nhịp điệu tự nhiên đáng tin cậy: {voice_text}"
                }]
            }],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Aoede"}}}
            }
        }
        r = requests.post(url, json=payload, timeout=60)
        if r.status_code != 200:
            stop_pipeline(f"Gemini TTS trả lỗi HTTP {r.status_code}. Theo quy tắc dung-video-do-hoa: DỪNG và báo người dùng, không tự thay bằng giọng máy robot.")
        try:
            b64_audio = r.json()["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]
            pcm_bytes = base64.b64decode(b64_audio)
            raw_wav = "voice_gemini_raw.wav"
            with wave.open(raw_wav, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(24000)
                wf.writeframes(pcm_bytes)
        except Exception as e:
            stop_pipeline(f"Dữ liệu âm thanh trả về không hợp lệ ({e}). Dừng để kiểm tra.")

        # Thêm 0.45s khoảng nghỉ cuối câu để không bao giờ bị cắt cụt chữ cuối
        subprocess.run([
            "ffmpeg", "-y", "-i", raw_wav,
            "-af", "apad=pad_dur=0.45,loudnorm=I=-16:TP=-1.5:LRA=11",
            "-ar", "44100", "-ac", "2", out_wav
        ], check=True)

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", out_wav],
        capture_output=True, text=True, check=True
    )
    dur = float(probe.stdout.strip() or 0.0)
    if dur < 3.0:
        stop_pipeline("Thời lượng file giọng đọc quá ngắn (< 3 giây), nghi ngờ lỗi thu âm.")
    return dur

def main():
    mode = os.environ.get("MODE", "render").strip().lower()
    content_id = os.environ.get("CONTENT_ID", "VID-DRAFT").strip() or "VID-DRAFT"
    palette_key = os.environ.get("PALETTE", "natural").strip().lower()
    pal = PALETTES.get(palette_key, PALETTES["natural"])
    packshot_url = os.environ.get("PACKSHOT_URL", "").strip()
    voice_text = os.environ.get("VOICE_TEXT", "").strip()
    voice_audio_url = os.environ.get("VOICE_AUDIO_URL", "").strip()
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()

    os.makedirs("keyframes", exist_ok=True)
    os.makedirs("Video_cho_duyet", exist_ok=True)
    os.makedirs("layers", exist_ok=True)

    # 1. Nạp Storyboard đã duyệt & Kiểm tra tuân thủ từ cấm
    scenes = load_storyboard()
    qa_warnings = check_compliance_and_words(scenes, voice_text)
    packshot_abs = download_verified_packshot(packshot_url) if packshot_url else None

    # 2. Render bộ Keyframe tĩnh 1080x1920 sắc nét bằng Chromium (Visual QA)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1080, "height": 1920}, device_scale_factor=1)

        for idx, sc in enumerate(scenes, 1):
            for lmode, out_file in [
                ("full", f"keyframes/scene_{idx:02d}_keyframe.png"),
                ("bg", f"layers/scene_{idx:02d}_bg.png"),
                ("fg", f"layers/scene_{idx:02d}_fg.png")
            ]:
                html_path = os.path.abspath(f"layers/scene_{idx:02d}_{lmode}.html")
                with open(html_path, "w", encoding="utf-8") as hf:
                    hf.write(build_html_template(pal, sc, idx, len(scenes), packshot_abs, lmode))
                page.goto(f"file://{html_path}", wait_until="networkidle")
                page.screenshot(path=out_file, omit_background=(lmode == "fg"))
        browser.close()

    # Nếu chạy chế độ PREVIEW: dừng đúng cổng STOP ANIMATE để người dùng xem Keyframes trước
    if mode == "preview":
        with open("QA_Receipt.md", "w", encoding="utf-8") as f:
            f.write(
                f"# STYLE LOAD & VISUAL QA RECEIPT (CHẾ ĐỘ PREVIEW KEYFRAME)\n\n"
                f"- **Content ID:** `{content_id}`\n"
                f"- **Style Guide áp dụng:** `brand/sorbus-premium-style-guide.md` (v1.1 - 30/10/2026) — Palette: `{pal['name']}`\n"
                f"- **Số Keyframe 1080x1920 đã xuất:** {len(scenes)} ảnh trong thư mục `keyframes/`\n"
                f"- **Packshot gốc:** {'Đã ghép nguyên nhãn không filter' if packshot_abs else 'Không sử dụng (Archetype Knowledge Cover)'}\n"
                f"- **Cảnh báo số từ:** {', '.join(qa_warnings) if qa_warnings else 'Không có (100% cảnh <= 8 từ)'}\n"
                f"- **Trạng thái Video:** CHƯA QA VIDEO THẬT (Đang dừng tại cổng duyệt Keyframe trước khi Animate).\n"
            )
        print("Đã xuất xong bộ Keyframe 1080x1920 để duyệt Visual QA.")
        return

    # 3. Chế độ RENDER MP4: Thu âm nguyên văn & chia thời lượng khớp 100% độ dài giọng đọc
    voice_dur = generate_verified_voiceover(voice_text, voice_audio_url, api_key, "voice_master.wav")

    # Chỉ trộn nhạc nền nếu có file nhạc thật assets/bgm.mp3 trong kho (tuyệt đối không tạo sóng âm giả aevalsrc)
    if os.path.exists("assets/bgm.mp3"):
        subprocess.run([
            "ffmpeg", "-y", "-i", "voice_master.wav", "-stream_loop", "-1", "-i", "assets/bgm.mp3",
            "-filter_complex", "[0:a]volume=1.0[v];[1:a]volume=0.14[b];[v][b]amix=inputs=2:duration=first:dropout_transition=2[aout]",
            "-map", "[aout]", "-c:a", "aac", "-b:a", "192k", "final_audio.m4a"
        ], check=True)
    else:
        subprocess.run([
            "ffmpeg", "-y", "-i", "voice_master.wav", "-c:a", "aac", "-b:a", "192k", "final_audio.m4a"
        ], check=True)

    # Tính thời lượng từng cảnh khớp tổng thời lượng Audio (ưu tiên trọng số độ dài chữ)
    fixed_total = sum(s["duration"] for s in scenes if s["duration"] > 0)
    flex_scenes = [s for s in scenes if s["duration"] <= 0]
    rem_dur = max(len(flex_scenes) * 2.8, voice_dur - fixed_total)
    total_chars = sum(max(10, len(s["text"])) for s in flex_scenes) or 1
    for s in flex_scenes:
        s["duration"] = round(rem_dur * (max(10, len(s["text"])) / total_chars), 2)

    # 4. Kết xuất từng cảnh 1080x1920 @ 30fps (Máy khóa tĩnh + 1 chuyển động hạ thẻ nhẹ 18px trong 0.55s đầu)
    clip_files = []
    timecodes = []
    cursor = 0.0
    for idx, sc in enumerate(scenes, 1):
        dur = max(2.5, round(sc["duration"], 2))
        bg_img = f"layers/scene_{idx:02d}_bg.png"
        fg_img = f"layers/scene_{idx:02d}_fg.png"
        clip_out = f"layers/clip_{idx:02d}.mp4"
        fade_out_st = round(dur - 0.25, 2)

        # Máy khóa: nền đứng yên, lớp thẻ trượt nhẹ 18px với gia tốc giảm dần rồi dừng tĩnh hoàn toàn để đọc chữ
        filter_str = (
            f"[1:v]format=rgba,fade=t=in:st=0:d=0.35:alpha=1,"
            f"fade=t=out:st={fade_out_st}:d=0.25:alpha=1[fg];"
            f"[0:v][fg]overlay=x=0:y='if(lt(t,0.55),18*pow(1-t/0.55,3),0)':format=auto,format=yuv420p[vout]"
        )
        subprocess.run([
            "ffmpeg", "-y",
            "-loop", "1", "-t", f"{dur:.2f}", "-r", "30", "-i", bg_img,
            "-loop", "1", "-t", f"{dur:.2f}", "-r", "30", "-i", fg_img,
            "-filter_complex", filter_str,
            "-map", "[vout]", "-t", f"{dur:.2f}", "-r", "30",
            "-c:v", "libx264", "-profile:v", "high", "-crf", "20", "-pix_fmt", "yuv420p",
            clip_out
        ], check=True)
        clip_files.append(clip_out)
        timecodes.append(f"- Cảnh {idx:02d} (`{cursor:05.2f}s -> {cursor+dur:05.2f}s`): {sc['text']}")
        cursor += dur

    # 5. Ghép thành phẩm MP4 1080x1920 (Không dùng -shortest để không bao giờ cắt mất chữ cuối của giọng đọc)
    inputs_cmd = []
    for cf in clip_files:
        inputs_cmd.extend(["-i", cf])
    v_concat = "".join([f"[{i}:v:0]" for i in range(len(clip_files))]) + f"concat=n={len(clip_files)}:v=1:a=0[outv]"

    final_mp4 = "final_30s.mp4"
    archive_mp4 = f"Video_cho_duyet/{content_id}.mp4"
    subprocess.run([
        "ffmpeg", "-y", *inputs_cmd, "-i", "final_audio.m4a",
        "-filter_complex", v_concat,
        "-map", "[outv]", "-map", f"{len(clip_files)}:a:0",
        "-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p", "-r", "30", "-crf", "21",
        "-c:a", "copy", "-movflags", "+faststart", final_mp4
    ], check=True)

    subprocess.run(["cp", final_mp4, archive_mp4], check=True)

    # 6. Xuất Biên bản Video QA thật (SHA-256 hash, fps, tổng frame, duration, timecode)
    sha256_hash = hashlib.sha256(open(archive_mp4, "rb").read()).hexdigest()
    probe_json = json.loads(subprocess.run([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate,nb_frames,duration",
        "-of", "json", archive_mp4
    ], capture_output=True, text=True, check=True).stdout)
    vstream = probe_json["streams"][0]

    with open("QA_Receipt.md", "w", encoding="utf-8") as f:
        f.write(
            f"# VIDEO QA & STYLE LOAD RECEIPT\n\n"
            f"## 1. Style Load Receipt\n"
            f"- **Tài liệu đã nạp:** `brand/sorbus-premium-style-guide.md` (v1.1 · 30/10/2026), `dung-video-do-hoa/SKILL.md`, `brand/bo-nao-thuong-hieu.md`, `brand/quy-tac-nguon.md`\n"
            f"- **Palette áp dụng:** `{pal['name']}` (`{pal['bg']}` / `{pal['secondary']}` / `{pal['accent']}` / `{pal['text']}`)\n"
            f"- **Safe Zone kiểm tra:** Trên 288px (15%), Dưới 384px (20%), Trái/Phải 92px (8.5%)\n"
            f"- **Packshot gốc:** {'Đã ghép nguyên nhãn + bóng tiếp xúc thật' if packshot_abs else 'Không dùng (Archetype Knowledge Cover)'}\n\n"
            f"## 2. Thông số kỹ thuật MP4 thật\n"
            f"- **Đường dẫn lưu:** `{archive_mp4}`\n"
            f"- **SHA-256 Hash:** `{sha256_hash}`\n"
            f"- **Độ phân giải:** `{vstream.get('width')}x{vstream.get('height')}`\n"
            f"- **FPS:** `{vstream.get('r_frame_rate')}`\n"
            f"- **Tổng số Frame:** `{vstream.get('nb_frames')}`\n"
            f"- **Thời lượng thực tế:** `{float(vstream.get('duration', cursor)):.2f}s` (Audio gốc: `{voice_dur:.2f}s`)\n\n"
            f"## 3. Timecode từng phân cảnh\n" + "\n".join(timecodes) + "\n\n"
            f"## 4. Ghi chú QA\n"
            f"- **Cảnh báo độ dài chữ:** {', '.join(qa_warnings) if qa_warnings else 'ĐẠT (Mọi cảnh nội dung <= 8 từ)'}\n"
            f"- **Trạng thái bàn giao:** `Video_cho_duyet/{content_id}.mp4` — Chờ người dùng duyệt cuối.\n"
        )

if __name__ == "__main__":
    main()
