import io

from PIL import Image

from flowpost.config import Settings
from flowpost.services.ai import AIService
from flowpost.services.watermark import position_xy, render_photo, wm_cache_key, wm_configured


def _jpeg(w=800, h=600) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (20, 120, 200)).save(buf, "JPEG")
    return buf.getvalue()


def test_render_text_watermark_changes_corner_only():
    settings = {"type": "text", "text": "Наше місто", "position": "br", "opacity": 80, "scale": 30}
    out = Image.open(io.BytesIO(render_photo(_jpeg(), settings, None, None)))
    assert out.size == (800, 600)
    assert out.getpixel((10, 10)) == Image.open(io.BytesIO(_jpeg())).getpixel((10, 10))


def test_render_image_watermark():
    logo = io.BytesIO()
    Image.new("RGBA", (100, 50), (255, 255, 255, 255)).save(logo, "PNG")
    settings = {"type": "image", "image_file_id": "x", "position": "mc", "opacity": 50, "scale": 20}
    out = Image.open(io.BytesIO(render_photo(_jpeg(), settings, logo.getvalue(), None)))
    center = out.getpixel((400, 300))
    assert center != (20, 120, 200)


def test_positions_and_cache_key():
    assert position_xy((1000, 500), (100, 50), "tl") == (15, 15)
    assert position_xy((1000, 500), (100, 50), "br") == (885, 435)
    assert position_xy((1000, 500), (100, 50), "mc") == (450, 225)
    assert wm_cache_key(1, {"text": "a"}) != wm_cache_key(1, {"text": "b"})
    assert not wm_configured({}) and wm_configured({"text": "x"})


def test_ai_request_shape():
    service = AIService(Settings(bot_token="1:x", anthropic_api_key="sk-test", _env_file=None))
    assert service.enabled
    req = service._build_request("screenshot", text="чернетка", lang="uk", limit=1000, style="Коротко",
                                 instruction=None, image=(b"img", "image/jpeg"))
    assert req["model"] == "claude-opus-5"
    assert req["fallbacks"] == "default" and req["betas"] == ["server-side-fallback-2026-07-01"]
    assert req["output_config"] == {"effort": "medium"}
    content = req["messages"][0]["content"]
    assert content[0]["type"] == "image" and content[1]["type"] == "text"
    assert "Коротко" in req["system"][1]["text"]
    assert "thinking" not in req and "temperature" not in req


def test_ai_disabled_without_key():
    assert not AIService(Settings(bot_token="1:x", _env_file=None)).enabled
