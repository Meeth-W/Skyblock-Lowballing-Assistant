"""The application shell.

Tabs, a status line, and the wiring between the controller and the views. No
chrome beyond that: the valuation tab is where the user lives, and everything
else is somewhere they go afterwards.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QStatusBar,
    QTabWidget,
    QWidget,
)

from ..api.coflnet import auction_url
from ..money import format_coins, format_coins_exact
from ..uplink import UplinkStatus
from .theme import ACCENT, GRID, INK_DIM, LOSS, SIZE_MICRO, stylesheet, ui_font
from .views.config import ConfigView
from .views.ledger import LedgerView
from .views.statistics import StatisticsView
from .views.valuation import ValuationView
from .widgets.links import ACTION_AH, ACTION_EXACT, ACTION_OPEN, ACTION_VIEW

if TYPE_CHECKING:  # the controller imports from this package, so only for types
    from ..controller import AppController


class MainWindow(QMainWindow):
    def __init__(self, controller: AppController) -> None:
        super().__init__()
        self.controller = controller
        self.setWindowTitle("Lowball")
        self.resize(1180, 760)
        self.setStyleSheet(stylesheet())

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.valuation = ValuationView()
        self.ledger = LedgerView(controller.ledger)
        self.statistics = StatisticsView(controller.ledger)
        self.tabs.addTab(self.valuation, "Valuation")
        self.tabs.addTab(self.ledger, "Ledger")
        self.config = ConfigView(controller)
        self.tabs.addTab(self.statistics, "Statistics")
        self.tabs.addTab(self.config, "Config")
        self.setCentralWidget(self.tabs)

        self._build_status_bar()
        self._connect()
        self._build_actions()

        self.tabs.currentChanged.connect(self._on_tab_changed)

    def _build_status_bar(self) -> None:
        bar = QStatusBar()
        bar.setSizeGripEnabled(False)
        self.setStatusBar(bar)

        self.uplink_label = QLabel("Mod not connected")
        self.uplink_label.setObjectName("dim")
        self.uplink_label.setFont(ui_font(SIZE_MICRO))
        self.message_label = QLabel("")
        self.message_label.setObjectName("faint")
        self.message_label.setFont(ui_font(SIZE_MICRO))

        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(GRID * 2, 0, GRID * 2, 0)
        row.setSpacing(GRID * 3)
        row.addWidget(self.uplink_label)
        row.addWidget(self.message_label, 1)
        bar.addPermanentWidget(holder, 1)

    def _connect(self) -> None:
        c = self.controller
        c.selection_changed.connect(self.valuation.set_items)
        c.item_pending.connect(self.valuation.show_pending)
        c.item_valued.connect(self.valuation.show_valuation)
        c.totals_changed.connect(self.valuation.set_totals)
        c.uplink_changed.connect(self._on_uplink)
        c.status_message.connect(self._on_message)
        c.ledger_changed.connect(self._on_ledger_changed)
        c.settled_trade.connect(self._on_settled)
        c.clipboard_requested.connect(self._on_clipboard)
        c.item_valued.connect(self._on_item_valued)

        self.valuation.item_selected.connect(self._on_item_selected)
        self.valuation.offer_made.connect(c.make_offer)
        self.valuation.offer_rejected.connect(c.reject_offer)
        self.valuation.sale_confirmed.connect(c.confirm_sale)
        self.valuation.estimate_overridden.connect(c.override_estimate)
        self.valuation.auction_action.connect(self._on_auction_action)
        self.ledger.changed.connect(self._on_ledger_written)
        self.ledger.status.connect(self._on_message)
        self.ledger.clear_confirmed.connect(self._clear_history)
        self.statistics.bucket_clicked.connect(self._on_bucket_clicked)
        self.config.rules_saved.connect(lambda: self._on_message("Rules reloaded"))
        self.config.values_saved.connect(lambda: self._on_message("Pricing reloaded"))
        self.config.settings_saved.connect(lambda: self._on_message("Settings saved"))

    def _build_actions(self) -> None:
        reload_rules = QAction("Reload rules", self)
        reload_rules.setShortcut(QKeySequence("Ctrl+R"))
        reload_rules.triggered.connect(self._reload_rules)
        self.addAction(reload_rules)

        rebuild = QAction("Rebuild projections", self)
        rebuild.triggered.connect(self._rebuild)
        self.addAction(rebuild)

    # ---- reacting to the controller -------------------------------------

    def _on_uplink(self, status: UplinkStatus) -> None:
        self.uplink_label.setText(status.label)
        self.uplink_label.setStyleSheet(
            f"color: {ACCENT};" if status.connected else f"color: {INK_DIM};"
        )

    def _on_message(self, text: str) -> None:
        self.message_label.setText(text)
        self.message_label.setStyleSheet(
            f"color: {LOSS};" if "limit" in text.lower() or "failed" in text.lower() else ""
        )
        # Messages are transient; the status line should not become a log.
        QTimer.singleShot(8000, lambda: self._clear_message(text))

    def _clear_message(self, text: str) -> None:
        if self.message_label.text() == text:
            self.message_label.setText("")

    def _on_ledger_changed(self) -> None:
        if self.tabs.currentWidget() is self.ledger:
            self.ledger.refresh()
        elif self.tabs.currentWidget() is self.statistics:
            self.statistics.refresh()

    def _on_tab_changed(self, index: int) -> None:
        widget = self.tabs.widget(index)
        if widget is self.ledger:
            self.ledger.refresh()
        elif widget is self.statistics:
            self.statistics.refresh()

    def _on_item_selected(self, index: int) -> None:
        items = self.controller.items
        if not (0 <= index < len(items)):
            return
        item = items[index]
        if item.valuation is not None and item.ladder is not None:
            self.valuation.show_valuation(index, item.valuation, item.ladder)
            self.controller.prefetch_seller(item.valuation)
        else:
            self.valuation.show_pending(index, item.sig)

    def _on_item_valued(self, index: int, valuation, _ladder) -> None:
        """Warm the seller name, but only for the item actually on screen.

        Every item in a trade is valued; only one of them is being looked at.
        Prefetching for all of them would spend rate-limit budget on listings
        nobody will click, during the window where the remaining valuations are
        still queued behind it.
        """
        if index == self.valuation.trade.selected_index:
            self.controller.prefetch_seller(valuation)

    # ---- reaching the listing behind a price -----------------------------

    def _on_auction_action(self, action: str, auction) -> None:
        """A market figure was clicked. Three of the four need no network."""
        if auction is None:
            return
        if action == ACTION_AH:
            self.controller.copy_ah_command(auction)
        elif action == ACTION_VIEW:
            self._on_clipboard(
                f"/viewauction {auction.uuid}", "Copied /viewauction for that listing"
            )
        elif action == ACTION_OPEN:
            QDesktopServices.openUrl(QUrl(auction_url(auction.uuid)))
            self._on_message("Opened the listing on SkyCofl")
        elif action == ACTION_EXACT:
            exact = format_coins_exact(auction.unit_price)
            self._on_clipboard(exact, f"Copied {exact}")

    def _on_clipboard(self, text: str, message: str) -> None:
        """The one place anything is written to the clipboard."""
        clipboard = QApplication.clipboard()
        if clipboard is None:  # headless, or a platform without one
            self._on_message("No clipboard available on this system")
            return
        clipboard.setText(text)
        self._on_message(message)

    def _on_settled(self, settled, matched_index) -> None:
        """A trade actually completed, according to the server's own message.

        Ground truth for the price, so it pre-fills the confirmation. It never
        confirms on the user's behalf: chat reports the trade as a whole, and
        when several items moved at once it cannot say which offer any part of
        the total settles. The click stays.
        """
        if not settled.is_purchase:
            return
        who = settled.counterparty or "someone"
        paid = format_coins(settled.coins_paid)
        if matched_index is None:
            self._on_message(
                f"Trade with {who}: paid {paid} for {settled.describe()}."
                " Several items moved, so confirm each offer yourself."
            )
            return

        self.tabs.setCurrentWidget(self.valuation)
        self.valuation.prefill_confirmation(matched_index, settled.coins_paid)
        self._on_message(
            f"Trade with {who}: paid {paid} for {settled.describe()}."
            " Confirm the offer to log it."
        )

    def _on_ledger_written(self) -> None:
        """An outcome was recorded, so every figure downstream is stale."""
        self.statistics.refresh()

    def _clear_history(self) -> None:
        """The user confirmed in the ledger; the controller does the erasing."""
        removed = self.controller.clear_history()
        self.ledger.refresh()
        self.statistics.refresh()
        self._on_message(f"Cleared {removed} recorded event(s)")

    def _on_bucket_clicked(self, bucket) -> None:
        """A band on the ageing chart, clicked through to the rows behind it."""
        from ..stats import queries

        label = bucket[0] if isinstance(bucket, tuple) else str(bucket)
        self.tabs.setCurrentWidget(self.ledger)
        self.ledger.filter.setCurrentText("In stock")
        self.ledger.refresh()
        self.ledger.filter_to_items(
            queries.items_in_age_band(self.controller.ledger.conn, label)
        )
        self._on_message(
            f"Showing the {label} band. Change the filter to see everything again."
        )

    # ---- actions ---------------------------------------------------------

    def _reload_rules(self) -> None:
        count = self.controller.reload_rules()
        self._on_message(f"Reloaded {count} rules")

    def _rebuild(self) -> None:
        applied = self.controller.ledger.rebuild()
        self.ledger.refresh()
        self.statistics.refresh()
        self._on_message(f"Replayed {applied} events")

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        open_sessions = [
            s for s in self.controller.sessions._sessions.values() if s.is_open and s.offers
        ]
        if open_sessions:
            answer = QMessageBox.question(
                self,
                "Offers still open",
                f"{len(open_sessions)} offer(s) have no outcome recorded.\n"
                "Log them as walked away?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            )
            if answer == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
            self.controller.abandon_all()
        self.controller.stop()
        event.accept()
