from __future__ import annotations

from dataclasses import dataclass

from .models import Listing, SpyConfig, DecisionStatus
from .logger import SpyLogger
from .pipeline import ListingPipeline
from spyengine.ai.service import AIService
from spyengine.storage.memory import MemoryManager
from spyengine.storage.reports import DecisionReporter
from spyengine.services.notifier import TelegramNotifier
from spyengine.services.browser import BrowserManager
from spyengine.platforms.registry import PlatformRegistry
from spyengine.core.runtime import LimitTracker

@dataclass(frozen=True)
class RuntimeWritePolicy:
    persist_memory: bool
    persist_reports: bool
    send_notifications: bool


def runtime_write_policy(*, full_dry_run: bool = False, notification_dry_run: bool = False) -> RuntimeWritePolicy:
    """Resolve side effects for the two deliberately distinct dry-run modes."""
    return RuntimeWritePolicy(
        persist_memory=not full_dry_run,
        persist_reports=not full_dry_run,
        send_notifications=not (full_dry_run or notification_dry_run),
    )



class SpyEngineApp:
    def __init__(
        self,
        config: SpyConfig,
        ollama_queue,
        dry_run: bool = False,
        notification_dry_run: bool = False,
    ):
        self.config = config
        self.write_policy = runtime_write_policy(
            full_dry_run=dry_run,
            notification_dry_run=notification_dry_run,
        )
        self.logger = SpyLogger(config.name)
        self.memory = MemoryManager(config.name, config.max_history, read_only=not self.write_policy.persist_memory)
        self.reports = DecisionReporter(config.name, enabled=self.write_policy.persist_reports)
        self.browser = BrowserManager(self.logger)
        self.ai = AIService(ollama_queue, config.system_prompt, logger=self.logger)
        self.notifier = TelegramNotifier(dry_run=not self.write_policy.send_notifications)
        self.platforms = PlatformRegistry.create_enabled(config.platforms, config, self.logger, self.browser, self.memory)
        self.pipeline = ListingPipeline(config, self.memory, self.ai, logger=self.logger)

        self.logger.info("🕵️", f"Agente {config.name.upper()} pronto all'azione")
        self.logger.info("📋", f"Target: {config.item_description}")
        self.logger.info("🔍", f"Piattaforme attive: {', '.join([p.name for p in self.platforms])}")

    def format_message(self, listing: Listing, decision) -> str:
        emoji = {"VINTED": "👕", "EBAY": "🛒", "SUBITO": "📰", "WALLAPOP": "🌍", "MOCK": "🧪"}.get(listing.platform, "🔍")
        budget = self.pipeline.scoring.resolve_budget(decision.config)
        extra = f"{listing.extra_info}\n" if listing.extra_info else ""
        return (
            f"[{self.config.name.upper()}] {emoji} <b>{listing.platform}</b>\n"
            f"{listing.title}\n"
            f"<b>{listing.price:.0f}EUR</b> | {decision.config}\n"
            f"Budget: <b>{budget:.0f}EUR</b>\n"
            f"{extra}"
            f"Score: <b>{decision.score}/100</b>\n"
            f'<a href="{listing.url}">Apri annuncio</a>'
        )

    def run_once(self):
        self.logger.info("🔄", "=== CICLO avviato ===")
        stats = {"checked": 0, "notified": 0, "rejected": 0, "skipped": 0, "errors": 0}
        limit = LimitTracker(self.config.max_total_items)
        try:
            for platform in self.platforms:
                if not limit.allow():
                    self.logger.warning("Raggiunto max_total_items, interrompo il ciclo")
                    break
                self.logger.action(f"{platform.name} — ricerca in corso")
                try:
                    for listing in platform.search():
                        if not limit.allow():
                            self.logger.warning("Raggiunto max_total_items, interrompo la piattaforma corrente")
                            break
                        limit.seen()
                        stats["checked"] += 1
                        self.logger.think(f"Analizzo {listing.platform} | {listing.id} | {listing.title[:80]} | {listing.price:.0f}EUR")
                        decision = self.pipeline.process(listing)
                        self.reports.save(listing, decision)

                        if decision.status == DecisionStatus.ACCEPT:
                            self.notifier.send(self.format_message(listing, decision))
                            stats["notified"] += 1
                            self.logger.action(f"✅ NOTIFICATO: {listing.title[:60]}... | {listing.price:.0f}EUR | Score {decision.score}")
                        elif decision.status == DecisionStatus.SKIP:
                            stats["skipped"] += 1
                        else:
                            stats["rejected"] += 1
                except Exception as e:
                    stats["errors"] += 1
                    self.logger.error(f"Errore piattaforma {platform.name}: {e}")
        finally:
            self.browser.stop()

        self.logger.info(
            "📊",
            f"=== RIEPILOGO: controllati={stats['checked']} notificati={stats['notified']} "
            f"rifiutati={stats['rejected']} skip={stats['skipped']} errori={stats['errors']} ==="
        )
        return stats
