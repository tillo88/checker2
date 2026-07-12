from __future__ import annotations
import base64, io, random, time
import requests
from PIL import Image
from spyengine.services.browser import get_random_user_agent


def image_url_to_b64(img_url: str | None, max_size_mb: int = 5, logger=None) -> str | None:
    if not img_url:
        return None
    try:
        time.sleep(random.uniform(0.3, 1.2))
        resp = requests.get(img_url, headers={"User-Agent": get_random_user_agent()}, timeout=15)
        if resp.status_code != 200:
            return None
        if len(resp.content) / (1024 * 1024) > max_size_mb:
            if logger:
                logger.think("Immagine troppo grande, salto vision")
            return None
        image = Image.open(io.BytesIO(resp.content))
        if image.mode != "RGB":
            image = image.convert("RGB")
        max_dim = 1024
        if max(image.size) > max_dim:
            ratio = max_dim / max(image.size)
            image = image.resize((int(image.size[0] * ratio), int(image.size[1] * ratio)), Image.LANCZOS)
        buf = io.BytesIO()
        image.save(buf, format="JPEG", quality=85)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception as e:
        if logger:
            logger.think(f"Errore elaborazione immagine: {e}")
        return None
