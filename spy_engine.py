#!/usr/bin/env python3
"""
SpyEngine - Motore di ricerca per singolo target.
Rifattorizzazione di spy_everything.py come classe per multi-spy.
"""
import time
import requests
import re
import json
import os
import base64
import threading
from datetime import datetime, timezone
from bs4 import BeautifulSoup

from ollama_queue import OllamaQueue


def carica_env(path=".env"):
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and val and key not in os.environ:
                os.environ[key] = val


carica_env()


class SpyEngine:
    """Motore di ricerca per un singolo target/configurazione."""

    def __init__(self, config_path, ollama_queue):
        self.config_path = config_path
        self.ollama_queue = ollama_queue

        # Deriva nome spy dal filename
        basename = os.path.splitext(os.path.basename(config_path))[0]
        self.name = basename.replace("spy_config_", "") if basename.startswith("spy_config_") else basename

        # Carica configurazione
        self.config = self._carica_config()

        # File di memoria per-spy
        self.seen_file = f"seen_ads_{self.name}.json"
        self.price_history_file = f"price_history_{self.name}.json"
        self.uncertain_file = f"incerti_{self.name}.json"

        # Parametri da config
        self.item_desc = self.config.get("item_description", "oggetto")
        self.ricerche = self.config.get("search_keywords", [])
        self.budget = self.config.get("budget", {}).get("configurations", {})
        if not self.budget:
            self.budget = {"standard": self.config.get("budget", {}).get("default", 100)}
        self.interval = self.config.get("interval_seconds", 300)
        self.max_history = self.config.get("max_history", 200)

        self.vision_enabled = self.config.get("vision_enabled", True) and ollama_queue.is_healthy()
        self.context_enabled = self.config.get("context_check_enabled", True) and ollama_queue.is_healthy()

        self.p_escluse = [w.lower() for w in self.config.get("exclude_words", [])]
        self.p_richieste = [w.lower() for w in self.config.get("required_words", [])]
        self.p_distrattori = [w.lower() for w in self.config.get("distractor_words", [])]
        self.marche_premium = [w.lower() for w in self.config.get("premium_brands", [])]
        self.positive_kw = {k.lower(): v for k, v in self.config.get("positive_keywords", {}).items()}
        self.negative_kw = [w.lower() for w in self.config.get("negative_keywords", [])]
        self.config_patterns = self.config.get("config_patterns", {})
        self.reject_patterns = self.config.get("reject_patterns", [])
        self.platforms = self.config.get("platforms", ["VINTED", "SUBITO", "EBAY", "WALLAPOP"])

        # Memoria persistente
        self.annunci_visti = set(self._carica_json(self.seen_file, []))
        self.price_history = self._carica_json(self.price_history_file, [])

        # Telegram (condiviso da env)
        self.telegram_token = os.environ.get("TELEGRAM_TOKEN", "")
        self.telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

        print(f"[{self.name}] Engine inizializzato | keywords={len(self.ricerche)} | platforms={self.platforms}")

    def _carica_config(self):
        with open(self.config_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _carica_json(self, path, default):
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except:
                pass
        return default

    def _salva_json(self, path, data):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _extract_json(self, text):
        if not text:
            return None
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except:
                pass
        return None

    def _registra_incerto(self, piattaforma, id_annuncio, titolo, prezzo, link, reason):
        incerti = self._carica_json(self.uncertain_file, [])
        if any(item.get("id") == id_annuncio for item in incerti):
            return
        incerti.append({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "piattaforma": piattaforma, "id": id_annuncio,
            "titolo": titolo, "prezzo": prezzo, "link": link, "motivo": reason
        })
        self._salva_json(self.uncertain_file, incerti[-150:])
        print(f"  [{self.name}] [LOG INCERTI] Salvato in {self.uncertain_file}")

    def _invia_telegram(self, messaggio):
        if not self.telegram_token or not self.telegram_chat_id:
            return
        url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
        payload = {
            "chat_id": self.telegram_chat_id, 
            "text": messaggio, 
            "parse_mode": "HTML", 
            "disable_web_page_preview": True
        }
        try:
            requests.post(url, json=payload, timeout=15)
        except Exception as e:
            print(f"[{self.name}] Errore Telegram: {e}")

    def _scarica_immagine(self, url):
        if not url or not url.startswith("http"):
            return None
        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code == 200:
                try:
                    from PIL import Image
                    import io
                    img = Image.open(io.BytesIO(r.content))
                    if img.mode in ("RGBA", "P"):
                        img = img.convert("RGB")
                    img.thumbnail((512, 512))
                    output = io.BytesIO()
                    img.save(output, format="JPEG", quality=75)
                    return base64.b64encode(output.getvalue()).decode("utf-8")
                except:
                    return base64.b64encode(r.content).decode("utf-8")
        except:
            pass
        return None

    def _vision_check(self, image_b64, item_desc):
        if not self.vision_enabled or not self.ollama_queue.is_healthy():
            return True, "Vision OFF"

        prompt = (
            f"Analyze this image for: {item_desc}. "
            "CRITICAL: Check physical size. SODIMM (notebook) is ~67mm short with 260 pins. "
            "UDIMM (desktop) is ~133mm long with 288 pins. Count pins if visible. "
            "If the stick is SHORT, it is SODIMM (notebook/laptop) — REJECT for desktop. "
            "If the stick is LONG, it is UDIMM (desktop) — ACCEPT. "
            "Be concise. Answer ONLY with JSON: "
            '{"correct":true/false, "confidence":0-100, "reason":"max 10 words"}'
        )

        event = threading.Event()
        result = {"ok": True, "reason": "Vision inconclusiva"}

        def callback(resp, err):
            if err:
                result["reason"] = f"Vision error: {err}"
            else:
                data = self._extract_json(resp)
                if data:
                    ok = data.get("correct", True)
                    conf = data.get("confidence", 0)
                    reason = data.get("reason", "")
                    if not ok and conf >= 70:
                        result["ok"] = False
                        result["reason"] = f"{reason} (conf {conf}%)"
                    else:
                        result["ok"] = True
                        result["reason"] = f"{reason} (conf {conf}%)"
                else:
                    result["reason"] = "Vision inconclusiva (parse failed)"
            event.set()

        self.ollama_queue.submit(
            prompt, images=[image_b64], 
            priority=OllamaQueue.PRIORITY_VISION, 
            timeout=45, 
            callback=callback
        )

        if event.wait(timeout=60):
            return result["ok"], result["reason"]
        else:
            return True, "Vision timeout"

    def _context_check(self, titolo, descrizione, image_b64=None, item_desc=""):
        if not self.context_enabled or not self.ollama_queue.is_healthy():
            return False, "Context OFF", None, None

        prompt = (
            f"Analyze this Italian marketplace listing. User wants: {item_desc}. "
            f"Title: {titolo}\nDescription: {descrizione}\n\n"
            "CRITICAL RULES:\n"
            "1. ACCEPTED configurations: 1x32GB, 2x16GB (32GB total), 1x16GB, 4x32GB (128GB total).\n"
            "2. REJECTED configurations: ANY 8GB module (1x8GB, 2x8GB, 4x8GB), 2x8GB=16GB is NOT acceptable because user wants 16GB or 32GB modules, not 8GB sticks.\n"
            "3. If the listing is for a COMPLETE PC, LAPTOP, or BUNDLE and the seller does NOT explicitly state they sell RAM separately with its OWN price → REJECT.\n"
            "4. If the price shown is ONLY for the complete bundle → REJECT.\n"
            "5. If the description says 'non separo', 'vendo solo completo' → REJECT.\n"
            "6. If the RAM is SODIMM (notebook/laptop) → REJECT.\n"
            "7. ONLY accept if: standalone RAM, UDIMM/desktop, configuration in ACCEPTED list, with clear individual price.\n"
            "Answer ONLY with JSON: "
            '{"sells_item":true/false, "config":"...", "price_eur":number_or_null, "confidence":0-100, "reason":"max 15 words"}'
        )

        event = threading.Event()
        result = {"sells": False, "reason": "Context inconclusivo", "config": None, "price": None}

        def callback(resp, err):
            if err:
                result["reason"] = f"Context error: {err}"
            else:
                data = self._extract_json(resp)
                if data:
                    sells = data.get("sells_item", False)
                    conf = data.get("confidence", 0)
                    config = data.get("config")
                    price = data.get("price_eur")
                    reason = data.get("reason", "")
                    if sells and conf >= 60:
                        result["sells"] = True
                        result["reason"] = reason
                        result["config"] = config
                        result["price"] = price
                    else:
                        result["sells"] = False
                        result["reason"] = reason
                else:
                    result["reason"] = "Context inconclusivo (parse failed)"
            event.set()

        self.ollama_queue.submit(
            prompt, 
            images=[image_b64] if image_b64 else None, 
            priority=OllamaQueue.PRIORITY_CONTEXT, 
            timeout=60, 
            callback=callback
        )

        if event.wait(timeout=75):
            return result["sells"], result["reason"], result["config"], result["price"]
        else:
            return False, "Context timeout", None, None

    def _normalizza(self, text):
        return text.lower().strip()

    def _contiene_parola_esclusa(self, testo):
        if not testo:
            return False
        return any(p in self._normalizza(testo) for p in self.p_escluse)

    def _contiene_distrattore(self, testo):
        if not testo:
            return False
        return any(p in self._normalizza(testo) for p in self.p_distrattori)

    def _e_annuncio_valido(self, titolo, descrizione=""):
        full = self._normalizza(titolo + " " + descrizione)
        if self.p_richieste and not any(p in full for p in self.p_richieste):
            return False
        if self._contiene_parola_esclusa(titolo) or self._contiene_parola_esclusa(descrizione):
            return False
        if self._contiene_distrattore(titolo) or self._contiene_distrattore(descrizione):
            return False
        return True

    def _analizza_configurazione(self, titolo, descrizione=""):
        t = self._normalizza(titolo + " " + descrizione)
        for pat in self.reject_patterns:
            if pat.lower() in t:
                return ("RIGETTATO", 0, 0)
        for config_name, patterns in self.config_patterns.items():
            for pat in patterns:
                if pat.lower() in t:
                    return (config_name, 0, 85)
        return ("standard", 0, 70)

    def _calcola_score(self, titolo, prezzo, config_tipo):
        t = self._normalizza(titolo)
        score = 70
        for marca in self.marche_premium:
            if marca in t:
                score += 5
                break
        for kw, bonus in self.positive_kw.items():
            if kw in t:
                score += bonus
        for kw in self.negative_kw:
            if kw in t:
                score -= 20
        budget = self.budget.get(config_tipo, self.budget.get("standard", 999))
        if budget > 0:
            ratio = prezzo / budget
            if ratio <= 0.5: score += 10
            elif ratio <= 0.7: score += 5
            elif ratio <= 0.9: score += 2
            elif ratio >= 1.0: score -= 15
        return max(0, min(100, score))

    def _calcola_media_prezzi(self, config_tipo):
        simili = [p for p in self.price_history if p.get("config") == config_tipo]
        if len(simili) < 3:
            return None
        return sum(p["prezzo"] for p in simili[-50:]) / len(simili[-50:])

    def _registra_prezzo(self, prezzo, config_tipo):
        self.price_history.append({
            "prezzo": prezzo, 
            "config": config_tipo, 
            "timestamp": datetime.now().isoformat()
        })
        if len(self.price_history) > self.max_history:
            self.price_history = self.price_history[-self.max_history:]
        self._salva_json(self.price_history_file, self.price_history)

    def _formatta_messaggio(self, piattaforma, titolo, prezzo, link, config_tipo, score, extra_info=""):
        emoji = {"VINTED": "👕", "EBAY": "🛒", "SUBITO": "📰", "WALLAPOP": "🌍"}
        e = emoji.get(piattaforma, "🔍")
        stelle = "AFFARE ECCEZIONALE" if score >= 90 else "Ottimo" if score >= 75 else "Buono" if score >= 60 else "Discreto"
        budget = self.budget.get(config_tipo, self.budget.get("standard", 0))
        riga_budget = f"Budget: <b>{budget:.0f}EUR</b>\n"
        media = self._calcola_media_prezzi(config_tipo)
        riga_media = ""
        if media and prezzo < media:
            riga_media = f"Prezzo medio: <b>{media:.0f}EUR</b>  |  Risparmi: <b>{int((1-prezzo/media)*100)}%</b>\n"
        elif media:
            riga_media = f"Prezzo medio: <b>{media:.0f}EUR</b>\n"
        riga_extra = f"{extra_info}\n" if extra_info else ""
        return (
            f"[{self.name.upper()}] {e} <b>{piattaforma}</b>\n {titolo}\n"
            f" <b>{prezzo:.0f}EUR</b>  |   {config_tipo}\n"
            f"{riga_budget}{riga_media}{riga_extra}"
            f"Score: <b>{score}/100</b>  -  {stelle}\n"
            f'<a href="{link}">Apri annuncio</a>'
        )

    def processa_annuncio(self, piattaforma, id_annuncio, titolo, prezzo, link, descrizione="", img_url=None, extra_info=""):
        if id_annuncio in self.annunci_visti:
            return False

        # Se descrizione vuota, usa il titolo come fallback
        check_text = descrizione if descrizione else titolo

        # SEMPRE chiama Context Check se abilitato — il model decide tutto
        if self.context_enabled and check_text:
            b64 = self._scarica_immagine(img_url) if img_url else None
            ok, reason, config_override, price_override = self._context_check(titolo, check_text, b64, self.item_desc)
            if ok:
                config_tipo = config_override if config_override else "standard"
                if price_override:
                    prezzo = price_override
                budget = self.budget.get(config_tipo, self.budget.get("standard", 999))
                if prezzo > budget:
                    print(f"  [{self.name}] Context check: prezzo {prezzo}EUR oltre budget {budget}EUR")
                    return False
                extra_info = f"Context: {reason}"
                print(f"  [{self.name}] Context check: {reason}")
            else:
                print(f"  [{self.name}] Context check: {reason}")
                return False
        else:
            # Fallback: filtri base se Context Check disabilitato
            is_valid = self._e_annuncio_valido(titolo, descrizione)
            if not is_valid:
                print(f"  [{self.name}] Scartato: {titolo[:50]}...")
                return False
            config_tipo, _, _ = self._analizza_configurazione(titolo, descrizione)
            if config_tipo == "RIGETTATO":
                return False
            budget = self.budget.get(config_tipo, self.budget.get("standard", 999))
            if prezzo > budget:
                return False

        score = self._calcola_score(titolo, prezzo, config_tipo)
        if score < 40:
            return False

        vision_info = ""
        if self.vision_enabled and img_url:
            b64 = self._scarica_immagine(img_url) if img_url else None
            if b64:
                ok, reason = self._vision_check(b64, self.item_desc)
                vision_info = reason
                if not ok:
                    if "non raggiungibile" in reason or "Timeout" in reason:
                        print(f"  [{self.name}] Vision fallita ({reason}), rimando")
                        return False
                    print(f"  [{self.name}] Vision: {reason}")
                    self.annunci_visti.add(id_annuncio)
                    self._salva_json(self.seen_file, list(self.annunci_visti))
                    return False

        info_completa = extra_info + ("\n " + vision_info if vision_info else "")
        msg = self._formatta_messaggio(piattaforma, titolo, prezzo, link, config_tipo, score, info_completa)
        self._invia_telegram(msg)
        self.annunci_visti.add(id_annuncio)
        self._salva_json(self.seen_file, list(self.annunci_visti))
        self._registra_prezzo(prezzo, config_tipo)
        print(f"  [{self.name}] NOTIFICATO: {titolo[:55]}... | {prezzo}EUR | {config_tipo} | Score {score}")
        return True


    def controlla_subito(self):
        if "SUBITO" not in self.platforms:
            return
        print(f"[{self.name}] [Subito] Controllo con Playwright (Monotab isolato)...")
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            print("  [!] Playwright non installato")
            return

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=["--disable-dev-shm-usage", "--no-sandbox", "--disable-setuid-sandbox", "--disable-gpu"]
                )
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0",
                    locale="it-IT"
                )

                for keyword in self.ricerche:
                    annunci_da_processare = []
                    page = context.new_page()
                    
                    try:
                        page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "stylesheet", "font", "media"] else route.continue_())
                        q = keyword.replace(" ", "%20")
                        page.goto(f"https://www.subito.it/annunci-italia/vendita/usato/?q={q}&o=date", timeout=20000)
                        page.wait_for_selector("[data-cy='item-card']", timeout=10000)

                        cards = page.locator("[data-cy='item-card']").all()
                        for card in cards[:10]:
                            try:
                                link_el = card.locator("a").first
                                href = link_el.get_attribute("href")
                                if not href: continue
                                link = href if href.startswith("http") else f"https://www.subito.it{href}"

                                match_id = re.search(r'-([a-f0-9]+)$', link)
                                id_ann = f"subito_{match_id.group(1)}" if match_id else f"subito_{hash(link)}"
                                if id_ann in self.annunci_visti: continue

                                titolo = card.locator("h2").first.text_content().strip()
                                prezzo_text = card.locator("[data-cy='item-price']").first.text_content() or ""
                                match_prezzo = re.search(r'(\d+(?:[.,]\d+)?)', prezzo_text)
                                prezzo = float(match_prezzo.group(1).replace(",", ".")) if match_prezzo else 999.0

                                annunci_da_processare.append({
                                    "id": id_ann, "link": link, "titolo": titolo, "prezzo": prezzo
                                })
                            except:
                                continue
                    except Exception as e:
                        print(f"  [!] Errore Subito ricerca '{keyword}': {e}")
                    finally:
                        page.close()

                    # Estrazione dei dettagli uno alla volta in modo isolato
                    for ann in annunci_da_processare:
                        desc = ""
                        img_url = None
                        detail_page = context.new_page()
                        
                        try:
                            detail_page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "stylesheet", "font", "media"] else route.continue_())
                            detail_page.goto(ann["link"], timeout=15000)

                            desc_el = detail_page.locator("[data-cy='ad-description']").first
                            if desc_el.count() > 0:
                                desc = desc_el.text_content() or ""

                            img_el = detail_page.locator("img").first
                            if img_el.count() > 0:
                                img_url = img_el.get_attribute("src")
                        except Exception:
                            pass
                        finally:
                            detail_page.close()

                        self.processa_annuncio("SUBITO", ann["id"], ann["titolo"], ann["prezzo"], ann["link"], desc, img_url)

                browser.close()
        except Exception as e:
            print(f"[!] Errore critico Subito Playwright: {e}")

    def controlla_vinted(self):
        if "VINTED" not in self.platforms:
            return
        print(f"[{self.name}] [Vinted] Controllo con Playwright (Monotab isolato)...")
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            print("  [!] Playwright non installato")
            return

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=["--disable-dev-shm-usage", "--no-sandbox", "--disable-setuid-sandbox", "--disable-gpu"]
                )
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0",
                    locale="it-IT"
                )

                for keyword in self.ricerche:
                    annunci_da_processare = []
                    page = context.new_page()
                    
                    try:
                        page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "stylesheet", "font", "media"] else route.continue_())
                        q = keyword.replace(" ", "%20")
                        page.goto(f"https://www.vinted.it/catalog?search_text={q}&order=newest_first", timeout=20000)
                        page.wait_for_selector("[data-testid='grid-item']", timeout=10000)

                        items = page.locator("[data-testid='grid-item']").all()
                        for item in items[:10]:
                            try:
                                link_el = item.locator("a").first
                                href = link_el.get_attribute("href")
                                if not href: continue
                                link = href if href.startswith("http") else f"https://www.vinted.it{href}"

                                match_id = re.search(r'/items/(\d+)', link)
                                id_ann = f"vinted_{match_id.group(1)}" if match_id else f"vinted_{hash(link)}"
                                if id_ann in self.annunci_visti: continue

                                titolo = item.text_content() or ""
                                titolo = titolo.strip().split("\n")[0]
                                match_prezzo = re.search(r'(\d+(?:[.,]\d+)?)\s*€', titolo)
                                prezzo = float(match_prezzo.group(1).replace(",", ".")) if match_prezzo else 999.0

                                annunci_da_processare.append({
                                    "id": id_ann, "link": link, "titolo": titolo, "prezzo": prezzo
                                })
                            except:
                                continue
                    except Exception as e:
                        print(f"  [!] Errore Vinted ricerca '{keyword}': {e}")
                    finally:
                        page.close()

                    for ann in annunci_da_processare:
                        desc = ""
                        img_url = None
                        detail_page = context.new_page()
                        
                        try:
                            detail_page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "stylesheet", "font", "media"] else route.continue_())
                            detail_page.goto(ann["link"], timeout=15000)

                            desc_el = detail_page.locator("[data-testid='description']").first
                            if desc_el.count() > 0:
                                desc = desc_el.text_content() or ""

                            img_el = detail_page.locator("img").first
                            if img_el.count() > 0:
                                img_url = img_el.get_attribute("src")
                        except Exception:
                            pass
                        finally:
                            detail_page.close()

                        self.processa_annuncio("VINTED", ann["id"], ann["titolo"], ann["prezzo"], ann["link"], desc, img_url)

                browser.close()
        except Exception as e:
            print(f"[!] Errore critico Vinted Playwright: {e}")

    def controlla_wallapop(self):
        if "WALLAPOP" not in self.platforms:
            return
        print(f"[{self.name}] [Wallapop] Controllo con Playwright (Monotab isolato)...")
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            print("  [!] Playwright non installato")
            return

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=["--disable-dev-shm-usage", "--no-sandbox", "--disable-setuid-sandbox", "--disable-gpu"]
                )
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0",
                    locale="it-IT"
                )

                for keyword in self.ricerche:
                    annunci_da_processare = []
                    page = context.new_page()
                    
                    try:
                        page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "stylesheet", "font", "media"] else route.continue_())
                        q = keyword.replace(" ", "%20")
                        # Utilizziamo l'ordinamento più recente debuggato in precedenza
                        page.goto(f"https://it.wallapop.com/app/search?keywords={q}&filters_source=search_box&order_by=newest", timeout=20000)
                        page.wait_for_selector("tsl-public-item-card", timeout=10000)

                        cards = page.locator("tsl-public-item-card").all()
                        for card in cards[:10]:
                            try:
                                link_el = card.locator("a.ItemCard__title").first
                                href = link_el.get_attribute("href")
                                if not href: continue
                                link = href if href.startswith("http") else f"https://it.wallapop.com{href}"

                                match_id = re.search(r'-(\d+)$', link)
                                id_ann = f"wallapop_{match_id.group(1)}" if match_id else f"wallapop_{hash(link)}"
                                if id_ann in self.annunci_visti: continue

                                titolo = link_el.text_content().strip()
                                
                                prezzo_el = card.locator(".ItemCard__price").first
                                prezzo_text = prezzo_el.text_content() if prezzo_el.count() > 0 else "999"
                                match_prezzo = re.search(r'(\d+(?:[.,]\d+)?)', prezzo_text)
                                prezzo = float(match_prezzo.group(1).replace(",", ".")) if match_prezzo else 999.0

                                annunci_da_processare.append({
                                    "id": id_ann, "link": link, "titolo": titolo, "prezzo": prezzo
                                })
                            except:
                                continue
                    except Exception as e:
                        print(f"  [!] Errore Wallapop ricerca '{keyword}': {e}")
                    finally:
                        page.close()

                    # Estrazione dei dettagli anche per Wallapop per permettere all'LLM di leggere la descrizione profonda
                    for ann in annunci_da_processare:
                        desc = ""
                        img_url = None
                        detail_page = context.new_page()
                        
                        try:
                            detail_page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "stylesheet", "font", "media"] else route.continue_())
                            detail_page.goto(ann["link"], timeout=15000)

                            # Selettore per la descrizione di Wallapop verificato
                            desc_el = detail_page.locator(".item-detail__description").first
                            if desc_el.count() > 0:
                                desc = desc_el.text_content() or ""

                            img_el = detail_page.locator(".item-detail-images___image img").first
                            if img_el.count() > 0:
                                img_url = img_el.get_attribute("src")
                        except Exception:
                            pass
                        finally:
                            detail_page.close()

                        self.processa_annuncio("WALLAPOP", ann["id"], ann["titolo"], ann["prezzo"], ann["link"], desc, img_url)

                browser.close()
        except Exception as e:
            print(f"[!] Errore critico Wallapop Playwright: {e}")

    def controlla_ebay(self):
        if "EBAY" not in self.platforms:
            return
        app_id = os.environ.get(self.config.get("ebay_app_id_env", "EBAY_APP_ID"))
        if not app_id:
            print(f"[{self.name}] [eBay] API key mancante, salto")
            return

        print(f"[{self.name}] [eBay] Controllo via API...")
        endpoint = "https://svcs.ebay.com/services/search/FindingService/v1"

        for idx, keyword in enumerate(self.ricerche):
            params = {
                "OPERATION-NAME": "findItemsByKeywords",
                "SERVICE-VERSION": "1.0.0",
                "SECURITY-APPNAME": app_id,
                "RESPONSE-DATA-FORMAT": "JSON",
                "REST-PAYLOAD": "",
                "keywords": keyword,
                "paginationInput.entriesPerPage": 10,
                "paginationInput.pageNumber": 1,
                "sortOrder": "StartTimeNewest",
                "GLOBAL-ID": "EBAY-IT",
            }
            try:
                r = requests.get(endpoint, params=params, timeout=20)
                if r.status_code != 200:
                    print(f"  [{self.name}] eBay HTTP {r.status_code}")
                    continue
                data = r.json()
                resp = data.get("findItemsByKeywordsResponse", [{}])[0]
                result = resp.get("searchResult", [{}])[0]
                items = result.get("item", [])

                for item in items:
                    id_item = item.get("itemId", [None])[0]
                    if not id_item:
                        continue
                    id_ann = f"ebay_{id_item}"
                    if id_ann in self.annunci_visti:
                        continue

                    titolo = item.get("title", [""])[0]
                    selling = item.get("sellingStatus", [{}])[0]
                    curr_price = selling.get("currentPrice", [{}])[0]
                    try: prezzo = float(curr_price.get("__value__", "999"))
                    except: prezzo = 999.0

                    link = item.get("viewItemURL", [""])[0]
                    img_url = item.get("galleryURL", [""])[0] or None

                    extra_info = ""
                    listing_info = item.get("listingInfo", [{}])[0]
                    listing_type = listing_info.get("listingType", [""])[0]
                    end_time_str = listing_info.get("endTime", [None])[0]

                    if listing_type in ["Auction", "AuctionWithBIN"] and end_time_str:
                        try:
                            end_time = datetime.fromisoformat(end_time_str.replace("Z", "+00:00"))
                            hours_left = (end_time - datetime.now(timezone.utc)).total_seconds() / 3600
                            if hours_left > 24:
                                print(f"  [{self.name}] Asta scade tra {hours_left:.0f}h, skip")
                                continue
                            extra_info = f"Asta: scade in {hours_left:.0f}h"
                        except:
                            pass

                    self.processa_annuncio("EBAY", id_ann, titolo, prezzo, link, "", img_url, extra_info)
            except Exception as e:
                print(f"  [{self.name}] Errore eBay '{keyword}': {e}")

            if idx < len(self.ricerche) - 1:
                time.sleep(3)

    def run_cycle(self):
        """Esegue un ciclo completo di ricerca su tutte le piattaforme."""
        print(f"\n[{self.name}] === Ciclo avviato {datetime.now().strftime('%H:%M:%S')} ===")
        self.controlla_vinted()
        time.sleep(2)
        self.controlla_subito()
        time.sleep(2)
        self.controlla_ebay()
        time.sleep(2)
        self.controlla_wallapop()
        print(f"[{self.name}] === Ciclo completato. Prossimo check tra {self.interval}s ===\n")

    def startup_message(self):
        """Invia messaggio di avvio su Telegram."""
        self._invia_telegram(
            f"🕵️ <b>{self.name.upper()}</b> attivo!\n"
            f"Target: <b>{self.item_desc}</b>\n"
            f"Budget: {json.dumps(self.budget)}\n"
            f"Piattaforme: {', '.join(self.platforms)}\n"
            f"Vision: <b>{'ON' if self.vision_enabled else 'OFF'}</b>\n"
            f"Context: <b>{'ON' if self.context_enabled else 'OFF'}</b>"
        )