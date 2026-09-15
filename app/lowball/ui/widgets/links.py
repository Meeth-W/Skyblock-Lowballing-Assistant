"""Prices you can act on.

Every figure in this app that came from one identifiable listing is also a way
to get to that listing. A lowballer quoting a price is asked "where are you
getting that from" several times an hour, and the answer -- the actual auction
the number came from -- was until now something they had to go and find by
hand while the customer waited.

The affordance is deliberately quiet. These are still numbers being read out
loud, so they are not dressed as buttons: they underline under the cursor and
nothing else. The app's rule that structure is a hairline holds here too.

Left click does the thing the user wants ninety per cent of the time, which is
to put ``/ah <seller>`` on the clipboard so it can be pasted into chat. Right
click opens the rest: the listing in a browser, the direct ``/viewauction``
command, the exact figure.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QAction, QContextMenuEvent, QDesktopServices, QMouseEvent
from PySide6.QtWidgets import QLabel, QMenu, QWidget

from ...api import players
from ...api.models import Auction

#: Copy ``/ah <seller>``.  Needs the seller's name, which is a lookup.
ACTION_AH = "ah"
#: Copy ``/viewauction <uuid>``.  Lands on this exact listing, no lookup.
ACTION_VIEW = "viewauction"
#: Open the listing on SkyCofl in a browser.
ACTION_OPEN = "open"
#: Copy the price itself, in full.
ACTION_EXACT = "exact"


class AuctionLink(QLabel):
    """A price with the listing it came from behind it."""

    #: (action, auction) -- what to do, and which listing to do it to.
    activated = Signal(str, object)

    def __init__(
        self,
        text: str,
        auction: Auction | None,
        *,
        note: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(text, parent)
        self._auction = auction
        self._note = note
        self._apply_affordance()

    # ---- state -----------------------------------------------------------

    @property
    def auction(self) -> Auction | None:
        return self._auction

    def set_auction(self, auction: Auction | None) -> None:
        self._auction = auction
        self._apply_affordance()

    @property
    def is_live(self) -> bool:
        """A link needs a listing with a uuid; without one it is just a label."""
        return self._auction is not None and bool(self._auction.uuid)

    def _apply_affordance(self) -> None:
        self.setCursor(
            Qt.CursorShape.PointingHandCursor
            if self.is_live
            else Qt.CursorShape.ArrowCursor
        )
        self.setToolTip(self._describe())

    def _describe(self) -> str:
        """Built fresh, because the seller's name arrives after the price does.

        The lookup that turns an auctioneer id into a name is asynchronous and
        cached, so a tooltip composed once when the pane was built would go on
        saying the name was unknown long after it had arrived.
        """
        if not self.is_live:
            return self._note
        lines = [self._note] if self._note else []
        seller = self._auction.seller
        if seller:
            known = players.known(seller)
            lines.append(f"Seller: {known}" if known else "Seller: not looked up yet")
        lines.append("Click to copy /ah for the seller · right click for more")
        return "\n".join(lines)

    # ---- interaction -----------------------------------------------------

    def enterEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if self.is_live:
            self._underline(True)
            self.setToolTip(self._describe())
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self._underline(False)
        super().leaveEvent(event)

    def _underline(self, on: bool) -> None:
        font = self.font()
        if font.underline() == on:
            return
        font.setUnderline(on)
        self.setFont(font)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt naming
        # On release rather than press: a press that ends outside the label is
        # a cancelled click everywhere else in the interface, and a price that
        # copied itself the moment the button went down would be the one
        # control here that could not be backed out of.
        if (
            self.is_live
            and event.button() == Qt.MouseButton.LeftButton
            and self.rect().contains(event.position().toPoint())
        ):
            self.activated.emit(ACTION_AH, self._auction)
            return
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:  # noqa: N802 - Qt naming
        if not self.is_live:
            return
        menu = QMenu(self)
        # Dialogs set their own stylesheet; inheriting the window's keeps the
        # menu from arriving in the platform default palette.
        window = self.window()
        if window is not None:
            menu.setStyleSheet(window.styleSheet())
        for action, label in (
            (ACTION_AH, "Copy /ah for the seller"),
            (ACTION_VIEW, "Copy /viewauction for this listing"),
            (ACTION_OPEN, "Open the listing on SkyCofl"),
            (ACTION_EXACT, "Copy the exact amount"),
        ):
            entry = QAction(label, menu)
            entry.triggered.connect(
                lambda _checked=False, name=action: self.activated.emit(name, self._auction)
            )
            menu.addAction(entry)
        menu.exec(event.globalPos())


class UrlLink(QLabel):
    """A figure that stands for a market rather than for one listing.

    The median is not an auction, so there is no ``/ah`` to copy and no listing
    to open -- but the item's own page on SkyCofl is where the sales behind it
    are, and that is worth one click. Same affordance as :class:`AuctionLink`
    so the two do not have to be told apart before being used.
    """

    def __init__(
        self,
        text: str,
        url: str,
        *,
        hint: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(text, parent)
        self._url = url
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lines = [hint] if hint else []
        lines.append("Click to open on SkyCofl")
        self.setToolTip("\n".join(lines))

    def enterEvent(self, event) -> None:  # noqa: N802 - Qt naming
        font = self.font()
        font.setUnderline(True)
        self.setFont(font)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt naming
        font = self.font()
        font.setUnderline(False)
        self.setFont(font)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt naming
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self.rect().contains(event.position().toPoint())
        ):
            QDesktopServices.openUrl(QUrl(self._url))
            return
        super().mouseReleaseEvent(event)
